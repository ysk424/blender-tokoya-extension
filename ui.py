"""3D View N-panel — Katsura Hair Simulation."""
from __future__ import annotations

import math

import bpy
from bpy.types import Panel


def _get_actual_label(key: str, disp_val: float) -> str:
    """Return a string showing the actual physics value for scaled/log properties."""
    if key in ("SPRING_KE", "ROOT_BENDING_KE", "BENDING_KE"):
        phys = 10.0 ** disp_val
        if phys >= 1_000_000:
            return f"= {phys/1_000_000:.2g}M"
        if phys >= 1_000:
            return f"= {phys/1_000:.3g}k"
        return f"= {phys:.4g}"
    if key == "DAMPING":
        return f"= {disp_val/100:.4f}"
    if key == "PARTICLE_MASS":
        return f"= {disp_val/1000:.4g} kg"
    return ""


class HAIR_SIM_PT_main(Panel):
    bl_idname      = "HAIR_SIM_PT_main"
    bl_label       = "Katsura"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "Katsura"

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        wm     = context.window_manager
        mode   = getattr(wm, "hair_sim_mode", "BYPASS")

        # ---- Header: name + version ----
        try:
            import os, tomllib
            path = os.path.join(os.path.dirname(__file__), "blender_manifest.toml")
            with open(path, "rb") as _f:
                version = tomllib.load(_f).get("version", "?")
        except Exception:
            version = "?"
        row = layout.row()
        row.label(text=f"Katsura v{version}", icon="HAIR")

        # ---- Mode buttons ----
        row = layout.row(align=True)
        row.operator("hair_sim.start",  text="Start",  icon="PLAY",
                     depress=(mode == "SIMULATING"))
        row.operator("hair_sim.stop",   text="Stop",   icon="PAUSE",
                     depress=(mode == "PLAYBACK"))
        row.operator("hair_sim.bypass", text="Bypass", icon="FILE_REFRESH",
                     depress=(mode == "BYPASS"))

        layout.label(text=f"Mode: {mode}")

        # ---- Save / Load preset ----
        row = layout.row(align=True)
        row.operator("hair_sim.save_params", text="Save Params", icon="FILE_TICK")
        row.operator("hair_sim.load_params", text="Load Params", icon="FILE_FOLDER")

        layout.separator(factor=0.5)
        layout.label(text="Params (applied at next Start):")

        # ---- Dynamics ----
        box = layout.box()
        box.label(text="Dynamics", icon="FORCE_GRAVITY")
        col = box.column(align=True)
        for key in ("SPRING_KE", "DAMPING", "PARTICLE_MASS", "GRAVITY"):
            attr = "hair_sim_param_" + key.lower()
            if hasattr(wm, attr):
                disp_val = getattr(wm, attr)
                actual   = _get_actual_label(key, disp_val)
                if actual:
                    row = col.row(align=True)
                    row.prop(wm, attr)
                    row.label(text=actual)
                else:
                    col.prop(wm, attr)

        # ---- Solver ----
        box = layout.box()
        box.label(text="Solver", icon="MOD_PHYSICS")
        col = box.column(align=True)
        for key in ("ITERATIONS", "SUBSTEPS"):
            attr = "hair_sim_param_" + key.lower()
            if hasattr(wm, attr):
                col.prop(wm, attr)

        # ---- Bending ----
        box = layout.box()
        bend_attr = "hair_sim_param_bending_enabled"
        box.prop(wm, bend_attr, text="Bending")
        if getattr(wm, bend_attr, False):
            col = box.column(align=True)
            for key in ("ROOT_BENDING_KE", "BENDING_KE"):
                attr = "hair_sim_param_" + key.lower()
                if hasattr(wm, attr):
                    disp_val = getattr(wm, attr)
                    actual   = _get_actual_label(key, disp_val)
                    row = col.row(align=True)
                    row.prop(wm, attr)
                    row.label(text=actual)

        # ---- Collision ----
        box = layout.box()
        coll_attr = "hair_sim_param_body_collision_enabled"
        box.prop(wm, coll_attr, text="Body Collision")
        if getattr(wm, coll_attr, False):
            tgt_attr = "hair_sim_param_body_collision_target"
            if hasattr(wm, tgt_attr):
                box.prop(wm, tgt_attr, text="Target")


_classes = (HAIR_SIM_PT_main,)


def register() -> None:
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
