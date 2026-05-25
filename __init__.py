from __future__ import annotations

import bpy
from bpy.app.handlers import persistent
from bpy.props import EnumProperty
from bpy.types import Operator, WindowManager

from . import ui


# Mode values for WindowManager.hair_sim_mode.
MODE_BYPASS     = "BYPASS"
MODE_SIMULATING = "SIMULATING"
MODE_PLAYBACK   = "PLAYBACK"


class SolverInterface:
    """Thin facade between operators / handler and the WorldPassthrough
    state owner. Holds the single live passthrough instance for the
    current Blender session."""

    def __init__(self) -> None:
        self._passthrough = None

    def start(self, scene: bpy.types.Scene) -> bool:
        """Initialize (or re-initialize) the passthrough at the current
        frame.

        **Instance reuse** (load-bearing for bake-allocation cost):
        the existing WorldPassthrough instance is preserved across
        Start calls. WorldPassthrough.start() then runs against the
        live instance, and `_allocate_bake` reuses the existing bake
        buffer if its shape matches the scene's animation length —
        avoiding a ~1 GB re-allocation on every Stop→Start cycle.
        A fresh instance is created only on first-ever Start, or
        after teardown (extension unregister)."""
        try:
            from . import _world_passthrough
        except Exception as exc:
            print(f"[hair_sim] start failed: import _world_passthrough: {exc!r}")
            return False

        obj = bpy.data.objects.get(_world_passthrough.TARGET_NAME)
        if obj is None or obj.type != "CURVES":
            print(f"[hair_sim] start failed: target "
                  f"'{_world_passthrough.TARGET_NAME}' missing or not Curves")
            return False

        # Reuse the existing passthrough instance if present so that
        # the bake buffer survives Stop → Start cycles. Only create a
        # new instance on first Start (or after teardown).
        if self._passthrough is None:
            self._passthrough = _world_passthrough.WorldPassthrough()

        if not self._passthrough.start(obj, scene):
            return False
        return True

    def teardown(self) -> None:
        """Full state cleanup. Only called by `unregister()`. Stop and
        Bypass operators do NOT teardown — they only change mode."""
        if self._passthrough is not None:
            try:
                self._passthrough.teardown()
            except Exception:
                pass
        self._passthrough = None

    def step(self, scene: bpy.types.Scene, depsgraph: bpy.types.Depsgraph) -> None:
        """SIMULATING-mode per-frame entry: scrub-restore from bake, or
        run one sim step on +1, or re-baseline on jump."""
        if self._passthrough is None:
            return
        self._passthrough.step(scene)

    def playback(self, scene: bpy.types.Scene) -> None:
        """PLAYBACK-mode per-frame entry: push baked state to Blender if
        the current frame is baked; otherwise leave Blender alone."""
        if self._passthrough is None:
            return
        self._passthrough.playback(scene)


_solver = SolverInterface()


@persistent
def _on_frame_change_post(scene: bpy.types.Scene, depsgraph: bpy.types.Depsgraph) -> None:
    """Per-frame dispatcher. Branches by `WindowManager.hair_sim_mode`:
      BYPASS      → return immediately (Blender handles everything).
      SIMULATING  → call solver.step().
      PLAYBACK    → call solver.playback()."""
    wm = bpy.context.window_manager
    if wm is None:
        return
    mode = getattr(wm, "hair_sim_mode", MODE_BYPASS)
    if mode == MODE_BYPASS:
        return
    if mode == MODE_SIMULATING:
        _solver.step(scene, depsgraph)
    elif mode == MODE_PLAYBACK:
        _solver.playback(scene)


def _install_handler() -> None:
    handlers = bpy.app.handlers.frame_change_post
    if _on_frame_change_post not in handlers:
        handlers.append(_on_frame_change_post)


def _uninstall_handler() -> None:
    handlers = bpy.app.handlers.frame_change_post
    if _on_frame_change_post in handlers:
        handlers.remove(_on_frame_change_post)


class HAIR_SIM_OT_start(Operator):
    bl_idname = "hair_sim.start"
    bl_label = "Start"
    bl_description = (
        "Enter SIMULATING mode. Initialize the simulator at the current "
        "frame and allocate the RAM bake. Consecutive +1 frame advances "
        "run simulation; scrub-back to a baked frame restores from bake"
    )

    def execute(self, context: bpy.types.Context) -> set[str]:
        wm = context.window_manager

        from . import _native_loader
        native = _native_loader.get_native()
        if native is None:
            self.report({"WARNING"}, "Native module not available — continuing without it")
        else:
            try:
                value = native.add(2, 3)
                phase = native.phase
                self.report({"INFO"}, f"Native ok: phase={phase!r}  add(2,3)={value}")
            except Exception as exc:
                self.report({"WARNING"}, f"Native call failed: {exc} — continuing anyway")

        if not _solver.start(context.scene):
            self.report({"ERROR"}, "Hair sim start failed (see system console)")
            return {"CANCELLED"}
        wm.hair_sim_mode = MODE_SIMULATING
        self.report({"INFO"}, "Hair sim → SIMULATING")
        return {"FINISHED"}


class HAIR_SIM_OT_stop(Operator):
    bl_idname = "hair_sim.stop"
    bl_label = "Stop"
    bl_description = (
        "Enter PLAYBACK mode. No further simulation runs; on each frame "
        "change the baked state for that frame is pushed back to "
        "Blender. State and bake are preserved (Start to resume)"
    )

    def execute(self, context: bpy.types.Context) -> set[str]:
        wm = context.window_manager
        wm.hair_sim_mode = MODE_PLAYBACK
        # Immediately push current frame's bake (if any) so the viewport
        # reflects the playback state without waiting for a frame change.
        _solver.playback(context.scene)
        self.report({"INFO"}, "Hair sim → PLAYBACK")
        return {"FINISHED"}


class HAIR_SIM_OT_bypass(Operator):
    bl_idname = "hair_sim.bypass"
    bl_label = "Bypass"
    bl_description = (
        "Enter BYPASS mode. The extension stops intercepting frame "
        "changes entirely — Blender handles everything natively. State "
        "and bake are preserved (Start / Stop to resume)"
    )

    def execute(self, context: bpy.types.Context) -> set[str]:
        wm = context.window_manager
        wm.hair_sim_mode = MODE_BYPASS
        self.report({"INFO"}, "Hair sim → BYPASS")
        return {"FINISHED"}


_classes = (
    HAIR_SIM_OT_start,
    HAIR_SIM_OT_stop,
    HAIR_SIM_OT_bypass,
)


def register() -> None:
    for cls in _classes:
        bpy.utils.register_class(cls)
    WindowManager.hair_sim_mode = EnumProperty(
        name="Hair Sim Mode",
        items=[
            (MODE_BYPASS,     "Bypass",     "Extension does nothing — Blender handles all"),
            (MODE_SIMULATING, "Simulating", "Run sim on consecutive frames; restore from bake on scrub"),
            (MODE_PLAYBACK,   "Playback",   "Push baked state on every frame; no simulation"),
        ],
        default=MODE_BYPASS,
        options={"SKIP_SAVE"},
    )
    ui.register()
    _install_handler()


def unregister() -> None:
    try:
        _solver.teardown()
    except Exception:
        pass
    _uninstall_handler()
    ui.unregister()
    del WindowManager.hair_sim_mode
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
