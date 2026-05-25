from __future__ import annotations

import array

import bpy
from bpy.app.handlers import persistent
from bpy.props import BoolProperty
from bpy.types import Operator, WindowManager

from . import ui


class SolverInterface:

    _TARGET_OBJECT_NAME = "カーブ.001"

    def __init__(self) -> None:
        self._passthrough = None

    def start(self, scene: bpy.types.Scene) -> bool:
        self._passthrough = None

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

        pt = _world_passthrough.WorldPassthrough()
        if not pt.start(obj, scene):
            return False

        self._passthrough = pt
        return True

    def stop(self) -> None:
        if self._passthrough is not None:
            self._passthrough.stop()

    def reset(self, scene: bpy.types.Scene) -> None:
        if self._passthrough is None:
            return
        self._passthrough.reset(scene)

    def step(self, scene: bpy.types.Scene, depsgraph: bpy.types.Depsgraph) -> None:
        if self._passthrough is None:
            return
        self._passthrough.step(scene)


_solver = SolverInterface()


@persistent
def _on_frame_change_post(scene: bpy.types.Scene, depsgraph: bpy.types.Depsgraph) -> None:
    wm = bpy.context.window_manager
    if wm is None or not getattr(wm, "hair_sim_running", False):
        return
    _solver.step(scene, depsgraph)


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
    bl_description = "Begin advancing the hair simulation on frame change"

    def execute(self, context: bpy.types.Context) -> set[str]:
        wm = context.window_manager
        if wm.hair_sim_running:
            return {"FINISHED"}

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
        wm.hair_sim_running = True
        self.report({"INFO"}, "Hair sim running")
        return {"FINISHED"}


class HAIR_SIM_OT_stop(Operator):
    bl_idname = "hair_sim.stop"
    bl_label = "Stop"
    bl_description = "Stop advancing the hair simulation on frame change"

    def execute(self, context: bpy.types.Context) -> set[str]:
        wm = context.window_manager
        if not wm.hair_sim_running:
            return {"FINISHED"}
        _solver.stop()
        wm.hair_sim_running = False
        self.report({"INFO"}, "Hair sim stopped")
        return {"FINISHED"}


class HAIR_SIM_OT_reset(Operator):
    bl_idname = "hair_sim.reset"
    bl_label = "Reset"
    bl_description = "Request the solver to reinitialize its internal state"

    def execute(self, context: bpy.types.Context) -> set[str]:
        _solver.reset(context.scene)
        return {"FINISHED"}


_classes = (
    HAIR_SIM_OT_start,
    HAIR_SIM_OT_stop,
    HAIR_SIM_OT_reset,
)


def register() -> None:
    for cls in _classes:
        bpy.utils.register_class(cls)
    WindowManager.hair_sim_running = BoolProperty(
        name="Hair Sim Running",
        default=False,
        options={"SKIP_SAVE"},
    )
    ui.register()
    _install_handler()


def unregister() -> None:
    try:
        _solver.stop()
    except Exception:
        pass
    _uninstall_handler()
    ui.unregister()
    del WindowManager.hair_sim_running
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
