"""3D View N-panel for the Phase 1 hair simulation skeleton."""
from __future__ import annotations

import bpy
from bpy.types import Panel


class HAIR_SIM_PT_main(Panel):
    bl_idname = "HAIR_SIM_PT_main"
    bl_label = "Hair Simulation"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "HairSim"

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        wm = context.window_manager

        status = "Running" if wm.hair_sim_running else "Stopped"
        layout.label(text=f"Status: {status}")

        row = layout.row(align=True)
        row.operator("hair_sim.start", icon="PLAY")
        row.operator("hair_sim.stop", icon="PAUSE")

        layout.operator("hair_sim.reset", icon="FILE_REFRESH")


_classes = (HAIR_SIM_PT_main,)


def register() -> None:
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
