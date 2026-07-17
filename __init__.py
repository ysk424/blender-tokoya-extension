from __future__ import annotations
import json, math, os, sys
import bpy
from bpy.props import (
    BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty,
    IntProperty, StringProperty,
)
from bpy.types import Operator, WindowManager
from mathutils import Vector
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


def _find_curves_obj(context=None):
    wm = context.window_manager if context is not None else bpy.context.window_manager
    name = getattr(wm, "tokoya_hair_obj", "").strip()
    if name:
        obj = bpy.data.objects.get(name)
        return obj if obj is not None and obj.type == "CURVES" else None
    objs = [o for o in bpy.data.objects if o.type == "CURVES"]
    return objs[0] if len(objs) == 1 else None


def _source_body_collider(context):
    name = getattr(context.window_manager, "tokoya_body_obj", "").strip()
    obj = bpy.data.objects.get(name)
    return obj if obj is not None and obj.type == "MESH" else None


def _source_clothes_collider(context):
    name = getattr(context.window_manager, "tokoya_clothes_obj", "").strip()
    obj = bpy.data.objects.get(name)
    return obj if obj is not None and obj.type == "MESH" else None


def _set_curves_surface(curves_obj, surface_obj):
    if curves_obj is None or curves_obj.type != "CURVES":
        return
    if surface_obj is None or surface_obj.type != "MESH":
        return
    curves_obj.data.surface = surface_obj
    if not curves_obj.data.surface_uv_map and surface_obj.data.uv_layers.active:
        curves_obj.data.surface_uv_map = surface_obj.data.uv_layers.active.name


def _settle_colliders(context, extra_clothes=None, include_manual_clothes=True):
    from . import _collider_proxy

    wm = context.window_manager
    body = _source_body_collider(context)
    if body is None:
        raise ValueError("Select a Body Mesh first")

    proxy = _collider_proxy.get_valid_proxy(
        body,
        getattr(wm, "tokoya_collider_proxy_obj", ""),
    )
    if proxy is None:
        for obj in bpy.data.objects:
            if (
                obj.type == "MESH"
                and bool(obj.get(_collider_proxy.PROXY_FLAG, False))
                and obj.get(_collider_proxy.PROXY_SOURCE) == body.name
            ):
                proxy = obj
                wm.tokoya_collider_proxy_obj = obj.name
                break
    proxy_created = False
    if proxy is None:
        stats = _collider_proxy.build_filled_proxy(
            body,
            getattr(wm, "tokoya_collider_proxy_obj", ""),
        )
        wm.tokoya_collider_proxy_obj = stats["proxy_name"]
        proxy = bpy.data.objects.get(stats["proxy_name"])
        proxy_created = True

    colliders = [proxy if proxy is not None else body]
    clothes = _source_clothes_collider(context) if include_manual_clothes else None
    if clothes is not None:
        colliders.append(clothes)
    for extra in extra_clothes or ():
        if extra is not None and extra.type == "MESH":
            colliders.append(extra)
    proxy_name = proxy.name if proxy is not None else ""
    return colliders, proxy_created, proxy_name


def _remove_mesh_object(obj):
    if obj is None:
        return
    mesh = obj.data if obj.type == "MESH" else None
    bpy.data.objects.remove(obj, do_unlink=True)
    if mesh is not None and mesh.users == 0:
        bpy.data.meshes.remove(mesh)


def _clear_settle_proxy(context, proxy_name=""):
    from . import _collider_proxy

    wm = context.window_manager
    names = set()
    if proxy_name:
        names.add(proxy_name)
    stored_name = getattr(wm, "tokoya_collider_proxy_obj", "").strip()
    if stored_name:
        names.add(stored_name)

    body = _source_body_collider(context)
    if body is not None:
        for obj in list(bpy.data.objects):
            if (
                obj.type == "MESH"
                and bool(obj.get(_collider_proxy.PROXY_FLAG, False))
                and obj.get(_collider_proxy.PROXY_SOURCE) == body.name
            ):
                names.add(obj.name)

    for name in names:
        _collider_proxy.clear_proxy(name)
    wm.tokoya_collider_proxy_obj = ""


def _clear_auto_bangs_cutter(context, cutter):
    if cutter is None:
        return
    name = cutter.name
    if bpy.data.objects.get(name) is None:
        return
    if cutter.get("tokoya_source") == "auto_bangs_trim":
        _remove_mesh_object(cutter)
        if context.window_manager.tokoya_cutter_obj == name:
            context.window_manager.tokoya_cutter_obj = ""


