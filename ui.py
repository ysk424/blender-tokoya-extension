"""Tokoya N-panel (VIEW_3D sidebar, tab 'Tokoya')."""
from __future__ import annotations
import os, tomllib
import bpy
from bpy.types import Panel


def _version():
    try:
        path = os.path.join(os.path.dirname(__file__), "blender_manifest.toml")
        with open(path, "rb") as f:
            return tomllib.load(f).get("version", "?")
    except Exception:
        return "?"


class TOKOYA_PT_main(Panel):
    bl_idname      = "TOKOYA_PT_main"
    bl_label       = "Tokoya"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "Tokoya"

    def draw(self, context):
        layout = self.layout
        wm     = context.window_manager

        # Header
        layout.label(text=f"Tokoya  v{_version()}")
        layout.separator(factor=0.3)

        # Plant parameters
        box = layout.box()
        box.label(text="Mask Plant")
        col = box.column(align=True)
        col.operator("tokoya.create_head_mask", icon="MESH_DATA")
        col.prop(wm, "tokoya_strand_count")
        col.prop(wm, "tokoya_max_length_cm")

        # Persistent body and temporary cutter targets
        box = layout.box()
        box.label(text="Meshes")
        col = box.column(align=True)
        row = col.row(align=True)
        row.prop(wm, "tokoya_body_obj", text="Body")
        row.operator("tokoya.pick_body", text="", icon="EYEDROPPER")
        row = col.row(align=True)
        row.prop(wm, "tokoya_cutter_obj", text="Cutter")
        row.operator("tokoya.pick_cutter", text="", icon="EYEDROPPER")
        col.prop(wm, "tokoya_simulation_steps")
        col.prop(wm, "tokoya_compute_backend")

        layout.separator(factor=0.3)

        # Main buttons
        col = layout.column(align=True)
        col.operator("tokoya.plant_hair",  icon="OUTLINER_OB_CURVES")
        col.operator("tokoya.hair_remove",  icon="TRASH")
        col.operator("tokoya.simulate",     icon="PLAY")

        box = layout.box()
        box.label(text="Animation")
        col = box.column(align=True)
        col.prop(wm, "tokoya_auto_frame_interpolation")
        row = col.row(align=True)
        row.enabled = not wm.tokoya_auto_frame_interpolation
        row.prop(wm, "tokoya_frame_interpolation")
        if wm.tokoya_auto_frame_interpolation:
            col.label(
                text=f"Auto Steps: {wm.tokoya_auto_interpolation_current}"
            )
        recording = getattr(wm, "tokoya_record_mode", "PLAYBACK") == "RECORDING"
        row = col.row(align=True)
        row.alert = recording
        row.operator(
            "tokoya.record",
            text="REC" if not recording else "REC ●",
            icon="REC",
            depress=recording,
        )

        col = layout.column(align=True)
        col.separator()
        col.operator("tokoya.mesh_shrink",  icon="MOD_SOLIDIFY")
        col.separator()
        col.operator("tokoya.urchin_reset", icon="FORCE_FORCE")

        # Physics params
        layout.separator(factor=0.3)
        box = layout.box()
        box.label(text="Physics (applied at Simulate)")
        col = box.column(align=True)
        col.prop(wm, "tokoya_spring_ke")
        col.prop(wm, "tokoya_damping")
        col.prop(wm, "tokoya_particle_mass")
        col.prop(wm, "tokoya_gravity")
        col.separator()
        col.prop(wm, "tokoya_iterations")
        col.prop(wm, "tokoya_interpolation_mag")
        col.separator()
        col.prop(wm, "tokoya_bending_enabled")
        if getattr(wm, "tokoya_bending_enabled", False):
            col.prop(wm, "tokoya_root_bending_ke")
            col.prop(wm, "tokoya_bending_ke")


_classes = (TOKOYA_PT_main,)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
