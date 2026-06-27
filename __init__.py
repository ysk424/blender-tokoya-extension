from __future__ import annotations
import json, math, os
import bpy
from bpy.props import (
    BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty,
    IntProperty, StringProperty,
)
from bpy.types import Operator, WindowManager
from . import ui


def _load_defaults():
    path = os.path.join(os.path.dirname(__file__), "tokoya_defaults.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _snapshot_sim_params(wm):
    from . import _world_passthrough as _wp
    _wp.SPRING_KE       = 10.0 ** wm.tokoya_spring_ke
    _wp.DAMPING         = wm.tokoya_damping       / 100.0
    _wp.PARTICLE_MASS   = wm.tokoya_particle_mass / 1000.0
    _wp.GRAVITY         = tuple(wm.tokoya_gravity)
    _wp.ITERATIONS      = wm.tokoya_iterations
    _wp.SUBSTEPS        = 1
    _wp.BENDING_ENABLED = wm.tokoya_bending_enabled
    _wp.ROOT_BENDING_KE = 10.0 ** wm.tokoya_root_bending_ke
    _wp.BENDING_KE      = 10.0 ** wm.tokoya_bending_ke
    _wp.COMPUTE_BACKEND = wm.tokoya_compute_backend


def _find_curves_obj():
    objs = [o for o in bpy.data.objects if o.type == "CURVES"]
    return objs[0] if len(objs) == 1 else None


def _mark_hair_changed():
    return None


class TOKOYA_OT_create_head_mask(Operator):
    bl_idname = "tokoya.create_head_mask"
    bl_label = "Create Head Mask"
    bl_description = "Create a white scale-1 paint mesh from the Curves surface"

    def execute(self, context):
        curves_obj = _find_curves_obj()
        if curves_obj is None:
            self.report({"ERROR"}, "Need exactly one Curves object")
            return {"CANCELLED"}
        body_name = context.window_manager.tokoya_body_obj.strip()
        surface = bpy.data.objects.get(body_name)
        if surface is None or surface.type != "MESH":
            self.report({"ERROR"}, "Select a Body Mesh first")
            return {"CANCELLED"}
        curves_obj.data.surface = surface
        if not curves_obj.data.surface_uv_map and surface.data.uv_layers.active:
            curves_obj.data.surface_uv_map = surface.data.uv_layers.active.name

        from . import _mask_plant
        try:
            mask_obj = _mask_plant.create_head_mask(surface)
        except RuntimeError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        for obj in context.selected_objects:
            obj.select_set(False)
        mask_obj.select_set(True)
        context.view_layer.objects.active = mask_obj
        try:
            bpy.ops.object.mode_set(mode="TEXTURE_PAINT")
            paint = context.scene.tool_settings.image_paint
            if paint.brush is not None and hasattr(paint.brush, "color"):
                paint.brush.color = (0.0, 0.0, 0.0)
        except RuntimeError:
            pass

        self.report(
            {"INFO"},
            "Created Tokoya_HairMask: white=0 cm, black=max length",
        )
        return {"FINISHED"}


class TOKOYA_OT_plant_hair(Operator):
    bl_idname      = "tokoya.plant_hair"
    bl_label       = "Plant Hair"
    bl_description = "Plant strands from the grayscale texture on Ref Object (Mesh)"

    def execute(self, context):
        wm       = context.window_manager
        ref_obj = bpy.data.objects.get("Tokoya_HairMask")
        if ref_obj is None:
            self.report({"ERROR"}, "Create Tokoya_HairMask first"); return {"CANCELLED"}
        if ref_obj.type != "MESH":
            self.report({"ERROR"}, "Tokoya_HairMask must be a painted MESH")
            return {"CANCELLED"}
        from . import _mask_plant
        try:
            r = _mask_plant.plant_mask_hair(
                ref_obj,
                strand_count=wm.tokoya_strand_count,
                max_length_cm=wm.tokoya_max_length_cm,
            )
        except (ValueError, RuntimeError) as exc:
            self.report({"ERROR"}, str(exc)); return {"CANCELLED"}
        self.report({"INFO"},
            f"Planted {r['n_added']} strands / {r['total_points']} points. "
            f"Mean length {r['mean_length_cm']:.1f} cm")
        _mark_hair_changed()
        return {"FINISHED"}


class TOKOYA_OT_simulate(Operator):
    bl_idname      = "tokoya.simulate"
    bl_label       = "Simulate"
    bl_description = ("Run N steps of Taichi XPBD. "
                      "If Ref Object is a closed mesh, strands inside are frozen.")

    def execute(self, context):
        obj = _find_curves_obj()
        if obj is None:
            self.report({"ERROR"}, "Need exactly one Curves object"); return {"CANCELLED"}
        wm = context.window_manager
        _snapshot_sim_params(wm)

        from . import _world_passthrough as _wp
        body_name = wm.tokoya_body_obj.strip()
        body = bpy.data.objects.get(body_name)
        if body is None or body.type != "MESH":
            self.report({"ERROR"}, "Select a Body Mesh first"); return {"CANCELLED"}
        _wp.BODY_COLLISION_TARGET = body.name
        status = _wp.run_simulation(
            obj.name, wm.tokoya_simulation_steps, context.scene
        )
        if status.startswith("ERROR"):
            self.report({"ERROR"}, status); return {"CANCELLED"}
        _mark_hair_changed()
        self.report({"INFO"}, status)
        return {"FINISHED"}


class TOKOYA_OT_mesh_shrink(Operator):
    bl_idname      = "tokoya.mesh_shrink"
    bl_label       = "Mesh Shrink"
    bl_description = ("Shrink strands to first intersection with Ref mesh. "
                      "Plane=height-cut, half-sphere=round-cut.")

    def execute(self, context):
        obj = _find_curves_obj()
        if obj is None:
            self.report({"ERROR"}, "Need exactly one Curves object"); return {"CANCELLED"}
        ref_name = context.window_manager.tokoya_cutter_obj.strip()
        ref = bpy.data.objects.get(ref_name)
        if ref is None or ref.type != "MESH":
            t = ref.type if ref else "not found"
            self.report({"ERROR"},
                f"Ref Object must be MESH (got {t}). "
                "Ellipse/Circle are CURVE — use UV Sphere scaled to ellipsoid instead.")
            return {"CANCELLED"}
        from . import _mesh_ops
        n = _mesh_ops.mesh_shrink(obj, ref)
        _mark_hair_changed()
        self.report({"INFO"}, f"Shrunk {n} strands")
        return {"FINISHED"}


class TOKOYA_OT_urchin_reset(Operator):
    bl_idname      = "tokoya.urchin_reset"
    bl_label       = "Urchin Reset"
    bl_description = "Reset all strands to straight radial lines (arc-length preserved)"

    def execute(self, context):
        obj = _find_curves_obj()
        if obj is None:
            self.report({"ERROR"}, "Need exactly one Curves object"); return {"CANCELLED"}
        from . import _mesh_ops
        n = _mesh_ops.urchin_reset(obj)
        _mark_hair_changed()
        self.report({"INFO"}, f"Urchin reset: {n} strands")
        return {"FINISHED"}


class TOKOYA_OT_pick_body(Operator):
    bl_idname = "tokoya.pick_body"
    bl_label = "Pick Active as Body"

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.type != "MESH":
            self.report({"WARNING"}, "Active object must be a mesh")
            return {"CANCELLED"}
        context.window_manager.tokoya_body_obj = obj.name
        curves = _find_curves_obj()
        if curves is not None:
            curves.data.surface = obj
            if obj.data.uv_layers.active:
                curves.data.surface_uv_map = obj.data.uv_layers.active.name
        self.report({"INFO"}, f"Body Mesh: {obj.name!r}")
        return {"FINISHED"}


class TOKOYA_OT_pick_cutter(Operator):
    bl_idname = "tokoya.pick_cutter"
    bl_label = "Pick Active as Cutter"

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.type != "MESH":
            self.report({"WARNING"}, "Active object must be a mesh")
            return {"CANCELLED"}
        context.window_manager.tokoya_cutter_obj = obj.name
        self.report({"INFO"}, f"Cutter Mesh: {obj.name!r}")
        return {"FINISHED"}


_classes = (
    TOKOYA_OT_create_head_mask,
    TOKOYA_OT_plant_hair,
    TOKOYA_OT_simulate,
    TOKOYA_OT_mesh_shrink,
    TOKOYA_OT_urchin_reset,
    TOKOYA_OT_pick_body,
    TOKOYA_OT_pick_cutter,
)


def _install_handlers():
    return None


def _uninstall_handlers():
    return None


def register():
    defaults = _load_defaults()
    registered_classes = []
    ui_registered = False
    handlers_installed = False
    try:
        for cls in _classes:
            bpy.utils.register_class(cls)
            registered_classes.append(cls)

        WindowManager.tokoya_strand_count = IntProperty(
            name="Strands", description="Total number of mask-planted strands",
            default=4000, min=1, max=100000, options={"SKIP_SAVE"})
        WindowManager.tokoya_max_length_cm = FloatProperty(
            name="Max Length cm",
            description="Black mask length; gray is linearly shorter and white is zero",
            default=20.0, min=0.1, max=500.0, step=100, precision=1,
            options={"SKIP_SAVE"})
        WindowManager.tokoya_simulation_steps = IntProperty(
            name="Simulation Steps", description="Number of XPBD simulation steps",
            default=20, min=1, max=500, options={"SKIP_SAVE"})
        WindowManager.tokoya_compute_backend = EnumProperty(
            name="Compute",
            description="Taichi compute backend; changing it rebuilds the solver",
            items=(
                ("CUDA", "CUDA", "NVIDIA CUDA"),
                ("VULKAN", "Vulkan", "Vulkan compute"),
                ("CPU", "CPU", "CPU backend"),
            ),
            default="CUDA",
            options={"SKIP_SAVE"},
        )
        WindowManager.tokoya_body_obj = StringProperty(
            name="Body Mesh", description="Animated surface and collision mesh",
            default="", options={"SKIP_SAVE"})
        WindowManager.tokoya_cutter_obj = StringProperty(
            name="Cutter Mesh", description="Mesh used by Mesh Shrink",
            default="", options={"SKIP_SAVE"})
        WindowManager.tokoya_spring_ke = FloatProperty(
            name="Stiffness 10^N", default=math.log10(defaults["SPRING_KE"]),
            min=1.0, max=9.0, step=10, precision=2, options={"SKIP_SAVE"})
        WindowManager.tokoya_damping = FloatProperty(
            name="Damping /100", default=defaults["DAMPING"] * 100.0,
            min=0.0, max=50.0, step=10, precision=1, options={"SKIP_SAVE"})
        WindowManager.tokoya_particle_mass = FloatProperty(
            name="Mass /1000", default=defaults["PARTICLE_MASS"] * 1000.0,
            min=1.0, max=10000.0, step=100, precision=1, options={"SKIP_SAVE"})
        WindowManager.tokoya_gravity = FloatVectorProperty(
            name="Gravity m/s2", default=defaults["GRAVITY"],
            size=3, subtype="XYZ", min=-100.0, max=100.0,
            step=10, precision=2, options={"SKIP_SAVE"})
        WindowManager.tokoya_iterations = IntProperty(
            name="Iterations", default=int(defaults["ITERATIONS"]),
            min=1, max=64, options={"SKIP_SAVE"})
        WindowManager.tokoya_bending_enabled = BoolProperty(
            name="Bending", default=bool(defaults["BENDING_ENABLED"]),
            options={"SKIP_SAVE"})
        WindowManager.tokoya_root_bending_ke = FloatProperty(
            name="Root Stiff 10^N", default=math.log10(defaults["ROOT_BENDING_KE"]),
            min=0.0, max=7.0, step=10, precision=2, options={"SKIP_SAVE"})
        WindowManager.tokoya_bending_ke = FloatProperty(
            name="Strand Stiff 10^N", default=math.log10(defaults["BENDING_KE"]),
            min=0.0, max=6.0, step=10, precision=2, options={"SKIP_SAVE"})
        ui.register()
        ui_registered = True
        _install_handlers()
        handlers_installed = True
    except Exception:
        if handlers_installed:
            _uninstall_handlers()
        if ui_registered:
            try:
                ui.unregister()
            except Exception:
                pass
        for name in (
            "tokoya_strand_count", "tokoya_max_length_cm",
            "tokoya_simulation_steps", "tokoya_compute_backend",
            "tokoya_body_obj", "tokoya_cutter_obj",
            "tokoya_spring_ke", "tokoya_damping", "tokoya_particle_mass",
            "tokoya_gravity", "tokoya_iterations",
            "tokoya_bending_enabled", "tokoya_root_bending_ke",
            "tokoya_bending_ke",
        ):
            try:
                delattr(WindowManager, name)
            except Exception:
                pass
        for cls in reversed(registered_classes):
            try:
                bpy.utils.unregister_class(cls)
            except Exception:
                pass
        raise


def unregister():
    _uninstall_handlers()
    ui.unregister()
    for name in (
        "tokoya_strand_count", "tokoya_max_length_cm",
        "tokoya_simulation_steps", "tokoya_compute_backend",
        "tokoya_body_obj", "tokoya_cutter_obj",
        "tokoya_spring_ke", "tokoya_damping", "tokoya_particle_mass",
        "tokoya_gravity", "tokoya_iterations",
        "tokoya_bending_enabled", "tokoya_root_bending_ke", "tokoya_bending_ke",
    ):
        try: delattr(WindowManager, name)
        except Exception: pass
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
