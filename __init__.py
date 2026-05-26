from __future__ import annotations

import json
import os

import bpy
from bpy.app.handlers import persistent
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty
from bpy.types import Operator, WindowManager

from . import ui


MODE_BYPASS     = "BYPASS"
MODE_SIMULATING = "SIMULATING"
MODE_PLAYBACK   = "PLAYBACK"


# ---------------------------------------------------------------------------
# Simulation parameter panel.
# Defaults from hair_sim_defaults.json. Values snapshotted into
# _world_passthrough module constants at each Start.
# ---------------------------------------------------------------------------

_PARAM_FLOAT_KEYS = (
    "SPRING_KE",
    "DAMPING",
    "PARTICLE_MASS",
    "GRAVITY",
    "ROOT_BENDING_KE",
    "BENDING_KE",
)
_PARAM_INT_KEYS = (
    "ITERATIONS",
    "SUBSTEPS",
)
_PARAM_BOOL_KEYS = (
    "BENDING_ENABLED",
    "BODY_COLLISION_ENABLED",
)
_PARAM_STR_KEYS = (
    "BODY_COLLISION_TARGET",
)

def _wm_attr(key: str) -> str:
    return "hair_sim_param_" + key.lower()


def _load_defaults_json() -> dict:
    path = os.path.join(os.path.dirname(__file__), "hair_sim_defaults.json")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    required = _PARAM_FLOAT_KEYS + _PARAM_INT_KEYS + _PARAM_BOOL_KEYS + _PARAM_STR_KEYS
    missing  = [k for k in required if k not in data]
    if missing:
        raise RuntimeError(f"hair_sim_defaults.json missing keys: {missing}")
    return data


def _register_param_props(defaults: dict) -> None:
    for key in _PARAM_FLOAT_KEYS:
        setattr(WindowManager, _wm_attr(key), FloatProperty(
            name=key, default=float(defaults[key]), options={"SKIP_SAVE"},
        ))
    for key in _PARAM_INT_KEYS:
        setattr(WindowManager, _wm_attr(key), IntProperty(
            name=key, default=int(defaults[key]), options={"SKIP_SAVE"},
        ))
    for key in _PARAM_BOOL_KEYS:
        setattr(WindowManager, _wm_attr(key), BoolProperty(
            name=key, default=bool(defaults[key]), options={"SKIP_SAVE"},
        ))
    for key in _PARAM_STR_KEYS:
        setattr(WindowManager, _wm_attr(key), StringProperty(
            name=key, default=str(defaults[key]), options={"SKIP_SAVE"},
        ))


def _unregister_param_props() -> None:
    for key in _PARAM_FLOAT_KEYS + _PARAM_INT_KEYS + _PARAM_BOOL_KEYS + _PARAM_STR_KEYS:
        try:
            delattr(WindowManager, _wm_attr(key))
        except Exception:
            pass


def _snapshot_params(wm: bpy.types.WindowManager) -> None:
    """Push current WM property values into the sim engine module constants."""
    from . import _world_passthrough as _wp
    for key in _PARAM_FLOAT_KEYS + _PARAM_INT_KEYS + _PARAM_BOOL_KEYS + _PARAM_STR_KEYS:
        setattr(_wp, key, getattr(wm, _wm_attr(key)))
    vals = ", ".join(f"{k}={getattr(_wp, k)}" for k in _PARAM_FLOAT_KEYS + _PARAM_INT_KEYS)
    print(f"[hair_sim] params: {vals}")


# ---------------------------------------------------------------------------
# Solver interface
# ---------------------------------------------------------------------------

class SolverInterface:
    """Thin facade between operators / handler and WorldPassthrough."""

    def __init__(self) -> None:
        self._passthrough = None

    def start(self, scene: bpy.types.Scene) -> bool:
        try:
            from . import _world_passthrough
        except Exception as exc:
            print(f"[hair_sim] import failed: {exc!r}")
            return False

        obj = bpy.data.objects.get(_world_passthrough.TARGET_NAME)
        if obj is None or obj.type != "CURVES":
            print(f"[hair_sim] start failed: '{_world_passthrough.TARGET_NAME}' missing or not Curves")
            return False

        if self._passthrough is None:
            self._passthrough = _world_passthrough.WorldPassthrough()

        return self._passthrough.start(obj, scene)

    def teardown(self) -> None:
        if self._passthrough is not None:
            try:
                self._passthrough.teardown()
            except Exception:
                pass
        self._passthrough = None

    def step(self, scene: bpy.types.Scene, depsgraph: bpy.types.Depsgraph) -> None:
        if self._passthrough is None:
            return
        self._passthrough.step(scene)

    def playback(self, scene: bpy.types.Scene) -> None:
        if self._passthrough is None:
            return
        self._passthrough.playback(scene)


_solver = SolverInterface()


# ---------------------------------------------------------------------------
# Frame handler
# ---------------------------------------------------------------------------

@persistent
def _on_frame_change_post(scene: bpy.types.Scene, depsgraph: bpy.types.Depsgraph) -> None:
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
    if _on_frame_change_post not in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.append(_on_frame_change_post)


def _uninstall_handler() -> None:
    if _on_frame_change_post in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.remove(_on_frame_change_post)


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

class HAIR_SIM_OT_start(Operator):
    bl_idname   = "hair_sim.start"
    bl_label    = "Start"
    bl_description = "Enter SIMULATING mode"

    def execute(self, context: bpy.types.Context) -> set[str]:
        wm = context.window_manager
        _snapshot_params(wm)
        if not _solver.start(context.scene):
            self.report({"ERROR"}, "Hair sim start failed (see system console)")
            return {"CANCELLED"}
        wm.hair_sim_mode = MODE_SIMULATING
        self.report({"INFO"}, "Hair sim → SIMULATING")
        return {"FINISHED"}


class HAIR_SIM_OT_stop(Operator):
    bl_idname   = "hair_sim.stop"
    bl_label    = "Stop"
    bl_description = "Enter PLAYBACK mode"

    def execute(self, context: bpy.types.Context) -> set[str]:
        wm = context.window_manager
        wm.hair_sim_mode = MODE_PLAYBACK
        _solver.playback(context.scene)
        self.report({"INFO"}, "Hair sim → PLAYBACK")
        return {"FINISHED"}


class HAIR_SIM_OT_bypass(Operator):
    bl_idname   = "hair_sim.bypass"
    bl_label    = "Bypass"
    bl_description = "Enter BYPASS mode — extension does nothing"

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


# ---------------------------------------------------------------------------
# Register / unregister
# ---------------------------------------------------------------------------

def register() -> None:
    _defaults = _load_defaults_json()
    for cls in _classes:
        bpy.utils.register_class(cls)
    WindowManager.hair_sim_mode = EnumProperty(
        name="Hair Sim Mode",
        items=[
            (MODE_BYPASS,     "Bypass",     "Extension inactive"),
            (MODE_SIMULATING, "Simulating", "Run sim on +1 frames; restore from bake on scrub"),
            (MODE_PLAYBACK,   "Playback",   "Push baked state; no simulation"),
        ],
        default=MODE_BYPASS,
        options={"SKIP_SAVE"},
    )
    _register_param_props(_defaults)
    ui.register()
    _install_handler()


def unregister() -> None:
    try:
        _solver.teardown()
    except Exception:
        pass
    _uninstall_handler()
    ui.unregister()
    _unregister_param_props()
    del WindowManager.hair_sim_mode
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
