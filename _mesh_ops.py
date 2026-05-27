"""Tokoya — geometric hair operations.

Coordinate convention
---------------------
- local  : Curves object local space (stored in 'position' attribute, never includes modifier).
- eval   : Evaluated world space (after Surface Deform modifier + matrix_world).
           Used for ALL intersection tests so that results match what the user sees.
- Writes always go to local positions (no modifier compensation needed for pure
  scale-from-root operations, because scale is dimensionless).

Operations
----------
extend_length  : scale all strands to a target arc-length (bigger urchin).
mesh_shrink    : proportionally shrink strands to their first mesh intersection
                 (walking segments from root toward tip, bidirectional ray cast).
mesh_extend    : extend strands whose root→tip ray hits the mesh BEYOND the
                 current tip (short strands grow to fill the mesh boundary).
urchin_reset   : redistribute all strand points along root-normal direction
                 (arc-length preserved).
"""
from __future__ import annotations

import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

_PPC = 8  # must match _spiral_plant.PPC


# ------------------------------------------------------------------ #
# Internal helpers
# ------------------------------------------------------------------ #

def _read_local(curves_obj: bpy.types.Object) -> np.ndarray:
    """Return (n_total, 3) float32 in LOCAL space."""
    attr = curves_obj.data.attributes.get("position")
    n    = len(attr.data)
    flat = np.zeros(n * 3, dtype=np.float32)
    attr.data.foreach_get("vector", flat)
    return flat.reshape(n, 3)


def _write_local(curves_obj: bpy.types.Object, local_pts: np.ndarray) -> None:
    """Write (n_total, 3) float32 back to local position attribute."""
    attr = curves_obj.data.attributes.get("position")
    attr.data.foreach_set("vector", local_pts.ravel().astype(np.float32))
    curves_obj.data.update_tag()


def _read_world_eval(curves_obj: bpy.types.Object) -> np.ndarray:
    """Return (n_total, 3) float32 in WORLD space — uses evaluated mesh
    so the Surface Deform modifier offset is included.

    This is the position the user *sees*, and should be used for all
    intersection tests.
    """
    deps     = bpy.context.evaluated_depsgraph_get()
    eval_obj = curves_obj.evaluated_get(deps)
    attr     = eval_obj.data.attributes.get("position")
    n        = len(attr.data)
    flat     = np.zeros(n * 3, dtype=np.float32)
    attr.data.foreach_get("vector", flat)
    local_pts = flat.reshape(n, 3)
    mw  = np.array(eval_obj.matrix_world, dtype=np.float32)
    lh  = np.column_stack([local_pts, np.ones(n, dtype=np.float32)])
    return (lh @ mw.T)[:, :3].astype(np.float32, copy=True)


def _build_bvh(ref_mesh_obj: bpy.types.Object) -> BVHTree:
    """Build a world-space BVHTree from the evaluated ref mesh."""
    deps     = bpy.context.evaluated_depsgraph_get()
    eval_obj = ref_mesh_obj.evaluated_get(deps)
    mesh     = eval_obj.to_mesh()
    mat      = eval_obj.matrix_world
    verts_w  = [mat @ v.co for v in mesh.vertices]
    polys    = [tuple(p.vertices) for p in mesh.polygons]
    bvh      = BVHTree.FromPolygons(verts_w, polys)
    eval_obj.to_mesh_clear()
    return bvh


def _arc_length(pts_3d: np.ndarray) -> float:
    """Sum of segment lengths for one strand."""
    return float(np.sum(np.linalg.norm(np.diff(pts_3d, axis=0), axis=1)))


def _ray_cast_bidir(bvh: BVHTree, p0: Vector, p1: Vector):
    """Ray cast from p0 toward p1; if that misses, try the reverse direction.

    Returns (hit_dist_from_p0, hit_loc) or (None, None).
    Bidirectional cast handles one-sided / back-face planes correctly.
    """
    d       = p1 - p0
    seg_len = d.length
    if seg_len < 1e-8:
        return None, None
    fwd = d.normalized()

    # Forward: p0 → p1
    loc, _, _, dist = bvh.ray_cast(p0, fwd, seg_len)
    if loc is not None:
        return dist, loc

    # Reverse: cast from p1 back toward p0 (catches back-face planes)
    loc_r, _, _, dist_r = bvh.ray_cast(p1, -fwd, seg_len)
    if loc_r is not None:
        return seg_len - dist_r, loc_r

    return None, None


# ------------------------------------------------------------------ #
# Public operations
# ------------------------------------------------------------------ #

def extend_length(curves_obj: bpy.types.Object, target_m: float) -> int:
    """Scale every strand from root so total arc-length = target_m.

    Works in local space (no mesh reference needed).
    Returns number of strands modified.
    """
    local = _read_local(curves_obj)
    n_c   = len(local) // _PPC
    mod   = 0
    for ci in range(n_c):
        b    = ci * _PPC
        root = local[b]
        cur  = _arc_length(local[b:b + _PPC])
        if cur < 1e-6:
            continue
        scale = target_m / cur
        for j in range(1, _PPC):
            local[b + j] = root + (local[b + j] - root) * scale
        mod += 1
    _write_local(curves_obj, local)
    return mod


