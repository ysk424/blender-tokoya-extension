"""Hair Simulation — Phase 1 skeleton.

Container only: no physics, no collision, no hair deformation.
Provides Start / Stop / Reset operators, a frame_change_post handler,
and a placeholder SolverInterface that defines the future C++ boundary.
"""
from __future__ import annotations

import bpy
from bpy.app.handlers import persistent
from bpy.props import BoolProperty
from bpy.types import Operator, WindowManager

from . import ui


# --------------------------------------------------------------------------- #
# Solver boundary
# --------------------------------------------------------------------------- #

class SolverInterface:
    """Phase 1 placeholder for the future native (C++/PhysX) solver.

    The four methods below are the only contact surface between the
    Blender layer and whatever runs the simulation. Curves / points
    are intentionally not part of the signature yet — how geometry is
    handed to the solver is a separate decision."""

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def reset(self) -> None:
        pass

    def step(self, scene: bpy.types.Scene, depsgraph: bpy.types.Depsgraph) -> None:
        pass


_solver = SolverInterface()


# --------------------------------------------------------------------------- #
# Frame handler
# --------------------------------------------------------------------------- #

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


# --------------------------------------------------------------------------- #
# Operators
# --------------------------------------------------------------------------- #

class HAIR_SIM_OT_start(Operator):
    bl_idname = "hair_sim.start"
    bl_label = "Start"
    bl_description = "Begin advancing the hair simulation on frame change"

    def execute(self, context: bpy.types.Context) -> set[str]:
        wm = context.window_manager
        if wm.hair_sim_running:
            return {"FINISHED"}
        _solver.start()
        wm.hair_sim_running = True
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
        return {"FINISHED"}


class HAIR_SIM_OT_reset(Operator):
    bl_idname = "hair_sim.reset"
    bl_label = "Reset"
    bl_description = "Request the solver to reinitialize its internal state"

    def execute(self, context: bpy.types.Context) -> set[str]:
        _solver.reset()
        return {"FINISHED"}


# --------------------------------------------------------------------------- #
# Register
# --------------------------------------------------------------------------- #

_classes = (
    HAIR_SIM_OT_start,
    HAIR_SIM_OT_stop,
    HAIR_SIM_OT_reset,
)


def register() -> None:
    for cls in _classes:
        bpy.utils.register_class(cls)
    # SKIP_SAVE keeps the running flag out of the .blend file.
    WindowManager.hair_sim_running = BoolProperty(
        name="Hair Sim Running",
        default=False,
        options={"SKIP_SAVE"},
    )
    ui.register()
    _install_handler()


def unregister() -> None:
    _uninstall_handler()
    ui.unregister()
    del WindowManager.hair_sim_running
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
