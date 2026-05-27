"""Tokoya — plant hair on a CC head using Vogel spiral seeded from an Empty.

Adapted from spiral-hair-build v5. Key change: instead of reading curve[0]
as the whorl position, we accept any Empty object directly.

No whorl marker curve is required. The Curves object may start empty or
already contain hair from previous plant operations — new strands are
appended.

Requirements (same as spiral-hair-build v5):
  - Exactly one Curves-type object in the scene.
  - curves.data.surface = CC_Base_Body (or similar mesh).
  - curves.data.surface_uv_map set to an existing UV layer.
  - Deform Curves on Surface modifier present.
  - An Armature with CC_Base_Tongue02 bone.
"""
from __future__ import annotations

import math
import random
import statistics

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.interpolate import poly_3d_calc

PPC                  = 8        # control points per curve
HAIR_LEN             = 0.04     # initial rest length (m) — 40 mm
R_HEAD               = 0.10     # head-sphere radius estimate (m)
MAX_POLAR            = 0.85 * math.pi
MAX_PROJ_OFFSET      = 0.03     # m — sphere point must land near actual skin
ALIGN_THRESHOLD      = -0.2     # face normal vs whorl-up; rejects steep undersides
MOUTH_BONE_NAME      = "CC_Base_Tongue02"
MOUTH_EXCLUSION_RADIUS = 0.05   # m


