"""Hair Simulation — VBD-direction Phase 0: state-evolution scaffolding +
write-persistence verification test.

This module currently serves TWO purposes:

  (A) Architecture scaffolding for the future VBD solver. The structure
      (_prev_state held in world coords, _last_frame synced atomically,
      delta-1 frame dispatch) is the shape any future solver plugs into.

  (B) Verification of a foundational assumption: when we write to
      `obj.data.attributes["position"]`, does the write persist through
      Blender's storage AND the active Geometry Nodes modifier
      ("サーフェス変形")?

      To answer (B), `_run_one_simulation_step` is wired with a
      deterministic fake deformation: every step, non-root points
      receive `world Z += 0.02`. Over N frames the accumulation is
      observable both in `_prev_state.points_world` and visually.

      If accumulation occurs → writes persist → the (iii) design
                                (modifier-output-as-anchor + writeback
                                to original) is structurally viable.
      If not                  → strategy needs to be re-thought from
                                scratch.

**Why _last_frame and _prev_state are always updated together**

Simulation = state evolution. To compute the next state we need the
previous state. If _last_frame and _prev_state ever fell out of sync,
the next +1-frame step would solve from stale data, which silently
produces wrong physics. They are updated atomically in
`_capture_current_state`.

**Flow**

  on Start (frame N):
      capture current state  →  _prev_state, _last_frame = N
      (no simulation runs on Start)

  on every frame_change_post (current frame = M):
      if M == _last_frame + 1:
          run one simulation step (fake deformation today)
          capture current state  →  _prev_state, _last_frame = M
      else (jump / backward / same):
          skip simulation
          capture current state  →  _prev_state, _last_frame = M
              ★ still update — never carry stale state

  on Stop:
      clear _prev_state, _last_frame = None

  on Reset:
      capture current state — re-base on current frame

**Modifier policy (current)**

The target Curves object carries a Geometry Nodes modifier
"サーフェス変形". This module does NOT touch it. If verification
test (B) reveals the modifier overwrites our writeback, the choice
between (mute modifier) vs (alternative path) is revisited then.

**Phase 1 invariants preserved**

Exactly one persistent `frame_change_post` handler, gated by
`WindowManager.hair_sim_running`. step() is invoked at most once per
frame change.
"""
from __future__ import annotations

from dataclasses import dataclass

import bpy
import numpy as np


TARGET_NAME        = "カーブ.001"
POINTS_PER_STRAND  = 8       # Uniform per Phase 3A scene investigation.
TEST_Z_PER_STEP    = 0.02    # World-Z increment applied to non-root points
                             # each simulation step. (B) verification only.


@dataclass
class HairFrameState:
    """One frame's hair snapshot. All world coordinates. Sufficient to
    reproduce hair shape and to drive the next-frame state transition.

    Today only positions are held. Velocities, per-strand attributes,
    and other dynamics-related fields will be added when the real
    solver lands; the dataclass shape is intended to grow."""
    points_world: np.ndarray   # (n_total, 3) float32
    frame:        int


