"""Hair Simulation — VBD-direction Phase 1: NVIDIA Newton VBD solver
plugged into the v0.0.30 scaffolding (three-mode lifecycle + RAM bake).

**What this module owns**

  * The per-frame state (positions + velocities in world coords) held
    in `_prev_state`. Single source of truth, updated only by
    `_capture_current_state`. See "Why" note below.
  * The full-animation RAM bake: parallel arrays
    `_bake_positions[n_frames, n_total, 3]` and
    `_bake_velocities[n_frames, n_total, 3]` plus a per-frame
    `_bake_mask` boolean. Allocated once at Start (or reused if size
    matches), sized by the scene's animation length.
  * The simulation step: NVIDIA Newton's `SolverVBD`. Hair roots are
    kinematic (mass=0 → fixed); other points are integrated under
    gravity + per-strand spring forces. Sloppy physics constants for
    the explosion test: any non-zero stiffness/damping; user-approved
    that hair may visibly explode as long as Python does not crash.
  * The scrub-restore behaviour: if the user enters a frame that has
    been baked, the baked state is pushed back to Blender — the
    simulator never re-derives it.

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

# VBD sloppy physics values (intentionally arbitrary, per user spec for the
# explosion test: any non-zero value is fine, zeros only allowed where
# physically meaningful — currently only for the kinematic anchor mass).
VBD_SPRING_KE          = 1000.0  # spring stiffness
VBD_SPRING_KD          = 1.0     # spring damping
VBD_FREE_PARTICLE_MASS = 1.0     # mass for non-root particles
VBD_GRAVITY            = -9.81   # m/s² along the up-axis (Z down)
VBD_ITERATIONS         = 8       # VBD solver iterations per step
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
        self._vbd_device        = None
        self._vbd_module_warp   = None  # cached `import warp` handle

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

    def _capture_current_state(
        self,
        scene: bpy.types.Scene,
        derive_velocity_from_prev: bool = False,
    ) -> bool:
        """Snapshot the current frame's full hair state (positions +
        velocities, world coords).

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
        attr = obj.data.attributes.get("position")
        if attr is None or len(attr.data) != self._n_total:
            self._last_frame = None
            self._prev_state = None
            return False

        n = self._n_total

        # 1. Read ORIGINAL (local-space) positions.
        local_flat = np.zeros(n * 3, dtype=np.float32)
        attr.data.foreach_get("vector", local_flat)
        local_pts = local_flat.reshape(n, 3)

        # 2. Convert local → world via matrix_world.
        mw      = np.array(obj.matrix_world, dtype=np.float32)
        local_h = np.column_stack([local_pts, np.ones(n, dtype=np.float32)])
        world_h = local_h @ mw.T
        world_pts = world_h[:, :3].astype(np.float32, copy=True)

        # 3. Derive velocities (or zero them on re-baselining events).
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

        # 4. Atomic commit: both fields updated together at the end.
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

            # Springs along each strand. Rest length is auto-derived by
            # ModelBuilder from the initial particle positions.
            for s in range(n_strands):
                base = s * POINTS_PER_STRAND
                for i in range(POINTS_PER_STRAND - 1):
                    builder.add_spring(
                        base + i, base + i + 1,
                        ke=VBD_SPRING_KE, kd=VBD_SPRING_KD, control=0.0,
                    )

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
            self._vbd_solver      = newton.solvers.SolverVBD(model, iterations=VBD_ITERATIONS)
            self._vbd_state_in    = model.state()
            self._vbd_state_out   = model.state()
            self._vbd_control     = model.control()
            self._vbd_device      = device
            self._vbd_module_warp = wp

            print(
                f"[hair_sim/vbd] initialized on {device}: "
                f"n_particles={n}, n_springs={n_strands * (POINTS_PER_STRAND - 1)}, "
                f"iterations={VBD_ITERATIONS}, ke={VBD_SPRING_KE}, kd={VBD_SPRING_KD}, "
                f"gravity={VBD_GRAVITY}"
            )
            return True
        except Exception as exc:
            print(f"[hair_sim/vbd] build failed: {exc!r}")
            # Roll back partial state.
            self._vbd_model = self._vbd_solver = None
            self._vbd_state_in = self._vbd_state_out = None
            self._vbd_control = None
            self._vbd_device = None
            return False

    def _run_one_simulation_step(self, scene: bpy.types.Scene) -> None:
        """Evolve state by exactly one frame using Newton's VBD solver.

        Explosion-test setup (per user spec): hair root particles are
        kinematic (mass=0, fixed at the position the rig + scrub-restore
        provides), all other particles are subject to gravity and spring
        forces with sloppy non-zero stiffness/damping values. No
        collision is added. Hair is allowed to fly apart; the bar for
        success is that Python (and Blender) does not crash."""
        if self._prev_state is None:
            return
        obj = bpy.data.objects.get(self._target_obj_name)
        if obj is None:
            return
        if not self._ensure_vbd_initialized():
            return

        wp     = self._vbd_module_warp
        n      = self._n_total
        device = self._vbd_device

        try:
            # 1. Copy `_prev_state` into the solver's input state.
            #    wp.from_numpy on a (n, 3) float32 array with dtype=wp.vec3
            #    yields a wp.array(shape=(n,), dtype=wp.vec3).
            pts_np = np.ascontiguousarray(self._prev_state.points_world,     dtype=np.float32)
            vel_np = np.ascontiguousarray(self._prev_state.velocities_world, dtype=np.float32)
            tmp_q  = wp.from_numpy(pts_np, dtype=wp.vec3, device=device)
            tmp_qd = wp.from_numpy(vel_np, dtype=wp.vec3, device=device)
            wp.copy(self._vbd_state_in.particle_q,  tmp_q)
            wp.copy(self._vbd_state_in.particle_qd, tmp_qd)

            # 2. Step.
            dt = float(scene.render.fps_base) / float(scene.render.fps)
            self._vbd_solver.step(
                self._vbd_state_in,
                self._vbd_state_out,
                self._vbd_control,
                None,   # contacts: none for this test
                dt,
            )

            # 3. Read positions out (GPU → CPU copy).
            world_pts = self._vbd_state_out.particle_q.numpy()
            world_pts = np.ascontiguousarray(world_pts, dtype=np.float32).reshape(n, 3)
        except Exception as exc:
            print(f"[hair_sim/vbd] step failed (suppressing): {exc!r}")
            return

        # 4. Convert world → local and write to ORIGINAL.
        mw_inv  = np.array(obj.matrix_world.inverted(), dtype=np.float32)
        world_h = np.column_stack([world_pts, np.ones(n, dtype=np.float32)])
        local_h = world_h @ mw_inv.T
        local_pts = local_h[:, :3].astype(np.float32, copy=True)

        attr = obj.data.attributes.get("position")
        if attr is None or len(attr.data) != n:
            return
        # local_pts is C-contiguous (astype(copy=True) above), so ravel()
        # returns a view; foreach_set accepts numpy arrays directly.
        attr.data.foreach_set("vector", local_pts.ravel())
        obj.data.update_tag()

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

        # Invalidate any cached VBD state — the topology snapshot inside
        # the Newton model assumes the rest positions captured at this
        # Start. First sim step will rebuild it from the new _prev_state.
        self._vbd_solver    = None
        self._vbd_model     = None
        self._vbd_state_in  = None
        self._vbd_state_out = None
        self._vbd_control   = None

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
        self._vbd_device        = None
        self._vbd_module_warp   = None
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
                self._run_one_simulation_step(scene)
                self._capture_current_state(scene, derive_velocity_from_prev=True)
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