def _object_world_bounds(obj):
    corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    return {
        "min_x": min(point.x for point in corners),
        "max_x": max(point.x for point in corners),
        "min_y": min(point.y for point in corners),
        "max_y": max(point.y for point in corners),
        "min_z": min(point.z for point in corners),
        "max_z": max(point.z for point in corners),
    }


def _mesh_world_points(obj):
    deps = bpy.context.evaluated_depsgraph_get()
    eval_obj = obj.evaluated_get(deps)
    mesh = eval_obj.to_mesh()
    try:
        mat = eval_obj.matrix_world.copy()
        return [mat @ v.co for v in mesh.vertices]
    finally:
        eval_obj.to_mesh_clear()


def _find_eye_source_objects():
    exact_groups = (
        ("CC_Base_EyeOcclusion",),
        ("CC_Base_TearLine",),
        ("CC_Base_Eye",),
    )
    for names in exact_groups:
        objs = [
            bpy.data.objects.get(name)
            for name in names
            if bpy.data.objects.get(name) is not None
            and bpy.data.objects.get(name).type == "MESH"
        ]
        if objs:
            return objs

    pattern_groups = (
        ("eyeocclusion", "eye_occlusion"),
        ("tearline", "tear_line"),
        ("eye",),
    )
    for patterns in pattern_groups:
        objs = []
        for obj in bpy.data.objects:
            if obj.type != "MESH":
                continue
            name = obj.name.lower()
            if "lash" in name or "brow" in name:
                continue
            if any(pattern in name for pattern in patterns):
                objs.append(obj)
        if objs:
            return objs
    return []


def _detect_eye_opening_bounds():
    sources = _find_eye_source_objects()
    if not sources:
        raise RuntimeError("Could not find an eye mesh such as CC_Base_EyeOcclusion")

    pts = []
    for obj in sources:
        pts.extend(_mesh_world_points(obj))
    if not pts:
        names = ", ".join(obj.name for obj in sources)
        raise RuntimeError(f"Eye mesh has no evaluated vertices: {names}")

    return {
        "source_names": [obj.name for obj in sources],
        "min_x": min(p.x for p in pts),
        "max_x": max(p.x for p in pts),
        "min_y": min(p.y for p in pts),
        "max_y": max(p.y for p in pts),
        "min_z": min(p.z for p in pts),
        "max_z": max(p.z for p in pts),
    }


def _material_for_bangs_cutter():
    mat = bpy.data.materials.get("Tokoya_BangsAutoCutter_Material")
    if mat is None:
        mat = bpy.data.materials.new("Tokoya_BangsAutoCutter_Material")
    mat.diffuse_color = (1.0, 0.45, 0.05, 0.45)
    try:
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf is not None:
            if "Base Color" in bsdf.inputs:
                bsdf.inputs["Base Color"].default_value = (1.0, 0.45, 0.05, 0.45)
            if "Alpha" in bsdf.inputs:
                bsdf.inputs["Alpha"].default_value = 0.45
        mat.blend_method = "BLEND"
    except Exception:
        pass
    return mat


def _create_bangs_cutter(context, side_extra_cm, z_extra_cm):
    bounds = _detect_eye_opening_bounds()
    side_extra_m = max(0.0, float(side_extra_cm)) * 0.01
    z_extra_m = max(0.0, float(z_extra_cm)) * 0.01

    left_x = bounds["min_x"] - side_extra_m
    right_x = bounds["max_x"] + side_extra_m
    center_y = bounds["min_y"] - 0.020
    y0 = center_y - 0.050
    y1 = center_y + 0.050
    z = bounds["max_z"] + z_extra_m

    mesh = bpy.data.meshes.new("Tokoya_BangsAutoCutter_Mesh")
    verts = [
        (left_x, y0, z),
        (right_x, y0, z),
        (right_x, y1, z),
        (left_x, y1, z),
    ]
    mesh.from_pydata(verts, [], [(0, 1, 2, 3)])
    mesh.update()
    mesh.materials.append(_material_for_bangs_cutter())

    obj = bpy.data.objects.get("Tokoya_BangsAutoCutter")
    if obj is not None and obj.type == "MESH":
        old_mesh = obj.data
        obj.data = mesh
        obj.location = (0.0, 0.0, 0.0)
        obj.rotation_euler = (0.0, 0.0, 0.0)
        obj.scale = (1.0, 1.0, 1.0)
        if old_mesh.users == 0:
            bpy.data.meshes.remove(old_mesh)
    else:
        obj = bpy.data.objects.new("Tokoya_BangsAutoCutter", mesh)
        context.scene.collection.objects.link(obj)

    if not obj.users_collection:
        context.scene.collection.objects.link(obj)
    obj.hide_render = True
    obj.show_in_front = True
    obj["tokoya_source"] = "auto_bangs_trim"
    obj["tokoya_eye_sources"] = ",".join(bounds["source_names"])
    obj["tokoya_side_extra_cm"] = float(side_extra_cm)
    obj["tokoya_z_extra_cm"] = float(z_extra_cm)
    obj["tokoya_width_m"] = float(right_x - left_x)
    obj["tokoya_y_span_m"] = 0.100
    obj["tokoya_z_m"] = float(z)
    context.window_manager.tokoya_cutter_obj = obj.name
    return obj, bounds


