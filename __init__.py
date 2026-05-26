from __future__ import annotations

import json
import math
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
# Parameter definitions
#
# All values in hair_sim_defaults.json and _world_passthrough.py are
# PHYSICS values. WM properties store USER-FRIENDLY display values:
#
#   SPRING_KE / ROOT_BENDING_KE / BENDING_KE : log10(physics)
#       display 4.0 → physics 10,000
#   DAMPING : physics × 100
#       display 1.0  → physics 0.01
#   PARTICLE_MASS : physics × 1000
#       display 1000 → physics 1.0
#
# Conversions are applied in _snapshot_params() at each Start.
# ---------------------------------------------------------------------------

def _physics_to_display(key: str, phys) -> float:
    """Convert physics value (from JSON) to UI display value."""
    if key in ("SPRING_KE", "ROOT_BENDING_KE", "BENDING_KE"):
        return math.log10(max(float(phys), 1e-10))
    if key == "DAMPING":
        return float(phys) * 100.0
    if key == "PARTICLE_MASS":
        return float(phys) * 1000.0
    return float(phys)


def _display_to_physics(key: str, disp) -> float:
    """Convert UI display value back to physics value."""
    if key in ("SPRING_KE", "ROOT_BENDING_KE", "BENDING_KE"):
        return 10.0 ** float(disp)
    if key == "DAMPING":
        return float(disp) / 100.0
    if key == "PARTICLE_MASS":
        return float(disp) / 1000.0
    return float(disp)


# Float property specs: (name, description, min, max, soft_min, soft_max, step, precision)
_FLOAT_SPECS: dict[str, dict] = {
    "SPRING_KE": dict(
        name        = "Stiffness 10^N",
        description = "log10 segment spring stiffness. 4.0 → 10,000",
        min=1.0, max=9.0, soft_min=2.0, soft_max=7.0, step=10, precision=2,
    ),
    "DAMPING": dict(
        name        = "Damping /100",
        description = "Velocity damping per substep. Display / 100 = actual. 1.0 → 0.01",
        min=0.0, max=50.0, soft_min=0.0, soft_max=20.0, step=10, precision=1,
    ),
    "PARTICLE_MASS": dict(
        name        = "Mass /1000",
        description = "Free particle mass. Display / 1000 = actual kg. 1000 → 1.0 kg",
        min=1.0, max=10000.0, soft_min=10.0, soft_max=5000.0, step=100, precision=1,
    ),
    "GRAVITY": dict(
        name        = "Gravity m/s2",
        description = "Gravitational acceleration along -Z axis",
        min=-20.0, max=0.0, soft_min=-15.0, soft_max=0.0, step=10, precision=2,
    ),
    "ROOT_BENDING_KE": dict(
        name        = "Root Stiff 10^N",
        description = "log10 root bending stiffness (first 2 joints). 3.3 → 2,000",
        min=0.0, max=7.0, soft_min=1.0, soft_max=5.0, step=10, precision=2,
    ),
    "BENDING_KE": dict(
        name        = "Strand Stiff 10^N",
        description = "log10 strand bending stiffness (remaining joints). 1.0 → 10",
        min=0.0, max=6.0, soft_min=0.0, soft_max=4.0, step=10, precision=2,
    ),
}

_PARAM_FLOAT_KEYS = (
    "SPRING_KE", "DAMPING", "PARTICLE_MASS", "GRAVITY",
    "ROOT_BENDING_KE", "BENDING_KE",
)
_PARAM_INT_KEYS  = ("ITERATIONS", "SUBSTEPS")
_PARAM_BOOL_KEYS = ("BENDING_ENABLED", "BODY_COLLISION_ENABLED")
_PARAM_STR_KEYS  = ("BODY_COLLISION_TARGET",)

_ALL_KEYS = _PARAM_FLOAT_KEYS + _PARAM_INT_KEYS + _PARAM_BOOL_KEYS + _PARAM_STR_KEYS


def _wm_attr(key: str) -> str:
    return "hair_sim_param_" + key.lower()


def _load_defaults_json() -> dict:
    path = os.path.join(os.path.dirname(__file__), "hair_sim_defaults.json")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    missing = [k for k in _ALL_KEYS if k not in data]
    if missing:
        raise RuntimeError(f"hair_sim_defaults.json missing keys: {missing}")
    return data


def _register_param_props(defaults: dict) -> None:
    for key in _PARAM_FLOAT_KEYS:
        spec = _FLOAT_SPECS.get(key, {})
        disp_default = _physics_to_display(key, defaults[key])
        setattr(WindowManager, _wm_attr(key), FloatProperty(
            name        = spec.get("name", key),
            description = spec.get("description", ""),
            default     = disp_default,
            min         = spec.get("min", -1e9),
            max         = spec.get("max",  1e9),
            soft_min    = spec.get("soft_min", spec.get("min", -1e9)),
            soft_max    = spec.get("soft_max", spec.get("max",  1e9)),
            step        = spec.get("step", 3),
            precision   = spec.get("precision", 3),
            options     = {"SKIP_SAVE"},
        ))
    _int_labels = {"ITERATIONS": "Iterations", "SUBSTEPS": "Substeps"}
    for key in _PARAM_INT_KEYS:
        setattr(WindowManager, _wm_attr(key), IntProperty(
            name    = _int_labels.get(key, key),
            default = int(defaults[key]),
            min     = 1,
            max     = 64,
            options = {"SKIP_SAVE"},
        ))
    for key in _PARAM_BOOL_KEYS:
        setattr(WindowManager, _wm_attr(key), BoolProperty(
            name    = key,
            default = bool(defaults[key]),
            options = {"SKIP_SAVE"},
        ))
    for key in _PARAM_STR_KEYS:
        setattr(WindowManager, _wm_attr(key), StringProperty(
            name    = key,
            default = str(defaults[key]),
            options = {"SKIP_SAVE"},
        ))