def plant_hair(empty_obj: bpy.types.Object, alpha_cm: float, beta_cm: float) -> dict:
    """Plant hair strands from *empty_obj*'s world location using a Vogel spiral.

    Parameters
    ----------
    empty_obj : bpy.types.Object
        An Empty whose world position defines the whorl (crown) position.
    alpha_cm : float
        Spiral radius in cm (max 35).
    beta_cm : float
        Target spacing between adjacent roots in cm (min 0.2).

    Returns
    -------
    dict with keys: n_added, total_curves, filtered, root_to_surface_max_um.

    Raises
    ------
    ValueError  if parameters are out of supported bounds.
    RuntimeError if scene pre-flight fails.
    """
    if alpha_cm > 35 or beta_cm < 0.2:
        raise ValueError(
            f"Out of supported bounds: alpha={alpha_cm} (max 35), beta={beta_cm} (min 0.2)"
        )
    r_max    = alpha_cm / 100.0
    c        = beta_cm  / 100.0
    SEG      = HAIR_LEN / (PPC - 1)
    MIN_PAIR = c * 0.5

    # ------------------------------------------------------------------ #
    # Pre-flight
    # ------------------------------------------------------------------ #
    curves_objs = [o for o in bpy.data.objects if o.type == "CURVES"]
    if len(curves_objs) != 1:
        raise RuntimeError(f"Expected exactly 1 Curves object, found {len(curves_objs)}")
    curves_obj  = curves_objs[0]
    curves_data = curves_obj.data

    body = curves_data.surface
    if body is None:
        raise RuntimeError("Curves.surface is not set — snap to surface first")
    if not curves_data.surface_uv_map:
        raise RuntimeError("Curves.surface_uv_map is empty")

    arm = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
    if arm is None or MOUTH_BONE_NAME not in arm.pose.bones:
        raise RuntimeError(
            f"Armature bone '{MOUTH_BONE_NAME}' not found — CC rig required"
        )

    # ------------------------------------------------------------------ #
    # Setup: BVH, sphere frame, mouth exclusion
    # ------------------------------------------------------------------ #
    deps      = bpy.context.evaluated_depsgraph_get()
    whorl_pos = empty_obj.matrix_world.translation.copy()  # world space

    body_eval  = body.evaluated_get(deps)
    eval_mesh  = body_eval.to_mesh()
    mat        = body_eval.matrix_world
    verts_w    = [mat @ v.co for v in eval_mesh.vertices]
    polys      = [tuple(p.vertices) for p in eval_mesh.polygons]
    bvh        = BVHTree.FromPolygons(verts_w, polys)

    _, whorl_normal, _, _ = bvh.find_nearest(whorl_pos)
    up  = whorl_normal.normalized()
    ref = Vector((0, 0, 1)) if abs(up.dot(Vector((0, 0, 1)))) < 0.95 else Vector((1, 0, 0))
    tx  = up.cross(ref).normalized()
    ty  = up.cross(tx).normalized()
    center = whorl_pos - up * R_HEAD

    mouth_center = arm.matrix_world @ arm.pose.bones[MOUTH_BONE_NAME].head

    # ------------------------------------------------------------------ #
    # Phase 1: Vogel spiral + filters
    # ------------------------------------------------------------------ #
    golden = math.radians(137.5077640500378)
    n_max  = int((r_max / c) ** 2)
    filt   = {
        "polar_too_large": 0, "off_surface": 0,
        "far_from_sphere": 0, "wrong_facing": 0, "mouth_zone": 0,
    }
    raw = []
    for n in range(1, n_max + 1):
        r     = c * math.sqrt(n)
        theta = n * golden
        polar = r / R_HEAD
        if polar > MAX_POLAR:
            filt["polar_too_large"] += 1
            continue
        sa, ca    = math.sin(polar), math.cos(polar)
        sphere_pt = center + R_HEAD * (
            sa * math.cos(theta) * tx + sa * math.sin(theta) * ty + ca * up
        )
        loc, normal, fi, _ = bvh.find_nearest(sphere_pt)
        if loc is None:
            filt["off_surface"] += 1;    continue
        if (loc - sphere_pt).length > MAX_PROJ_OFFSET:
            filt["far_from_sphere"] += 1; continue
        if normal.normalized().dot(up) < ALIGN_THRESHOLD:
            filt["wrong_facing"] += 1;   continue
        if (loc - mouth_center).length < MOUTH_EXCLUSION_RADIUS:
            filt["mouth_zone"] += 1;     continue
        raw.append({"loc": loc, "normal": normal, "fi": fi, "n": n})

    # ------------------------------------------------------------------ #
    # Phase 2: Greedy pairwise pruning (spiral order = closest-first)
    # ------------------------------------------------------------------ #
    raw.sort(key=lambda d: d["n"])
    accepted  = []
    candidates = []
    dupes     = 0
    for d in raw:
        if any((d["loc"] - ap).length < MIN_PAIR for ap in accepted):
            dupes += 1
            continue
        accepted.append(d["loc"])
        candidates.append(d)
    filt["duplicates_pruned"] = dupes

    # ------------------------------------------------------------------ #
    # Phase 3: UV + rest-space position via barycentric weights
    # ------------------------------------------------------------------ #
    rest_mesh = body.data
    rest_mat  = body.matrix_world
    uv_layer  = eval_mesh.uv_layers[curves_data.surface_uv_map]
    final     = []
    for d in candidates:
        poly_e  = eval_mesh.polygons[d["fi"]]
        verts_e = [mat @ eval_mesh.vertices[vi].co for vi in poly_e.vertices]
        w       = poly_3d_calc(verts_e, d["loc"])

        uv = Vector((0.0, 0.0))
        for wi, li in zip(w, poly_e.loop_indices):
            uv += wi * Vector(uv_layer.data[li].uv)

        poly_r  = rest_mesh.polygons[d["fi"]]
        verts_r = [rest_mat @ rest_mesh.vertices[vi].co for vi in poly_r.vertices]
        rest_pos = Vector((0.0, 0.0, 0.0))
        for wi, v in zip(w, verts_r):
            rest_pos += wi * v
        rest_normal = (rest_mat.to_3x3() @ poly_r.normal).normalized()
        final.append({"uv": uv, "rest_pos": rest_pos, "rest_normal": rest_normal})

    # ------------------------------------------------------------------ #
    # Phase 4: Append new curves to the data block
    # ------------------------------------------------------------------ #
    N          = len(final)
    ci_start   = len(curves_data.curves)     # first index of newly added curves
    curves_data.add_curves([PPC] * N)

    pos_attr    = curves_data.attributes["position"]

    # surface_uv_coordinate is auto-created by the sculpt brush but absent on
    # programmatically-built (empty) Curves objects — create it if missing.
    if "surface_uv_coordinate" not in curves_data.attributes:
        curves_data.attributes.new(
            name   = "surface_uv_coordinate",
            type   = "FLOAT2",
            domain = "CURVE",
        )
    uv_attr = curves_data.attributes["surface_uv_coordinate"]
    obj_winv    = curves_obj.matrix_world.inverted()
    obj_3x3_inv = curves_obj.matrix_world.to_3x3().inverted()

    for i, cand in enumerate(final):
        ci   = ci_start + i
        rp_l = obj_winv    @ cand["rest_pos"]
        rn_l = (obj_3x3_inv @ cand["rest_normal"]).normalized()
        for j in range(PPC):
            pos_attr.data[PPC * ci + j].vector = rp_l + rn_l * (SEG * j)
        uv_attr.data[ci].vector = cand["uv"]

    curves_data.update_tag()
    bpy.context.view_layer.update()

    # ------------------------------------------------------------------ #
    # Verification — root-to-surface distance
    # ------------------------------------------------------------------ #
    curves_eval2 = curves_obj.evaluated_get(deps)
    ep           = curves_eval2.data.points
    total        = len(curves_data.curves)
    dists_mm     = []
    roots_w      = []
    for ci in range(ci_start, total):
        rp = curves_eval2.matrix_world @ ep[ci * PPC].position
        roots_w.append(rp)
        _, _, _, dd = bvh.find_nearest(rp)
        dists_mm.append(dd * 1000)

    # Neighbor spacing sample
    nn = []
    if len(roots_w) > 1:
        random.seed(0)
        sample = random.sample(range(len(roots_w)), min(100, len(roots_w)))
        for i in sample:
            p  = roots_w[i]
            md = min(
                (roots_w[j] - p).length for j in range(len(roots_w)) if j != i
            )
            nn.append(md * 1000)

    body_eval.to_mesh_clear()

    max_dist = max(dists_mm) if dists_mm else 0.0
    if max_dist > 0.05:
        raise RuntimeError(
            f"Verification FAILED: max root-to-surface {max_dist:.4f} mm > 0.05 mm"
        )

    return {
        "n_added":              N,
        "total_curves":         total,
        "filtered":             filt,
        "root_to_surface_max_um": max_dist * 1000,
        "neighbor_spacing_mm": {
            "median": statistics.median(nn) if nn else 0,
            "min":    min(nn)               if nn else 0,
            "max":    max(nn)               if nn else 0,
        },
    }