def _back_flow_guide_params(context):
    body = _source_body_collider(context)
    if body is None:
        raise RuntimeError("Select a Body Mesh first")

    body_bounds = _object_world_bounds(body)
    try:
        eye_bounds = _detect_eye_opening_bounds()
    except RuntimeError:
        eye_bounds = None

    if eye_bounds is not None:
        eye_top_z = eye_bounds["max_z"]
        face_front_y = min(body_bounds["min_y"], eye_bounds["min_y"])
        z_top = min(body_bounds["max_z"] - 0.030, eye_top_z + 0.100)
        z_shoulder = eye_top_z - 0.248
    else:
        face_front_y = body_bounds["min_y"]
        z_top = body_bounds["max_z"] - 0.035
        z_shoulder = z_top - 0.350

    body_back_y = body_bounds["max_y"]
    z_low = max(body_bounds["min_z"] + 0.850, z_shoulder - 0.380)
    return {
        "z_top": float(z_top),
        "y_top": float(face_front_y - 0.035),
        "z_shoulder": float(z_shoulder),
        "y_shoulder": float(body_back_y + 0.065),
        "z_low": float(z_low),
        "y_low": float(body_back_y + 0.125),
        "z_drop_m": 0.015,
    }


def _mark_hair_changed():
    return None


class TOKOYA_OT_create_head_mask(Operator):
    bl_idname = "tokoya.create_head_mask"
    bl_label = "Create Head Mask"
    bl_description = "Create a white scale-1 paint mesh from the Curves surface"

    def execute(self, context):
        curves_obj = _find_curves_obj(context)
        if curves_obj is None:
            self.report({"ERROR"}, "Pick one Hair Curves object")
            return {"CANCELLED"}
        surface = _source_body_collider(context)
        if surface is None or surface.type != "MESH":
            self.report({"ERROR"}, "Select a Body Mesh first")
            return {"CANCELLED"}
        _set_curves_surface(curves_obj, surface)

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
        curves_obj = _find_curves_obj(context)
        if curves_obj is None:
            self.report({"ERROR"}, "Pick one Hair Curves object")
            return {"CANCELLED"}
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
                curves_obj=curves_obj,
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
    bl_label       = "Settle Hair Back"
    bl_description = "Initial groom: lay long straight hair behind the body using the Yurameki settle pass"

    def execute(self, context):
        obj = _find_curves_obj(context)
        if obj is None:
            self.report({"ERROR"}, "Pick one Hair Curves object"); return {"CANCELLED"}
        wm = context.window_manager
        proxy_name = ""
        try:
            from . import _initial_groom

            colliders, proxy_created, proxy_name = _settle_colliders(context)
            stats = _initial_groom.settle_hair_back(
                obj,
                colliders,
                max_strands=0,
                collision_radius_m=float(wm.tokoya_groom_radius_mm) * 1.0e-3,
                follow_radius_m=float(wm.tokoya_groom_follow_mm) * 1.0e-3,
                release_probe_m=float(wm.tokoya_groom_release_mm) * 1.0e-3,
            )
        except Exception as exc:
            self.report({"ERROR"}, f"Settle Hair Back failed: {exc!r}")
            return {"CANCELLED"}
        finally:
            _clear_settle_proxy(context, proxy_name)
        _mark_hair_changed()
        proxy_note = "proxy created, " if proxy_created else ""
        self.report(
            {"INFO"},
            f"Settle Hair Back: {proxy_note}"
            f"strands={stats['processed_strands']}, "
            f"time={stats['elapsed_sec']:.2f}s, "
            f"len_err={stats['max_length_error_mm']:.6f}mm, "
            f"close={stats['remaining_close_points']}, "
            f"root_lock={stats.get('normal_root_locks', 0)}, "
            f"turn={stats.get('angle_limited_rods', 0)}, "
            f"lower_free={stats.get('lower_free_rods', 0)}, "
            f"tip_down={stats['avg_tip_down_dot']:.3f}",
        )
        return {"FINISHED"}


