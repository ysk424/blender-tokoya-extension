"""3D View N-panel for the three-mode hair simulation."""
from __future__ import annotations

import bpy
from bpy.types import Panel


class HAIR_SIM_PT_main(Panel):
    bl_idname     = "HAIR_SIM_PT_main"
    bl_label      = "Hair Simulation"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "HairSim"

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        wm     = context.window_manager
        mode   = getattr(wm, "hair_sim_mode", "BYPASS")

        # Mode label.
        layout.label(text=f"Mode: {mode}")

        # Three buttons. depress=True highlights the active mode so the
        # user can see at a glance which one is currently selected.
        row = layout.row(align=True)
        row.operator("hair_sim.start",  text="Start",  icon="PLAY",         depress=(mode == "SIMULATING"))
        row.operator("hair_sim.stop",   text="Stop",   icon="PAUSE",        depress=(mode == "PLAYBACK"))
        row.operator("hair_sim.bypass", text="Bypass", icon="FILE_REFRESH", depress=(mode == "BYPASS"))


_classes = (HAIR_SIM_PT_main,)


def register() -> None:
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
