"""Hair Simulation — VBD-direction Phase 2: head-tracked VBD (α strategy).

**What this module owns**

  * The per-frame state (positions + velocities in world coords) held
    in `_prev_state`. Updated by exactly two authors, each of which
    commits both fields atomically at the end of the function:
      - `_capture_current_state` (reads EVALUATED from Blender; used
        on Start, Reset, frame-jump)
      - `_run_one_simulation_step` (uses VBD output; used on +1 step)
  * The full-animation RAM bake: parallel arrays
    `_bake_positions[n_frames, n_total, 3]` and
    `_bake_velocities[n_frames, n_total, 3]` plus a per-frame
    `_bake_mask` boolean. Allocated once at Start (or reused if size
    matches), sized by the scene's animation length.
  * The simulation step: NVIDIA Newton's `SolverVBD`. Hair roots are
    kinematic (mass=0 → driven by us each step from the evaluated
    Surface Deform output); other points are integrated under
    gravity + per-strand spring forces. Sloppy physics constants for
    the explosion test: any non-zero stiffness/damping; user-approved
    that hair may visibly explode as long as Python does not crash.
  * The scrub-restore behaviour: if the user enters a frame that has
    been baked, the baked state is pushed back to Blender — the
    simulator never re-derives it.

**α strategy: head-tracked roots + modifier offset compensation**

User-chosen pragmatic approach (acknowledged as not the architecturally
"pure" way; see CLAUDE.md / commit history for the discussion):

  * Surface Deform GN modifier ("サーフェス変形") stays active and is
    NOT muted. It provides per-frame head-tracked anchor positions
    via the EVALUATED Curves.
  * Every sim step:
      1. Read evaluated world positions (head-tracked) for all points.
      2. Read original world positions (what we wrote last frame).
      3. offset = evaluated - original  (per-particle additive modifier
         contribution; v0.0.27 verified the modifier composes ~additively).
      4. Build VBD input: prev non-root positions + new evaluated roots;
         derived root velocity = (new_eval - prev) / dt.
      5. VBD step → vbd_out in world coords, head-tracked.
      6. Write to ORIGINAL: vbd_out - offset. Modifier then produces
         evaluated = (vbd_out - offset) + offset = vbd_out → matches
         what VBD intended. No double-tracking.
  * `_prev_state` after each sim = VBD output (vbd_out), so the next
    step's "previous frame" is the head-tracked world view.

**What this module does NOT own**

  * Mode (Bypass / Simulating / Playback) — lives in
    `WindowManager.hair_sim_mode`, set by operators.
  * Which entry point to call per frame — that decision is in the
    `frame_change_post` handler in `__init__.py`.

**Three modes (decided by handler)**

  * SIMULATING → calls `step(scene)`:
      - If current frame is baked → restore from bake (scrub-back).
      - Else if current == _last_frame + 1 → run sim, capture, bake.
      - Else (jump into unbaked area) → re-baseline (capture with
        zero velocity), do NOT bake.

  * PLAYBACK → calls `playback(scene)`:
      - If current frame is baked → restore from bake.
      - Else → do nothing (Blender shows whatever obj.data currently
        contains; no implicit re-baseline).

  * BYPASS → handler returns early; this module is not called at all.

**Why `_last_frame` and `_prev_state` are always updated together**

Simulation = state evolution. To compute the next state we need the
previous state. If the two ever drifted apart, the next +1-frame step
would solve from stale data. They are updated atomically inside
`_capture_current_state` (and inside `_restore_from_bake`, which is
also a single-point write).

**HairFrameState contents**

  points_world      — (n_total, 3) float32, world coords. ALL points
                       (roots + every joint).
  velocities_world  — (n_total, 3) float32, world m/sec. Derived only
                       after a successful +1 simulation step. Zero on
                       Start / scrub-back / frame-jump.
  frame             — int, the frame this snapshot corresponds to.

**Modifier policy**

The target Curves object carries a Geometry Nodes modifier
"サーフェス変形". This module does NOT touch it. Verified
2026-05-26 (v0.0.27): writes to original `position` persist and
the Modifier composes its head-tracking offset additively on top.

**Phase 1 invariants preserved**

Exactly one persistent `frame_change_post` handler, gated by
`WindowManager.hair_sim_mode != "BYPASS"`. step() / playback() are
invoked at most once per frame change.
"""
from __future__ import annotations

from dataclasses import dataclass

import bpy
import numpy as np


TARGET_NAME        = "カーブ.001"
POINTS_PER_STRAND  = 8       # Uniform per Phase 3A scene investigation.

# Body collision target. The full CC_Base_Body (225,184 verts /
# 397,024 triangles) is registered as a Newton mesh collider so hair
# particles collide with the character's surface. This commit adds it
# as a STATIC mesh baked once at Start; the next commit will refresh
# the mesh per frame to track body skinning.
BODY_COLLISION_TARGET   = "CC_Base_Body"
BODY_COLLISION_ENABLED  = True

# VBD physics values, calibrated against the TinyVBD reference
# implementation (Siggraph 2024 author AnkaChan):
# https://github.com/AnkaChan/TinyVBD
# TinyVBD's default strand test ("initializeTilted") uses:
#   stiffness = 1e8, iterations = 100, substeps = 1, gravity = (0,-10,0),
#   skip spring stiffness = 100, kinematic root via mVelocity.col(0).setZero()
# We use lower main stiffness (1e6, not 1e8) as a conservative starting
# point; iter=60 in the 50-100 band. Substep=4 is retained per user
# (not TinyVBD's 1) so substep tuning is still available. Bending
# (skip spring) is enabled per TinyVBD recipe.
VBD_SPRING_KE          = 1e6     # spring stiffness (TinyVBD: 1e6–1e8)
VBD_SPRING_KD          = 1.0     # spring damping
VBD_FREE_PARTICLE_MASS = 0.01    # mass for non-root particles
                                 # ratio ke/mass = 1e8 matches TinyVBD's
                                 # default test (1e8 stiffness / mass=1).
                                 # Lower mass than 1.0 reduces visible
                                 # inertial drag when the head moves;
                                 # going further (0.001, 0.0001) caused
                                 # spring overshoot / strand buckling
                                 # (numerical instability at ke/m > 1e9).