class WorldPassthrough:
    """Stateful manager of the state-evolution scaffolding. One instance
    is created on Start, lives for the running session, and is torn
    down on Stop / Reset → Start cycles."""

    def __init__(self) -> None:
        self._initialized       = False
        self._step_error_active = False
        self._target_obj_name   = None

        # Curves shape constants captured at Start.
        self._n_total           = 0

        # State evolution bookkeeping — ALWAYS updated together.
        self._last_frame        = None  # type: int | None
        self._prev_state        = None  # type: HairFrameState | None

        # Per-call telemetry.
        self._step_count        = 0

    # ---- placeholder hooks — to be filled in later phases ----

    def _capture_current_state(self, scene: bpy.types.Scene) -> None:
        """Snapshot the current frame's full hair state (all point
        world positions) so the next simulation step has a 'previous
        state' to evolve from. `_last_frame` and `_prev_state` are
        updated atomically."""
        frame = scene.frame_current
        self._last_frame = frame

        obj = bpy.data.objects.get(self._target_obj_name)
        if obj is None:
            self._prev_state = None
            return
        attr = obj.data.attributes.get("position")
        if attr is None or len(attr.data) != self._n_total:
            self._prev_state = None
            return

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

        self._prev_state = HairFrameState(
            points_world=world_pts,
            frame=frame,
        )

    def _run_one_simulation_step(self, scene: bpy.types.Scene) -> None:
        """Evolve state by exactly one frame.

        **Today (verification test (B))**: deterministic fake
        deformation. Non-root points receive `world Z += TEST_Z_PER_STEP`
        each call. Roots are not touched. Over N invocations the
        accumulation is observable both in `_prev_state.points_world`
        and in the viewport.

        The real VBD solver lands here later, replacing the fake
        deformation while preserving the input/output contract:
        (_prev_state + Blender's current boundary) → new state →
        write back to ORIGINAL."""
        if self._prev_state is None:
            return
        obj = bpy.data.objects.get(self._target_obj_name)
        if obj is None:
            return

        n = self._n_total

        # 1. Start from the previously held world-coord state.
        world_pts = self._prev_state.points_world.copy()

        # 2. Apply fake deformation in world space.
        #    Non-root points (index within strand != 0) shift up in Z.
        is_non_root = (np.arange(n) % POINTS_PER_STRAND) != 0
        world_pts[is_non_root, 2] += TEST_Z_PER_STEP

        # 3. Convert world → local via matrix_world.inverted().
        mw_inv  = np.array(obj.matrix_world.inverted(), dtype=np.float32)
        world_h = np.column_stack([world_pts, np.ones(n, dtype=np.float32)])
        local_h = world_h @ mw_inv.T
        local_pts = local_h[:, :3].astype(np.float32, copy=True)

        # 4. Write back to ORIGINAL and tag depsgraph.
        attr = obj.data.attributes.get("position")
        if attr is None or len(attr.data) != n:
            return
        attr.data.foreach_set("vector", local_pts.flatten().tolist())
        obj.data.update_tag()

    # ---- lifecycle ----

    def start(self, obj, scene: bpy.types.Scene) -> bool:
        """Acquire the target Curves and capture the current frame as
        the simulation's initial state. Returns False on any geometry
        sanity failure; caller must keep `hair_sim_running=False`."""
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

        self._target_obj_name = obj.name
        self._n_total         = n_total
        self._step_count      = 0
        self._initialized     = True

        # Capture initial state at the Start frame.
        self._capture_current_state(scene)

        print(
            "[hair_sim/passthrough] start ok: "
            f"target={obj.name!r}, n_total={n_total}, "
            f"start_frame={self._last_frame}, "
            f"prev_state_set={self._prev_state is not None}"
        )
        return True

    def stop(self) -> None:
        """Clear simulation state. Modifier is NOT touched (current policy)."""
        self._last_frame = None
        self._prev_state = None

    def reset(self, scene: bpy.types.Scene) -> bool:
        """Re-base the simulation on the current frame, as if Start
        were pressed again at this frame. Required before resuming
        simulation from an unrelated frame position."""
        if not self._initialized:
            return False
        self._step_error_active = False
        self._step_count        = 0
        self._capture_current_state(scene)
        return True

    # ---- per-frame entry from handler ----

    def step(self, scene: bpy.types.Scene) -> bool:
        """Dispatch by frame delta:
          M == last+1 → run one simulation step + capture
          else        → skip simulation + capture (still re-base)
        Both branches keep `_last_frame` and `_prev_state` in sync."""
        if self._step_error_active or not self._initialized:
            return False
        if self._last_frame is None:
            # Defensive: Start should have set this.
            return False

        current = scene.frame_current
        try:
            if current == self._last_frame + 1:
                self._run_one_simulation_step(scene)
                self._capture_current_state(scene)
                self._step_count += 1
            else:
                # Frame jumped / went backward / stayed same → cannot
                # simulate. Re-capture so stale state is never held.
                self._capture_current_state(scene)
        except Exception as exc:
            self._step_error_active = True
            print(f"[hair_sim/passthrough] step error (suppressing): {exc!r}")
            return False
        return True

    # ---- introspection ----

    def status(self) -> dict:
        prev_summary = None
        if self._prev_state is not None:
            pts = self._prev_state.points_world
            # Sample point 0 (a root) and point 7 (a tip in strand 0).
            prev_summary = {
                "frame":            self._prev_state.frame,
                "shape":            list(pts.shape),
                "root0_world_xyz":  [float(x) for x in pts[0]],
                "tip0_world_xyz":   [float(x) for x in pts[POINTS_PER_STRAND - 1]],
                "z_mean_non_root":  float(pts[(np.arange(pts.shape[0]) % POINTS_PER_STRAND) != 0, 2].mean()),
                "z_mean_root":      float(pts[0::POINTS_PER_STRAND, 2].mean()),
            }
        return {
            "initialized":       self._initialized,
            "step_error_active": self._step_error_active,
            "target_object":     self._target_obj_name,
            "n_total":           self._n_total,
            "last_frame":        self._last_frame,
            "step_count":        self._step_count,
            "prev_state":        prev_summary,
        }