def _unregister_param_props() -> None:
    for key in _ALL_KEYS:
        try:
            delattr(WindowManager, _wm_attr(key))
        except Exception:
            pass


def _snapshot_params(wm: bpy.types.WindowManager) -> None:
    """Push display values → physics values into the sim engine module."""
    from . import _world_passthrough as _wp
    for key in _ALL_KEYS:
        disp = getattr(wm, _wm_attr(key))
        if key in _PARAM_FLOAT_KEYS:
            setattr(_wp, key, _display_to_physics(key, disp))
        else:
            setattr(_wp, key, disp)
    phys_vals = ", ".join(
        f"{k}={getattr(_wp, k):.4g}" for k in _PARAM_FLOAT_KEYS
    )
    print(f"[hair_sim] params (physics): {phys_vals}")


# ---------------------------------------------------------------------------
# Save / Load preset operators
# ---------------------------------------------------------------------------

class HAIR_SIM_OT_save_params(Operator):
    bl_idname    = "hair_sim.save_params"
    bl_label     = "Save Params"
    bl_description = "Save current parameters to a JSON preset file"
    filepath: StringProperty(subtype="FILE_PATH", default="katsura_params.json")

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context: bpy.types.Context) -> set[str]:
        wm = context.window_manager
        out: dict = {}
        for key in _PARAM_FLOAT_KEYS:
            out[key] = _display_to_physics(key, getattr(wm, _wm_attr(key)))
        for key in _PARAM_INT_KEYS + _PARAM_BOOL_KEYS + _PARAM_STR_KEYS:
            out[key] = getattr(wm, _wm_attr(key))
        try:
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(out, f, indent=4)
            self.report({"INFO"}, f"Saved to {self.filepath}")
        except Exception as exc:
            self.report({"ERROR"}, f"Save failed: {exc}")
            return {"CANCELLED"}
        return {"FINISHED"}


class HAIR_SIM_OT_load_params(Operator):
    bl_idname    = "hair_sim.load_params"
    bl_label     = "Load Params"
    bl_description = "Load parameters from a JSON preset file"
    filepath: StringProperty(subtype="FILE_PATH")
    filter_glob: StringProperty(default="*.json", options={"HIDDEN"})

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context: bpy.types.Context) -> set[str]:
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            self.report({"ERROR"}, f"Load failed: {exc}")
            return {"CANCELLED"}
        wm = context.window_manager
        loaded = []
        for key, phys_val in data.items():
            attr = _wm_attr(key)
            if not hasattr(wm, attr):
                continue
            setattr(wm, attr,
                    _physics_to_display(key, phys_val) if key in _PARAM_FLOAT_KEYS
                    else phys_val)
            loaded.append(key)
        self.report({"INFO"}, f"Loaded {len(loaded)} params")
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# Solver interface
# ---------------------------------------------------------------------------

class SolverInterface:
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
            print(f"[hair_sim] start failed: '{_world_passthrough.TARGET_NAME}' not found or not Curves")
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
        if self._passthrough is not None:
            self._passthrough.step(scene)

    def playback(self, scene: bpy.types.Scene) -> None:
        if self._passthrough is not None:
            self._passthrough.playback(scene)


_solver = SolverInterface()


# ---------------------------------------------------------------------------
# Frame handler
# ---------------------------------------------------------------------------

@persistent
def _on_frame_change_post(scene: bpy.types.Scene, depsgraph: bpy.types.Depsgraph) -> None:
    wm   = bpy.context.window_manager
    if wm is None:
        return
    mode = getattr(wm, "hair_sim_mode", MODE_BYPASS)
    if   mode == MODE_SIMULATING:
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
    bl_idname    = "hair_sim.start"
    bl_label     = "Start"
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
    bl_idname    = "hair_sim.stop"
    bl_label     = "Stop"
    bl_description = "Enter PLAYBACK mode"

    def execute(self, context: bpy.types.Context) -> set[str]:
        wm = context.window_manager
        wm.hair_sim_mode = MODE_PLAYBACK
        _solver.playback(context.scene)
        self.report({"INFO"}, "Hair sim → PLAYBACK")
        return {"FINISHED"}


class HAIR_SIM_OT_bypass(Operator):
    bl_idname    = "hair_sim.bypass"
    bl_label     = "Bypass"
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
    HAIR_SIM_OT_save_params,
    HAIR_SIM_OT_load_params,
)


# ---------------------------------------------------------------------------
# Register / unregister
# ---------------------------------------------------------------------------

def register() -> None:
    _defaults = _load_defaults_json()
    for cls in _classes:
        bpy.utils.register_class(cls)
    WindowManager.hair_sim_mode = EnumProperty(
        name    = "Hair Sim Mode",
        items   = [
            (MODE_BYPASS,     "Bypass",     "Extension inactive"),
            (MODE_SIMULATING, "Simulating", "Run sim on +1 frames; restore from bake on scrub"),
            (MODE_PLAYBACK,   "Playback",   "Push baked state; no simulation"),
        ],
        default = MODE_BYPASS,
        options = {"SKIP_SAVE"},
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