VBD_GRAVITY            = -9.81   # m/s² along the up-axis (Z down)
VBD_ITERATIONS         = 60      # VBD inner iterations per solver.step()
                                 # (TinyVBD: 100)

# Bending (skip) spring: connect (i, i+2) per strand. TinyVBD's recipe:
# rest length = sum of two adjacent segments (= straight-line distance
# when initial pose is straight). Newton's add_spring auto-derives rest
# from initial positions (Euclidean), which equals the sum for a
# straight initial strand and respects natural curve otherwise.
VBD_BENDING_ENABLED    = True
VBD_BENDING_KE         = 100.0   # TinyVBD: 100 (much weaker than segment)
VBD_BENDING_KD         = 1.0

# Substepping. Each Blender frame is divided into N internal sim
# steps; per-substep dt = scene_dt / N. Smaller dt makes implicit
# integrators (VBD/XPBD) more compliant per step and dramatically
# improves constraint convergence and stability. Canonical lever
# for inextensible chain behaviour (Macklin "Small Steps" 2019).
VBD_SUBSTEPS           = 4

# Self-contact (particle-particle collision). Newton's SolverVBD has
# this OFF by default. We attempted to enable it at alpha-confirmed
# (commit fde65e0, v0.0.36) and found that SolverVBD's self-contact
# code path requires triangles in the model: the constructor accesses
# `particle_vertex_triangle_contact_filtering_list` which is only
# populated by `_compute_particle_contact_filtering_list` when
# `model.tri_count > 0`. Our spring-only hair model has zero triangles
# → AttributeError → build fails. KEPT OFF on this branch so VBD
# actually initializes; particle-particle conflict is left to bending
# constraints + careful tuning to manage.
VBD_SELF_CONTACT_ENABLED = False
VBD_SELF_CONTACT_RADIUS  = 0.005   # unused while disabled
VBD_SELF_CONTACT_MARGIN  = 0.005   # unused while disabled
# Newton 1.2.0 / Warp 1.13.0 on RTX 5070 Ti (sm_120 Blackwell):
# `cuda:0` finalize() succeeds but step() triggers "CUDA error 700:
# illegal memory access" mid-kernel, which corrupts the CUDA context
# for the rest of the Blender session. CPU mode runs the same model
# at ~19 ms/step for 35k particles + 31k springs, which is fast
# enough for the explosion test. Switch back to cuda:0 once Newton
# fixes the sm_120 + kinematic-particle + spring combo (or once we
# isolate which of those pieces is at fault).
VBD_DEVICE             = "cpu"
# Newton 1.2.0 is installed in user site (CLAUDE.md). Blender's bundled
# Python doesn't add user site to sys.path by default; we addsitedir on
# first VBD init.
VBD_USER_SITE          = r"C:\Users\azoo\AppData\Roaming\Python\Python313\site-packages"


@dataclass
class HairFrameState:
    """One frame's hair snapshot. All world coordinates. Sufficient to
    reproduce hair shape AND to drive next-frame physics."""
    points_world:     np.ndarray   # (n_total, 3) float32 — world coords
    velocities_world: np.ndarray   # (n_total, 3) float32 — world m/sec
    frame:            int