class TOKOYA_OT_settle_with_guide(Operator):
    bl_idname = "tokoya.settle_with_guide"
    bl_label = "Settle With Guide"
    bl_description = "Settle hair back using a temporary slanted guide mesh instead of the Clothes object"

    def execute(self, context):
        obj = _find_curves_obj(context)
        if obj is None:
            self.report({"ERROR"}, "Pick one Hair Curves object")
            return {"CANCELLED"}
        wm = context.window_manager
        proxy_name = ""
        guide_params = None
        try:
            from . import _initial_groom

            guide_params = _back_flow_guide_params(context)
            colliders, proxy_created, proxy_name = _settle_colliders(
                context,
                include_manual_clothes=False,
            )
            stats = _initial_groom.settle_hair_back(
                obj,
                colliders,
                max_strands=0,
                collision_radius_m=float(wm.tokoya_groom_radius_mm) * 1.0e-3,
                follow_radius_m=float(wm.tokoya_groom_follow_mm) * 1.0e-3,
                release_probe_m=float(wm.tokoya_groom_release_mm) * 1.0e-3,
                back_flow_guide=guide_params,
            )
        except Exception as exc:
            self.report({"ERROR"}, f"Settle With Guide failed: {exc!r}")
            return {"CANCELLED"}
        finally:
            _clear_settle_proxy(context, proxy_name)
        _mark_hair_changed()
        proxy_note = "proxy created, " if proxy_created else ""
        self.report(
            {"INFO"},
            f"Settle With Guide: {proxy_note}"
            f"strands={stats['processed_strands']}, "
            f"time={stats['elapsed_sec']:.2f}s, "
            f"len_err={stats['max_length_error_mm']:.6f}mm, "
            f"close={stats['remaining_close_points']}, "
            f"guide={stats.get('back_flow_guided_rods', 0)}, "
            f"tip_down={stats['avg_tip_down_dot']:.3f}",
        )
        return {"FINISHED"}


class TOKOYA_OT_mesh_shrink(Operator):
    bl_idname      = "tokoya.mesh_shrink"
    bl_label       = "Mesh Shrink"
    bl_description = ("Shrink strands to first intersection with Ref mesh. "
                      "Plane=height-cut, half-sphere=round-cut.")

    def execute(self, context):
        obj = _find_curves_obj(context)
        if obj is None:
            self.report({"ERROR"}, "Pick one Hair Curves object"); return {"CANCELLED"}
        ref_name = context.window_manager.tokoya_cutter_obj.strip()
        ref = bpy.data.objects.get(ref_name)
        if ref is None or ref.type != "MESH":
            t = ref.type if ref else "not found"
            self.report({"ERROR"},
                f"Ref Object must be MESH (got {t}). "
                "Ellipse/Circle are CURVE - use UV Sphere scaled to ellipsoid instead.")
            return {"CANCELLED"}
        from . import _mesh_ops
        n = _mesh_ops.mesh_shrink(obj, ref)
        _mark_hair_changed()
        self.report({"INFO"}, f"Shrunk {n} strands")
        return {"FINISHED"}


class TOKOYA_OT_trim_bangs(Operator):
    bl_idname = "tokoya.trim_bangs"
    bl_label = "Trim Bangs"
    bl_description = "Create an eye-based cutter plane and run Mesh Shrink"

    def execute(self, context):
        obj = _find_curves_obj(context)
        if obj is None:
            self.report({"ERROR"}, "Pick one Hair Curves object")
            return {"CANCELLED"}
        wm = context.window_manager
        cutter = None
        cutter_name = ""
        try:
            cutter, bounds = _create_bangs_cutter(
                context,
                wm.tokoya_bangs_side_extra_cm,
                wm.tokoya_bangs_z_extra_cm,
            )
            cutter_name = cutter.name
            from . import _mesh_ops

            n = _mesh_ops.mesh_shrink(obj, cutter)
        except Exception as exc:
            self.report({"ERROR"}, f"Trim Bangs failed: {exc}")
            return {"CANCELLED"}
        finally:
            _clear_auto_bangs_cutter(context, cutter)
        _mark_hair_changed()
        self.report(
            {"INFO"},
            f"Trim Bangs: shrunk {n} strands, "
            f"eye={'+'.join(bounds['source_names'])}, cutter={cutter_name}",
        )
        return {"FINISHED"}