def mesh_shrink(curves_obj: bpy.types.Object, ref_mesh_obj: bpy.types.Object) -> int:
    """Shrink each strand to its first intersection with ref_mesh.

    Uses EVALUATED world positions so the Surface Deform modifier is
    accounted for.  Segment-by-segment walk from root → tip; bidirectional
    ray cast so back-face planes are also caught.

    scale = arc_length_to_intersection / total_arc_length
    Applied to LOCAL positions (correct because scale is dimensionless).

    Returns number of strands shrunk.
    """
    bvh   = _build_bvh(ref_mesh_obj)
    local = _read_local(curves_obj)
    world = _read_world_eval(curves_obj)   # ← evaluated, not local-to-world
    n_c   = len(local) // _PPC
    shrunk = 0

    for ci in range(n_c):
        b    = ci * _PPC
        # Cumulative arc-lengths in evaluated world space
        arcs = np.zeros(_PPC, dtype=np.float64)
        for j in range(1, _PPC):
            arcs[j] = arcs[j - 1] + float(
                np.linalg.norm(world[b + j] - world[b + j - 1]))
        total = arcs[-1]
        if total < 1e-6:
            continue

        hit_arc = None
        for seg in range(_PPC - 1):
            p0 = Vector(world[b + seg    ].tolist())
            p1 = Vector(world[b + seg + 1].tolist())
            dist, _ = _ray_cast_bidir(bvh, p0, p1)
            if dist is not None:
                hit_arc = arcs[seg] + dist
                break

        if hit_arc is None or hit_arc >= total:
            continue  # strand never exits mesh, or tip already inside

        scale = hit_arc / total
        root  = local[b].copy()
        for j in range(1, _PPC):
            local[b + j] = root + (local[b + j] - root) * scale
        shrunk += 1

    _write_local(curves_obj, local)
    return shrunk


def mesh_extend(curves_obj: bpy.types.Object, ref_mesh_obj: bpy.types.Object) -> int:
    """Extend strands that do NOT yet reach the ref_mesh boundary.

    Algorithm
    ---------
    For each strand, cast a ray from ROOT in the ROOT→TIP direction,
    extended well beyond the current tip.

    - If the mesh intersection is BEYOND the current tip: extend to it.
    - If the mesh intersection is AT or BEFORE the current tip: skip
      (the strand already reaches or crosses the mesh — use Mesh Shrink).
    - No intersection: skip.

    Uses EVALUATED world positions for correct intersection with the
    Surface Deform modifier active.

    Returns number of strands extended.
    """
    bvh   = _build_bvh(ref_mesh_obj)
    local = _read_local(curves_obj)
    world = _read_world_eval(curves_obj)   # ← evaluated
    n_c   = len(local) // _PPC
    ext   = 0

    for ci in range(n_c):
        b      = ci * _PPC
        root_w = Vector(world[b          ].tolist())
        tip_w  = Vector(world[b + _PPC - 1].tolist())

        rtt     = tip_w - root_w
        rtt_len = rtt.length
        if rtt_len < 1e-6:
            continue
        rtt_dir = rtt.normalized()

        # Compute total arc length in evaluated space
        total_arc = 0.0
        for j in range(1, _PPC):
            total_arc += float(np.linalg.norm(world[b + j] - world[b + j - 1]))
        if total_arc < 1e-6:
            continue

        # Cast from root in root→tip direction, searching up to 2 m beyond tip
        search = rtt_len + 2.0
        loc, _, _, dist_f = bvh.ray_cast(root_w, rtt_dir, search)
        if loc is None:
            # Reverse direction: cast from beyond-tip back toward root
            far_pt = root_w + rtt_dir * search
            loc_r, _, _, dist_r = bvh.ray_cast(far_pt, -rtt_dir, search)
            if loc_r is not None:
                dist_f = search - dist_r
            else:
                continue  # no intersection at all

        if dist_f <= rtt_len:
            continue  # intersection is at or before tip → don't extend here

        # dist_f is the straight-line distance from root to intersection.
        # Scale so the tip reaches that point.
        # scale = dist_f / rtt_len  (straight-line ratio, same as arc-length ratio
        #                             for nearly-straight strands)
        scale = dist_f / rtt_len
        root_l = local[b].copy()
        for j in range(1, _PPC):
            local[b + j] = root_l + (local[b + j] - root_l) * scale
        ext += 1

    _write_local(curves_obj, local)
    return ext


def urchin_reset(curves_obj: bpy.types.Object) -> int:
    """Reset every strand to a straight line along root-normal direction.

    The root-normal is estimated from the follicle segment (point[1]-point[0]).
    Arc-length is preserved; points are redistributed at equal spacing.

    Returns number of strands reset.
    """
    local = _read_local(curves_obj)
    n_c   = len(local) // _PPC

    for ci in range(n_c):
        b         = ci * _PPC
        root      = local[b].copy()
        follicle  = local[b + 1]
        direction = follicle - root
        d_len     = float(np.linalg.norm(direction))
        if d_len < 1e-6:
            continue
        direction /= d_len

        arc_len = _arc_length(local[b:b + _PPC])
        seg     = arc_len / (_PPC - 1)
        for j in range(1, _PPC):
            local[b + j] = root + direction * (seg * j)

    _write_local(curves_obj, local)
    return n_c