class WorldPassthrough:
    """Stateful manager of the state-evolution scaffolding + RAM bake.
    One instance is created on Start, lives across mode changes
    (Stop/Bypass do not tear it down), and is freed via teardown() on
    extension unregister."""

    def __init__(self) -> None:
        self._initialized       = False
        self._step_error_active = False
        self._target_obj_name   = None

        # Curves shape constants captured at Start.
        self._n_total           = 0
        self._root_indices      = None  # type: np.ndarray | None  shape (n_strands,) int32

        # State evolution bookkeeping — ALWAYS updated together.
        self._last_frame        = None  # type: int | None
        self._prev_state        = None  # type: HairFrameState | None

        # RAM bake cache (allocated at Start, sized by scene anim length).
        self._bake_positions    = None  # type: np.ndarray | None  shape (n_frames, n_total, 3)
        self._bake_velocities   = None  # type: np.ndarray | None  shape (n_frames, n_total, 3)
        self._bake_mask         = None  # type: np.ndarray | None  shape (n_frames,) bool
        self._bake_frame_start  = None  # type: int | None
        self._bake_frame_end    = None  # type: int | None

        # VBD solver state (built lazily on first sim step; reset on Start /
        # teardown). All arrays live on `_vbd_device`.
        self._vbd_solver        = None
        self._vbd_model         = None
        self._vbd_state_in      = None
        self._vbd_state_out     = None
        self._vbd_control       = None
        self._vbd_contacts      = None  # allocated when body collision is enabled
        self._vbd_device        = None
        self._vbd_module_warp   = None  # cached `import warp` handle

        # Body collision: id of the body-mesh shape inside the solver
        # model, and vertex count at Start. Per-frame vertex updates
        # use these to locate the warp Mesh and validate topology.
        self._collider_shape_id     = None
        self._body_collider_n_verts = 0

        # Per-call telemetry.
        self._step_count        = 0

    # ----------------------------------------------------------- #
    # Bake helpers
    # ----------------------------------------------------------- #

    def _allocate_bake(self, scene: bpy.types.Scene) -> None:
        """Allocate (or resize) the RAM bake to fit the scene's animation
        length. Reuses existing arrays if shape matches; in either case
        the per-frame `_bake_mask` is cleared so no frame is considered
        baked at the start of a new Start session."""
        fs = int(scene.frame_start)
        fe = int(scene.frame_end)
        if fe < fs:
            fe = fs
        n_frames = fe - fs + 1
        n_total  = self._n_total

        desired_shape = (n_frames, n_total, 3)
        need_realloc = (
            self._bake_positions is None
            or self._bake_positions.shape != desired_shape
        )
        if need_realloc:
            # Costly: ~0.5–1 GB on full-length animations. One-shot per
            # session (cf. user spec: "1回だけ初期化").
            self._bake_positions  = np.zeros(desired_shape, dtype=np.float32)
            self._bake_velocities = np.zeros(desired_shape, dtype=np.float32)
            self._bake_mask       = np.zeros(n_frames,      dtype=bool)
        else:
            self._bake_mask[:] = False

        self._bake_frame_start = fs
        self._bake_frame_end   = fe

    def _frame_to_bake_index(self, frame: int) -> int | None:
        """Map a Blender frame number to its bake-array index. Returns
        None if the frame is outside the allocated bake range."""
        if self._bake_frame_start is None or self._bake_frame_end is None:
            return None
        if frame < self._bake_frame_start or frame > self._bake_frame_end:
            return None
        return frame - self._bake_frame_start

    def _store_prev_state_to_bake(self) -> bool:
        """Write the current `_prev_state` into `_bake_*[index]` and
        flag the frame as baked. No-op (returns False) if `_prev_state`
        is None or its frame is outside the bake range."""
        if self._prev_state is None:
            return False
        idx = self._frame_to_bake_index(self._prev_state.frame)
        if idx is None:
            return False
        self._bake_positions [idx] = self._prev_state.points_world
        self._bake_velocities[idx] = self._prev_state.velocities_world
        self._bake_mask      [idx] = True
        return True

    def _restore_from_bake(self, frame: int) -> bool:
        """Push the baked state at `frame` to Blender's ORIGINAL Curves,
        and update `_prev_state` / `_last_frame` to match. Returns False
        if the frame is outside the bake range or not baked yet."""
        idx = self._frame_to_bake_index(frame)
        if idx is None or not self._bake_mask[idx]:
            return False
        obj = bpy.data.objects.get(self._target_obj_name)
        if obj is None:
            return False
        attr = obj.data.attributes.get("position")
        if attr is None or len(attr.data) != self._n_total:
            return False

        n          = self._n_total
        world_pts  = self._bake_positions [idx]
        velocities = self._bake_velocities[idx]

        # Convert world → local via matrix_world.inverted() and write.
        mw_inv  = np.array(obj.matrix_world.inverted(), dtype=np.float32)
        world_h = np.column_stack([world_pts, np.ones(n, dtype=np.float32)])
        local_h = world_h @ mw_inv.T
        local_pts = local_h[:, :3].astype(np.float32, copy=True)

        # local_pts is C-contiguous (astype(copy=True) above), so ravel()
        # returns a view; foreach_set accepts numpy arrays directly.
        attr.data.foreach_set("vector", local_pts.ravel())
        obj.data.update_tag()

        # Sync the per-frame state holder so future +1 steps work.
        self._prev_state = HairFrameState(
            points_world     = world_pts.copy(),
            velocities_world = velocities.copy(),
            frame            = frame,
        )
        self._last_frame = frame
        return True

    # ----------------------------------------------------------- #
    # State capture (single source of truth for _prev_state writes)
    # ----------------------------------------------------------- #

    def _read_world_positions(
        self,
        attributes_owner,
    ) -> np.ndarray | None:
        """Helper: read `position` from any attributes-owning data
        (`obj.data` for ORIGINAL or `obj.evaluated_get(dg).data` for
        EVALUATED / post-modifier), and convert to world coords via
        the Curves object's matrix_world. Returns (n_total, 3) float32
        or None on any sanity failure."""
        attr = attributes_owner.attributes.get("position")
        if attr is None or len(attr.data) != self._n_total:
            return None
        n = self._n_total
        local_flat = np.zeros(n * 3, dtype=np.float32)
        attr.data.foreach_get("vector", local_flat)
        local_pts = local_flat.reshape(n, 3)

        obj = bpy.data.objects.get(self._target_obj_name)
        if obj is None:
            return None
        mw      = np.array(obj.matrix_world, dtype=np.float32)
        local_h = np.column_stack([local_pts, np.ones(n, dtype=np.float32)])
        world_h = local_h @ mw.T
        return world_h[:, :3].astype(np.float32, copy=True)

    def _capture_current_state(
        self,
        scene: bpy.types.Scene,
        derive_velocity_from_prev: bool = False,
    ) -> bool:
        """Snapshot the current frame's full hair state (positions +
        velocities, world coords) — read from the EVALUATED data
        (post-Surface-Deform), so `_prev_state` always reflects the
        head-tracked world view.

        **Atomicity guarantee** (load-bearing for physics correctness):
        `_last_frame` and `_prev_state` are updated together at the end
        of the function, or both are cleared to None on any failure.
        They are NEVER left in a state where one reflects the new frame
        and the other is stale or None. A future +1-frame step would
        otherwise compute physics from inconsistent state.

        Velocity policy:
          derive_velocity_from_prev=True  → velocity = (new - prev) / dt
            Called only after a successful +1 simulation step.
          derive_velocity_from_prev=False → velocity = zeros
            Start, frame-jump, and any re-baselining event.

        Returns True if both fields were updated to the new captured
        state, False if both were cleared to None due to a failure."""
        prior = self._prev_state
        frame = scene.frame_current

        obj = bpy.data.objects.get(self._target_obj_name)
        if obj is None:
            self._last_frame = None
            self._prev_state = None
            return False

        # Read EVALUATED (post-modifier) positions — these include the
        # Surface Deform head-tracking offset, so prev_state.points_world
        # is the head-tracked world view of the hair.
        dg = bpy.context.evaluated_depsgraph_get()
        obj_eval = obj.evaluated_get(dg)
        world_pts = self._read_world_positions(obj_eval.data)
        if world_pts is None:
            self._last_frame = None
            self._prev_state = None
            return False

        # Derive velocities (or zero them on re-baselining events).
        if (
            derive_velocity_from_prev
            and prior is not None
            and prior.points_world.shape == world_pts.shape
        ):
            dt = float(scene.render.fps_base) / float(scene.render.fps)
            velocities_world = ((world_pts - prior.points_world) / dt).astype(
                np.float32, copy=False
            )
        else:
            velocities_world = np.zeros_like(world_pts)

        # Atomic commit: both fields updated together at the end.
        self._prev_state = HairFrameState(
            points_world     = world_pts,
            velocities_world = velocities_world,
            frame            = frame,
        )
        self._last_frame = frame
        return True

    # ----------------------------------------------------------- #
    # Simulation — NVIDIA Newton VBD (explosion test)
    # ----------------------------------------------------------- #

    def _add_body_collider(self, builder, newton) -> bool:
        """Register the body mesh as a kinematic collision shape.
        Reads the EVALUATED body mesh (post-Armature) at the current
        scene frame and converts to world coords, then adds it as a
        kinematic (mass=0) body with one triangle-mesh shape.

        Static bake — does NOT update per frame. The next commit adds
        the per-frame vertex refresh."""
        body_obj = bpy.data.objects.get(BODY_COLLISION_TARGET)
        if body_obj is None or body_obj.type != 'MESH':
            print(
                f"[hair_sim/vbd] body collision skipped: "
                f"'{BODY_COLLISION_TARGET}' not found or not a mesh"
            )
            return False

        dg = bpy.context.evaluated_depsgraph_get()
        body_eval = body_obj.evaluated_get(dg)
        body_data = body_eval.data

        n_v = len(body_data.vertices)
        if n_v == 0:
            print("[hair_sim/vbd] body collision skipped: empty mesh")
            return False
        v_flat = np.zeros(n_v * 3, dtype=np.float32)
        body_data.vertices.foreach_get("co", v_flat)
        v_local = v_flat.reshape(n_v, 3)

        body_mw = np.array(body_obj.matrix_world, dtype=np.float32)
        v_h = np.column_stack([v_local, np.ones(n_v, dtype=np.float32)])
        v_world = (v_h @ body_mw.T)[:, :3].astype(np.float32, copy=True)

        body_data.calc_loop_triangles()
        n_t = len(body_data.loop_triangles)
        if n_t == 0:
            print("[hair_sim/vbd] body collision skipped: no triangles")
            return False
        t_idx = np.zeros(n_t * 3, dtype=np.int32)
        body_data.loop_triangles.foreach_get("vertices", t_idx)

        try:
            body_mesh = newton.Mesh(
                vertices        = v_world,
                indices         = t_idx,
                compute_inertia = False,
                is_solid        = False,
            )
            collider_body_id = builder.add_body(mass=0.0, is_kinematic=True)
            collider_shape_id = builder.add_shape_mesh(
                body = collider_body_id,
                mesh = body_mesh,
            )
        except Exception as exc:
            print(f"[hair_sim/vbd] body collision build failed: {exc!r}")
            return False

        # Remember shape id + initial vertex count so per-frame vertex
        # updates can locate the warp Mesh in the finalized model and
        # validate topology hasn't changed.
        self._collider_shape_id     = collider_shape_id
        self._body_collider_n_verts = n_v

        print(
            f"[hair_sim/vbd] body collision: "
            f"target={BODY_COLLISION_TARGET!r}, n_verts={n_v}, n_tris={n_t}, "
            f"shape_id={collider_shape_id}, body_id={collider_body_id} "
            f"(per-frame vertex update enabled)"
        )
        return True

    def _update_body_collider_vertices(self) -> bool:
        """Per-frame body-mesh refresh: re-read evaluated body mesh,
        push new world-space vertex positions into the warp Mesh's
        `points` buffer in-place, and refit BVH so subsequent
        model.collide() sees the current geometry.

        Topology unchanged is assumed; silent no-op on vertex-count
        mismatch (the static initial mesh from Start remains valid)."""
        if self._collider_shape_id is None or self._vbd_model is None:
            return False
        wp = self._vbd_module_warp
        if wp is None:
            return False

        body_obj = bpy.data.objects.get(BODY_COLLISION_TARGET)
        if body_obj is None or body_obj.type != 'MESH':
            return False

        dg = bpy.context.evaluated_depsgraph_get()
        body_eval = body_obj.evaluated_get(dg)
        body_data = body_eval.data

        n_v = len(body_data.vertices)
        if n_v != self._body_collider_n_verts:
            return False

        v_flat = np.zeros(n_v * 3, dtype=np.float32)
        body_data.vertices.foreach_get("co", v_flat)
        v_local = v_flat.reshape(n_v, 3)
        body_mw = np.array(body_obj.matrix_world, dtype=np.float32)
        v_h = np.column_stack([v_local, np.ones(n_v, dtype=np.float32)])
        v_world = (v_h @ body_mw.T)[:, :3].astype(np.float32, copy=True)

        try:
            # After finalize(), `model.shape_source[shape_id]` is the
            # newton.Mesh we passed; its `.mesh` attribute is the
            # underlying wp.Mesh with mutable `.points` + `refit()`.
            newton_mesh = self._vbd_model.shape_source[self._collider_shape_id]
            warp_mesh = newton_mesh.mesh
            new_points = wp.from_numpy(
                v_world, dtype=wp.vec3, device=warp_mesh.device,
            )
            wp.copy(warp_mesh.points, new_points)
            warp_mesh.refit()
        except Exception as exc:
            print(f"[hair_sim/vbd] body collider vertex update failed (suppressing): {exc!r}")
            return False
        return True

    def _ensure_vbd_initialized(self) -> bool:
        """Lazy-build the Newton VBD model + solver from the current
        `_prev_state` topology. No-op if already built. Returns True on
        success."""
        if self._vbd_solver is not None:
            return True
        if self._prev_state is None:
            return False

        # Import Newton / Warp. Blender's bundled Python doesn't add the
        # user site to sys.path; do it here on first use.
        try:
            import sys, site
            if VBD_USER_SITE not in sys.path:
                site.addsitedir(VBD_USER_SITE)
            import newton
            import warp as wp
        except Exception as exc:
            print(f"[hair_sim/vbd] import failed: {exc!r}")
            return False

        try:
            builder = newton.ModelBuilder(up_axis=newton.Axis.Z, gravity=VBD_GRAVITY)

            n         = self._n_total
            n_strands = n // POINTS_PER_STRAND
            init_pts  = self._prev_state.points_world

            # Particles: roots (index % POINTS_PER_STRAND == 0) get mass=0
            # which Newton treats as kinematic (fixed at the given position).
            # Non-roots get a non-zero mass so they're integrated.
            for k in range(n):
                p = init_pts[k]
                is_root = (k % POINTS_PER_STRAND) == 0
                mass = 0.0 if is_root else VBD_FREE_PARTICLE_MASS
                builder.add_particle(
                    pos = (float(p[0]), float(p[1]), float(p[2])),
                    vel = (0.0, 0.0, 0.0),
                    mass = mass,
                )

            # Segment springs along each strand (distance constraints).
            # Rest length auto-derived from initial particle positions.
            for s in range(n_strands):
                base = s * POINTS_PER_STRAND
                for i in range(POINTS_PER_STRAND - 1):
                    builder.add_spring(
                        base + i, base + i + 1,
                        ke=VBD_SPRING_KE, kd=VBD_SPRING_KD, control=0.0,
                    )

            # Bending (skip) springs: connect (i, i+2) per strand. Per
            # TinyVBD's recipe. Weaker stiffness than segment springs;
            # provides bending resistance so the strand doesn't fold
            # at any joint while still allowing soft drape.
            n_bending = 0
            if VBD_BENDING_ENABLED:
                for s in range(n_strands):
                    base = s * POINTS_PER_STRAND
                    for i in range(POINTS_PER_STRAND - 2):
                        builder.add_spring(
                            base + i, base + i + 2,
                            ke=VBD_BENDING_KE, kd=VBD_BENDING_KD, control=0.0,
                        )
                        n_bending += 1

            # ----- Body collision (static mesh, baked at Start) ----- #
            if BODY_COLLISION_ENABLED:
                self._add_body_collider(builder, newton)

            # SolverVBD requires graph-colored particles for parallel
            # updates. finalize() does NOT color implicitly; we must do
            # it explicitly between topology setup and finalize.
            builder.color()

            # Finalize on CUDA, fall back to CPU on any failure.
            try:
                model  = builder.finalize(device=VBD_DEVICE)
                device = VBD_DEVICE
            except Exception as exc:
                print(f"[hair_sim/vbd] finalize on {VBD_DEVICE} failed: {exc!r}, falling back to cpu")
                model  = builder.finalize(device="cpu")
                device = "cpu"

            self._vbd_model       = model
            self._vbd_solver      = newton.solvers.SolverVBD(
                model,
                iterations                    = VBD_ITERATIONS,
                particle_enable_self_contact  = VBD_SELF_CONTACT_ENABLED,
                particle_self_contact_radius  = VBD_SELF_CONTACT_RADIUS,
                particle_self_contact_margin  = VBD_SELF_CONTACT_MARGIN,
            )
            self._vbd_state_in    = model.state()
            self._vbd_state_out   = model.state()
            self._vbd_control     = model.control()
            # Allocate Contacts buffer when body collision is enabled
            # so model.collide() has somewhere to write contact data.
            self._vbd_contacts    = model.contacts() if BODY_COLLISION_ENABLED else None
            self._vbd_device      = device
            self._vbd_module_warp = wp

            n_segment = n_strands * (POINTS_PER_STRAND - 1)
            print(
                f"[hair_sim/vbd] initialized on {device}: "
                f"n_particles={n}, "
                f"n_segment_springs={n_segment}, n_bending_springs={n_bending}, "
                f"iterations={VBD_ITERATIONS}, substeps={VBD_SUBSTEPS}, "
                f"ke={VBD_SPRING_KE}, kd={VBD_SPRING_KD}, "
                f"bending_ke={VBD_BENDING_KE if VBD_BENDING_ENABLED else 'off'}, "
                f"gravity={VBD_GRAVITY}"
            )
            return True
        except Exception as exc:
            print(f"[hair_sim/vbd] build failed: {exc!r}")
            # Roll back partial state.
            self._vbd_model = self._vbd_solver = None
            self._vbd_state_in = self._vbd_state_out = None
            self._vbd_control = None
            self._vbd_contacts = None
            self._vbd_device = None
            return False

    def _run_one_simulation_step(self, scene: bpy.types.Scene) -> bool:
        """Evolve state by exactly one frame using Newton's VBD solver.

        **Strategy α — head-tracked roots + modifier-offset compensation**

        The hair roots' world positions for the new frame are taken from
        the EVALUATED Curves (Surface Deform output), so VBD sees the
        head motion as a moving boundary condition. The non-root
        particles' world positions are carried over from the previous
        sim's output (held in `_prev_state`).

          Input to VBD:
            q [non_root]  = _prev_state.points_world[non_root]
            q [root]      = evaluated_world[root]                      ← head boundary
            qd[non_root]  = _prev_state.velocities_world[non_root]    ← inertia
            qd[root]      = 0                                          ← see warning below

        ⚠ Kinematic-root velocity is intentionally zero. XPBD's predict
        step (verified on a 2-particle probe at the XPBD line, v0.0.38)
        integrates ALL particles by `x_new = x_old + v*dt`, including
        mass=0 — it only skips constraint corrections. Passing the
        derived head velocity there causes `solver_out[root] =
        2*eval_now - eval_prev` (the "hair drifts 2× the head" bug).
        VBD's internal integration is different (energy-based,
        coordinate descent) and may not have the same bug, but the
        fix is harmless: in_q[root] = eval_now is authoritative,
        spring forces feel root motion through frame-to-frame position
        change, no velocity needs to be communicated for kinematic
        particles. Keeping it zero on VBD too as a defensive carryover.

        Spring forces (rest length fixed at the initial geometry) pull
        the non-root particles toward the moved roots over subsequent
        iterations, producing inertial trailing of the hair tips.

        VBD output is in world coords and is "head-tracked" (because
        the input was). To display correctly, we must NOT let the
        Surface Deform modifier add its head-tracking offset on top
        again. We measure the modifier's per-particle additive offset
        (`offset = evaluated - original`) and subtract it from the VBD
        output before writing to ORIGINAL. Modifier then computes
        `evaluated = written + offset = vbd_out`, matching VBD's view.

        Returns True on successful update (prev_state + _last_frame
        atomically committed), False on any failure (state unchanged)."""
        if self._prev_state is None:
            return False
        obj = bpy.data.objects.get(self._target_obj_name)
        if obj is None:
            return False
        if not self._ensure_vbd_initialized():
            return False

        wp     = self._vbd_module_warp
        n      = self._n_total
        device = self._vbd_device

        # 1. Read EVALUATED (head-tracked) world positions for this frame
        #    and the ORIGINAL (what we wrote last frame) world positions.
        #    The difference is the modifier's per-particle additive
        #    offset, used both for the (iii) writeback compensation and
        #    as the source of the new root anchor positions.
        dg = bpy.context.evaluated_depsgraph_get()
        obj_eval = obj.evaluated_get(dg)
        eval_world = self._read_world_positions(obj_eval.data)
        orig_world = self._read_world_positions(obj.data)
        if eval_world is None or orig_world is None:
            return False
        offset_world = eval_world - orig_world   # (n, 3) float32

        # 2. Build VBD input state. Carry non-root positions/velocities
        #    from previous sim; override roots with current evaluated
        #    positions and derived velocity (head motion this frame).
        dt = float(scene.render.fps_base) / float(scene.render.fps)

        in_q  = self._prev_state.points_world.copy()
        in_qd = self._prev_state.velocities_world.copy()

        root_indices = self._root_indices  # cached (n_strands,) int32
        in_q [root_indices]  = eval_world[root_indices]
        # ⚠ in_qd[root] MUST be zero — see function docstring. XPBD's
        # predict step would double-integrate if a non-zero velocity is
        # passed here; VBD may not have the same bug but the fix is
        # harmless and we keep it defensively.
        in_qd[root_indices]  = 0.0

        try:
            # 3a. Refresh body-collision mesh to track body skinning at
            #     this frame. Body pose doesn't change between substeps
            #     within one Blender frame, so this is done once per
            #     frame (not per substep).
            if BODY_COLLISION_ENABLED and self._vbd_contacts is not None:
                self._update_body_collider_vertices()

            # 3b. Copy initial state into the solver's input buffer.
            in_q_np  = np.ascontiguousarray(in_q,  dtype=np.float32)
            in_qd_np = np.ascontiguousarray(in_qd, dtype=np.float32)
            tmp_q  = wp.from_numpy(in_q_np,  dtype=wp.vec3, device=device)
            tmp_qd = wp.from_numpy(in_qd_np, dtype=wp.vec3, device=device)
            wp.copy(self._vbd_state_in.particle_q,  tmp_q)
            wp.copy(self._vbd_state_in.particle_qd, tmp_qd)

            # 3c. Substep loop. Each substep runs collide() + step() with
            #     dt_sub = dt / N. Smaller dt makes the implicit solver
            #     more compliant per step (XPBD: alpha = 1/(ke·dt²) grows;
            #     VBD: smaller backward-Euler residual) → much better
            #     convergence and stability ("Small Steps" Macklin 2019).
            n_substeps = max(1, int(VBD_SUBSTEPS))
            dt_sub = dt / float(n_substeps)
            state_in  = self._vbd_state_in
            state_out = self._vbd_state_out
            for _ in range(n_substeps):
                if BODY_COLLISION_ENABLED and self._vbd_contacts is not None:
                    self._vbd_model.collide(state_in, self._vbd_contacts)
                self._vbd_solver.step(
                    state_in,
                    state_out,
                    self._vbd_control,
                    self._vbd_contacts,
                    dt_sub,
                )
                # Swap so the next substep's input is this output.
                state_in, state_out = state_out, state_in

            # After N swaps, the latest result lives in `state_in`.
            # MUST copy (not view) — see XPBD-line bug discovery
            # (commit ba16162): wp.array.numpy() on CPU returns a view
            # backed by the same memory as state_in.particle_q. If we
            # kept the view, the next solver.step() would update it
            # in-place and our `_prev_state.points_world` reference
            # would silently change with it, breaking velocity
            # derivation `(new - prev) / dt = 0`.
            vbd_out = np.array(
                state_in.particle_q.numpy(),
                dtype=np.float32, copy=True,
            ).reshape(n, 3)
        except Exception as exc:
            print(f"[hair_sim/vbd] step failed (suppressing): {exc!r}")
            return False

        # 5. Writeback with modifier-offset compensation:
        #    target_eval = vbd_out, modifier(written) = written + offset,
        #    so write = vbd_out - offset → modifier produces vbd_out.
        write_world = vbd_out - offset_world

        # Convert world → local via matrix_world.inverted() and write.
        mw_inv  = np.array(obj.matrix_world.inverted(), dtype=np.float32)
        world_h = np.column_stack([write_world, np.ones(n, dtype=np.float32)])
        local_h = world_h @ mw_inv.T
        local_pts = local_h[:, :3].astype(np.float32, copy=True)

        attr = obj.data.attributes.get("position")
        if attr is None or len(attr.data) != n:
            return False
        attr.data.foreach_set("vector", local_pts.ravel())
        obj.data.update_tag()

        # 6. Atomic commit of prev_state + _last_frame.
        #    Note: this is the second author of (_last_frame, _prev_state)
        #    besides _capture_current_state. Both update both fields at
        #    the end, never leaving them inconsistent. This is the
        #    "after-sim" author; capture is the "from-Blender" author.
        #    Velocity derived from position diff (matches capture's
        #    derive_velocity_from_prev=True convention).
        new_vel = ((vbd_out - self._prev_state.points_world) / dt).astype(
            np.float32, copy=False
        )
        self._prev_state = HairFrameState(
            points_world     = vbd_out,
            velocities_world = new_vel,
            frame            = scene.frame_current,
        )
        self._last_frame = scene.frame_current
        return True

    # ----------------------------------------------------------- #
    # Lifecycle
    # ----------------------------------------------------------- #

    def start(self, obj, scene: bpy.types.Scene) -> bool:
        """Initialize / re-initialize the simulator at the current
        frame. Allocates (or reuses) the RAM bake, captures the current
        frame as the initial state, and stores it in the bake.

        Returns False on any of:
          * geometry sanity failure (wrong type, no attr, empty, non-uniform);
          * `scene.frame_current` outside `[scene.frame_start, frame_end]`
            (would silently bake nothing; reject explicitly so the user
            knows to move into range first);
          * initial-frame capture failure (e.g., attribute read failed)."""
        self._step_error_active = False
        self._initialized       = False
        self._last_frame        = None
        self._prev_state        = None

        if obj is None or obj.type != "CURVES":
            print(f"[hair_sim/passthrough] start failed: target must be CURVES (got {obj})")
            return False
        attr = obj.data.attributes.get("position")
        if attr is None:
            print("[hair_sim/passthrough] start failed: no 'position' attribute on target")
            return False
        n_total = len(attr.data)
        if n_total == 0:
            print(f"[hair_sim/passthrough] start failed: empty Curves (n_total={n_total})")
            return False
        if n_total % POINTS_PER_STRAND != 0:
            print(
                "[hair_sim/passthrough] start failed: n_total "
                f"({n_total}) not divisible by POINTS_PER_STRAND "
                f"({POINTS_PER_STRAND})"
            )
            return False

        # Bake-range check: current frame must be inside the animation
        # range, otherwise the initial state cannot be baked and
        # subsequent sim results would also fall outside the bake,
        # leading to silent "sim runs but nothing baked" confusion.
        fs = int(scene.frame_start)
        fe = int(scene.frame_end)
        fc = int(scene.frame_current)
        if fc < fs or fc > fe:
            print(
                "[hair_sim/passthrough] start failed: "
                f"current frame {fc} outside scene range [{fs}..{fe}] "
                "(move the playhead inside the range and try again)"
            )
            return False

        self._target_obj_name = obj.name
        self._n_total         = n_total
        self._step_count      = 0
        self._initialized     = True

        # Cache root indices (one per strand) for fast per-step
        # override of the head-tracked anchor positions.
        n_strands = n_total // POINTS_PER_STRAND
        self._root_indices = (np.arange(n_strands, dtype=np.int32)
                              * POINTS_PER_STRAND)

        # Invalidate any cached VBD state — the topology snapshot inside
        # the Newton model assumes the rest positions captured at this
        # Start. First sim step will rebuild it from the new _prev_state.
        self._vbd_solver    = None
        self._vbd_model     = None
        self._vbd_state_in  = None
        self._vbd_state_out = None
        self._vbd_control   = None
        self._vbd_contacts  = None
        self._collider_shape_id     = None
        self._body_collider_n_verts = 0

        # Allocate (or reuse) the RAM bake. Clears mask either way.
        self._allocate_bake(scene)

        # Capture and bake the initial frame. If capture fails, abort
        # cleanly so we never advertise initialized=True with no state.
        if not self._capture_current_state(scene, derive_velocity_from_prev=False):
            print("[hair_sim/passthrough] start failed: initial capture returned no state")
            self._initialized = False
            return False
        self._store_prev_state_to_bake()

        n_frames = self._bake_frame_end - self._bake_frame_start + 1
        bake_mb = self._bake_positions.nbytes / (1024 * 1024) if self._bake_positions is not None else 0
        print(
            "[hair_sim/passthrough] start ok: "
            f"target={obj.name!r}, n_total={n_total}, "
            f"start_frame={self._last_frame}, "
            f"bake_range=[{self._bake_frame_start}..{self._bake_frame_end}] "
            f"(n_frames={n_frames}, ~{bake_mb:.1f} MB × 2 buffers)"
        )
        return True

    def teardown(self) -> None:
        """Free all per-session state. Called by extension `unregister()`.
        Operator Stop / Bypass do NOT teardown — they only change mode."""
        self._last_frame        = None
        self._prev_state        = None
        self._root_indices      = None
        self._bake_positions    = None
        self._bake_velocities   = None
        self._bake_mask         = None
        self._bake_frame_start  = None
        self._bake_frame_end    = None
        self._vbd_solver        = None
        self._vbd_model         = None
        self._vbd_state_in      = None
        self._vbd_state_out     = None
        self._vbd_control       = None
        self._vbd_contacts      = None
        self._vbd_device        = None
        self._vbd_module_warp   = None
        self._collider_shape_id     = None
        self._body_collider_n_verts = 0
        self._initialized       = False
        self._step_error_active = False

    # ----------------------------------------------------------- #
    # Per-frame entries from the handler (mode dispatch in __init__.py)
    # ----------------------------------------------------------- #

    def step(self, scene: bpy.types.Scene) -> bool:
        """SIMULATING-mode per-frame entry.

        Priority:
          1. If current frame is baked → restore from bake (scrub-back).
          2. Else if M == last+1 → run sim step, capture, bake.
          3. Else (jump into unbaked area) → re-baseline only (no sim,
             no bake — this is a teleport, not a physical motion)."""
        if self._step_error_active or not self._initialized:
            return False
        if self._last_frame is None:
            return False

        M = scene.frame_current
        idx = self._frame_to_bake_index(M)

        try:
            # 1. Scrub-restore: already baked → push and exit.
            if idx is not None and self._bake_mask[idx]:
                self._restore_from_bake(M)
                return True

            # 2. Consecutive +1 frame, not yet baked → simulate.
            if M == self._last_frame + 1:
                # _run_one_simulation_step now performs its own atomic
                # commit of (_prev_state, _last_frame) from VBD output —
                # we do NOT call _capture afterwards (that would re-read
                # the just-written Blender data, but the depsgraph
                # evaluation for that write hasn't run yet, and the VBD
                # output is the authoritative truth for this frame).
                ok = self._run_one_simulation_step(scene)
                if ok:
                    self._store_prev_state_to_bake()
                    self._step_count += 1
                return True

            # 3. Jump into unbaked territory → re-baseline.
            self._capture_current_state(scene, derive_velocity_from_prev=False)
            # Intentionally NOT bake-stored: not a sim result.
            return True
        except Exception as exc:
            self._step_error_active = True
            print(f"[hair_sim/passthrough] step error (suppressing): {exc!r}")
            return False

    def playback(self, scene: bpy.types.Scene) -> bool:
        """PLAYBACK-mode per-frame entry. Push baked state to Blender if
        the current frame is baked; do nothing otherwise. Never runs
        simulation."""
        if not self._initialized:
            return False
        M = scene.frame_current
        idx = self._frame_to_bake_index(M)
        if idx is None or not self._bake_mask[idx]:
            # Unbaked frame in PLAYBACK: leave Blender alone.
            return False
        try:
            self._restore_from_bake(M)
            return True
        except Exception as exc:
            print(f"[hair_sim/passthrough] playback error (suppressing): {exc!r}")
            return False

    # ----------------------------------------------------------- #
    # Introspection
    # ----------------------------------------------------------- #

    def status(self) -> dict:
        prev_summary = None
        if self._prev_state is not None:
            pts = self._prev_state.points_world
            vel = self._prev_state.velocities_world
            non_root_mask = (np.arange(pts.shape[0]) % POINTS_PER_STRAND) != 0
            prev_summary = {
                "frame":                 self._prev_state.frame,
                "points_shape":          list(pts.shape),
                "velocities_shape":      list(vel.shape),
                "root0_world_xyz":       [float(x) for x in pts[0]],
                "tip0_world_xyz":        [float(x) for x in pts[POINTS_PER_STRAND - 1]],
                "z_mean_non_root":       float(pts[non_root_mask, 2].mean()),
                "z_mean_root":           float(pts[0::POINTS_PER_STRAND, 2].mean()),
                "vel_max_abs":           float(np.abs(vel).max()),
                "vel_mean_mag_non_root": float(np.linalg.norm(vel[non_root_mask], axis=1).mean()),
                "vel_mean_mag_root":     float(np.linalg.norm(vel[0::POINTS_PER_STRAND], axis=1).mean()),
            }
        bake_summary = None
        if self._bake_mask is not None:
            bake_summary = {
                "frame_range":      [self._bake_frame_start, self._bake_frame_end],
                "n_frames":         int(self._bake_mask.shape[0]),
                "n_baked":          int(self._bake_mask.sum()),
                "buffer_mb_each":   round(
                    self._bake_positions.nbytes / (1024 * 1024), 2
                ) if self._bake_positions is not None else None,
            }
        return {
            "initialized":       self._initialized,
            "step_error_active": self._step_error_active,
            "target_object":     self._target_obj_name,
            "n_total":           self._n_total,
            "last_frame":        self._last_frame,
            "step_count":        self._step_count,
            "prev_state":        prev_summary,
            "bake":              bake_summary,
        }