class TOKOYA_OT_urchin_reset(Operator):
    bl_idname      = "tokoya.urchin_reset"
    bl_label       = "Urchin Reset"
    bl_description = "Reset all strands to straight radial lines (arc-length preserved)"

    def execute(self, context):
        obj = _find_curves_obj(context)
        if obj is None:
            self.report({"ERROR"}, "Pick one Hair Curves object"); return {"CANCELLED"}
        from . import _mesh_ops
        n = _mesh_ops.urchin_reset(obj)
        _mark_hair_changed()
        self.report({"INFO"}, f"Urchin reset: {n} strands")
        return {"FINISHED"}


class TOKOYA_OT_pick_hair(Operator):
    bl_idname = "tokoya.pick_hair"
    bl_label = "Pick Active as Hair"

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.type != "CURVES":
            self.report({"WARNING"}, "Active object must be Curves")
            return {"CANCELLED"}
        context.window_manager.tokoya_hair_obj = obj.name
        body = _source_body_collider(context)
        _set_curves_surface(obj, body)
        self.report({"INFO"}, f"Hair Curves: {obj.name!r}")
        return {"FINISHED"}


class TOKOYA_OT_pick_body(Operator):
    bl_idname = "tokoya.pick_body"
    bl_label = "Pick Active as Body"

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.type != "MESH":
            self.report({"WARNING"}, "Active object must be a mesh")
            return {"CANCELLED"}
        from . import _collider_proxy

        _collider_proxy.clear_proxy(
            getattr(context.window_manager, "tokoya_collider_proxy_obj", "")
        )
        context.window_manager.tokoya_collider_proxy_obj = ""
        context.window_manager.tokoya_body_obj = obj.name
        curves = _find_curves_obj(context)
        _set_curves_surface(curves, obj)
        self.report({"INFO"}, f"Body Mesh: {obj.name!r}")
        return {"FINISHED"}


class TOKOYA_OT_pick_clothes(Operator):
    bl_idname = "tokoya.pick_clothes"
    bl_label = "Pick Active as Clothes"

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.type != "MESH":
            self.report({"WARNING"}, "Active object must be a mesh")
            return {"CANCELLED"}
        context.window_manager.tokoya_clothes_obj = obj.name
        self.report({"INFO"}, f"Clothes Mesh: {obj.name!r}")
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


def _blender_python_exe():
    base = os.path.join(sys.prefix, "bin")
    win = os.path.join(base, "python.exe")
    if os.path.exists(win):
        return win
    nix = os.path.join(base, "python%d.%d" % sys.version_info[:2])
    return nix if os.path.exists(nix) else sys.executable


def _taichi_installed():
    import importlib.util, site
    user_site = site.getusersitepackages()
    if user_site not in sys.path:
        sys.path.append(user_site)
    return importlib.util.find_spec("taichi") is not None


class TOKOYA_OT_install_deps(Operator):
    bl_idname = "tokoya.install_deps"
    bl_label = "Install Dependencies (taichi)"
    bl_description = (
        "Download and install the taichi runtime into the Blender Python "
        "user site. Requires a network connection"
    )
    bl_options = {"REGISTER"}

    def execute(self, context):
        import subprocess
        python_exe = _blender_python_exe()
        try:
            subprocess.run([python_exe, "-m", "ensurepip"], check=False)
            subprocess.run(
                [python_exe, "-m", "pip", "install", "--user", "taichi==1.7.4"],
                check=True,
            )
        except Exception as exc:  # noqa: BLE001 - report any install failure to the user
            self.report({"ERROR"}, "taichi install failed: %s" % exc)
            return {"CANCELLED"}
        self.report({"INFO"}, "taichi installed. Restart Blender if it is still not detected.")
        return {"FINISHED"}


class TOKOYA_AddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    def draw(self, context):
        layout = self.layout
        if _taichi_installed():
            layout.label(text="taichi: installed", icon="CHECKMARK")
        else:
            layout.label(text="taichi: not found - simulation is disabled", icon="ERROR")
        layout.operator(TOKOYA_OT_install_deps.bl_idname, icon="IMPORT")
        layout.label(text="Installs into the Blender Python user site. Needs network access.")


_classes = (
    TOKOYA_OT_create_head_mask,
    TOKOYA_OT_plant_hair,
    TOKOYA_OT_simulate,
    TOKOYA_OT_settle_with_guide,
    TOKOYA_OT_mesh_shrink,
    TOKOYA_OT_trim_bangs,
    TOKOYA_OT_urchin_reset,
    TOKOYA_OT_pick_hair,
    TOKOYA_OT_pick_body,
    TOKOYA_OT_pick_clothes,
    TOKOYA_OT_pick_cutter,
    TOKOYA_OT_install_deps,
    TOKOYA_AddonPreferences,
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
        WindowManager.tokoya_hair_obj = StringProperty(
            name="Hair", description="Curves object to plant, groom, cut, and reset",
            default="", options={"SKIP_SAVE"})
        WindowManager.tokoya_body_obj = StringProperty(
            name="Body Mesh", description="Animated surface and collision mesh",
            default="", options={"SKIP_SAVE"})
        WindowManager.tokoya_clothes_obj = StringProperty(
            name="Clothes Mesh", description="Optional clothes collider used by Settle Hair Back",
            default="", options={"SKIP_SAVE"})
        WindowManager.tokoya_collider_proxy_obj = StringProperty(
            name="Collider Proxy", description="Auto-filled Body proxy used by Settle Hair Back",
            default="", options={"SKIP_SAVE"})
        WindowManager.tokoya_cutter_obj = StringProperty(
            name="Cutter Mesh", description="Mesh used by Mesh Shrink",
            default="", options={"SKIP_SAVE"})
        WindowManager.tokoya_bangs_side_extra_cm = FloatProperty(
            name="Side + cm",
            description="Extra width added to both eye-width ends for Trim Bangs",
            default=1.0, min=0.0, max=50.0, step=10, precision=2,
            options={"SKIP_SAVE"})
        WindowManager.tokoya_bangs_z_extra_cm = FloatProperty(
            name="Z + cm",
            description="Height added above the detected eye top for Trim Bangs",
            default=3.0, min=0.0, max=50.0, step=10, precision=2,
            options={"SKIP_SAVE"})
        WindowManager.tokoya_groom_radius_mm = FloatProperty(
            name="Groom Radius mm",
            default=float(defaults.get("GROOM_RADIUS_MM", 2.5)),
            min=0.1, max=20.0, precision=3, options={"SKIP_SAVE"})
        WindowManager.tokoya_groom_follow_mm = FloatProperty(
            name="Follow mm",
            default=float(defaults.get("GROOM_FOLLOW_MM", 30.0)),
            min=1.0, max=200.0, precision=3, options={"SKIP_SAVE"})
        WindowManager.tokoya_groom_release_mm = FloatProperty(
            name="Release Probe mm",
            default=float(defaults.get("GROOM_RELEASE_MM", 20.0)),
            min=1.0, max=200.0, precision=3, options={"SKIP_SAVE"})
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
            "tokoya_hair_obj", "tokoya_body_obj", "tokoya_clothes_obj",
            "tokoya_collider_proxy_obj", "tokoya_cutter_obj",
            "tokoya_bangs_side_extra_cm", "tokoya_bangs_z_extra_cm",
            "tokoya_groom_radius_mm", "tokoya_groom_follow_mm",
            "tokoya_groom_release_mm",
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
        "tokoya_hair_obj", "tokoya_body_obj", "tokoya_clothes_obj",
        "tokoya_collider_proxy_obj", "tokoya_cutter_obj",
        "tokoya_bangs_side_extra_cm", "tokoya_bangs_z_extra_cm",
        "tokoya_groom_radius_mm", "tokoya_groom_follow_mm",
        "tokoya_groom_release_mm",
        "tokoya_spring_ke", "tokoya_damping", "tokoya_particle_mass",
        "tokoya_gravity", "tokoya_iterations",
        "tokoya_bending_enabled", "tokoya_root_bending_ke", "tokoya_bending_ke",
    ):
        try: delattr(WindowManager, name)
        except Exception: pass
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
