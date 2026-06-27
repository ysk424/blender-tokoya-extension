"""Plant straight hair from a grayscale texture painted on a head mesh."""
from __future__ import annotations

from array import array
import bisect
import math
import random

import bpy
from mathutils import Matrix, Vector


POINTS_PER_STRAND = 9
MIN_POINTS_PER_STRAND = 9
MAX_POINTS_PER_STRAND = 13
NATURAL_SPACING_RATIO = 1.22
COMMON_ROOT_SEGMENTS = 2
MIN_DARKNESS = 1.0 / 255.0


def points_per_strand_for_length(max_length_cm: float) -> int:
    """Choose one uniform strand point count from the requested max length."""
    return max(
        MIN_POINTS_PER_STRAND,
        min(
            MAX_POINTS_PER_STRAND,
            MIN_POINTS_PER_STRAND + math.floor((max_length_cm - 20.0) / 10.0),
        ),
    )


def natural_distances(length_m: float, max_length_m: float, pps: int) -> list[float]:
    """Return monotonic distances from root for one strand.

    The first two segments use the max-length root zone when the strand is
    long enough. Shorter gray-mask or Mesh Shrink strands keep that common
    root zone, then distribute their remaining tail evenly.
    """
    if pps < 2:
        return [0.0]
    length_m = max(0.0, float(length_m))
    max_length_m = max(length_m, float(max_length_m), 1.0e-9)
    segments = [NATURAL_SPACING_RATIO ** i for i in range(pps - 1)]
    total = sum(segments)
    max_distances = [0.0]
    acc = 0.0
    for segment in segments:
        acc += segment
        max_distances.append(max_length_m * acc / total)

    root_index = min(COMMON_ROOT_SEGMENTS, pps - 1)
    root_zone = max_distances[root_index]
    if length_m >= max_length_m - 1.0e-9:
        return max_distances
    if length_m <= root_zone + 1.0e-9:
        scale = length_m / root_zone if root_zone > 1.0e-9 else 0.0
        return [min(length_m, distance * scale) for distance in max_distances]

    distances = [0.0] * pps
    for index in range(root_index + 1):
        distances[index] = max_distances[index]

    remaining_points = pps - root_index - 1
    if remaining_points > 0:
        step = (length_m - root_zone) / remaining_points
        for offset in range(1, remaining_points + 1):
            distances[root_index + offset] = root_zone + step * offset
    return distances


def create_head_mask(
    surface_obj: bpy.types.Object,
    image_size: int = 2048,
    offset_m: float = 0.001,
) -> bpy.types.Object:
    """Create a scale-1 paint shell from the surface's Head material region."""
    if surface_obj is None or surface_obj.type != "MESH":
        raise RuntimeError("Curves surface must be a mesh")
    if bpy.data.objects.get("Tokoya_HairMask") is not None:
        raise RuntimeError("Tokoya_HairMask already exists")

    material_index = next(
        (
            index
            for index, slot in enumerate(surface_obj.material_slots)
            if slot.material is not None
            and "skin_head" in slot.material.name.lower()
        ),
        None,
    )
    if material_index is None:
        raise RuntimeError("Could not find a material containing 'Skin_Head'")

    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated_obj = surface_obj.evaluated_get(depsgraph)
    evaluated_mesh = evaluated_obj.to_mesh(
        preserve_all_data_layers=True, depsgraph=depsgraph
    )
    try:
        uv_source = (
            evaluated_mesh.uv_layers.get("Channel0")
            or evaluated_mesh.uv_layers.active
        )
        if uv_source is None:
            raise RuntimeError("Head surface has no UV map")

        polygons = [
            polygon
            for polygon in evaluated_mesh.polygons
            if polygon.material_index == material_index
        ]
        if not polygons:
            raise RuntimeError("Head material contains no polygons")

        used_vertices = sorted(
            {vertex_index for polygon in polygons for vertex_index in polygon.vertices}
        )
        remap = {
            source_index: target_index
            for target_index, source_index in enumerate(used_vertices)
        }
        world = evaluated_obj.matrix_world
        normal_matrix = world.to_3x3().inverted().transposed()
        vertices = []
        for source_index in used_vertices:
            source_vertex = evaluated_mesh.vertices[source_index]
            position = world @ source_vertex.co
            normal = (normal_matrix @ source_vertex.normal).normalized()
            vertices.append(tuple(position + normal * offset_m))
        faces = [
            [remap[vertex_index] for vertex_index in polygon.vertices]
            for polygon in polygons
        ]

        mesh = bpy.data.meshes.new("Tokoya_HairMask_Mesh")
        mesh.from_pydata(vertices, [], faces)
        mesh.update()
        uv_target = mesh.uv_layers.new(name=uv_source.name)
        uv_values = []
        for polygon in polygons:
            for loop_index in polygon.loop_indices:
                uv = uv_source.data[loop_index].uv
                uv_values.extend((uv.x, uv.y))
        uv_target.data.foreach_set("uv", uv_values)
    finally:
        evaluated_obj.to_mesh_clear()

    mask_obj = bpy.data.objects.new("Tokoya_HairMask", mesh)
    bpy.context.collection.objects.link(mask_obj)
    mask_obj.matrix_world = Matrix.Identity(4)
    mask_obj["tokoya_mask_semantics"] = "WHITE=0 cm, BLACK=max length"
    mask_obj["tokoya_surface_offset_m"] = offset_m

    image = bpy.data.images.new(
        "Tokoya_HairMask_White",
        width=image_size,
        height=image_size,
        alpha=False,
        float_buffer=False,
    )
    image.generated_type = "BLANK"
    image.generated_color = (1.0, 1.0, 1.0, 1.0)
    image.colorspace_settings.name = "Non-Color"

    material = bpy.data.materials.new("Tokoya_HairMask_Material")
    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    shader = nodes.new("ShaderNodeBsdfPrincipled")
    texture = nodes.new("ShaderNodeTexImage")
    texture.image = image
    texture.interpolation = "Linear"
    texture.select = True
    nodes.active = texture
    shader.inputs["Roughness"].default_value = 0.8
    links.new(texture.outputs["Color"], shader.inputs["Base Color"])
    links.new(shader.outputs["BSDF"], output.inputs["Surface"])
    mesh.materials.append(material)

    return mask_obj


def _find_single_curves() -> bpy.types.Object:
    objects = [obj for obj in bpy.data.objects if obj.type == "CURVES"]
    if len(objects) != 1:
        raise RuntimeError(f"Expected exactly 1 Curves object, found {len(objects)}")
    return objects[0]


def remove_all_hair(curves_obj: bpy.types.Object) -> int:
    """Clear strands by replacing only the Curves data block."""
    old = curves_obj.data
    removed = len(old.curves)
    new = bpy.data.hair_curves.new(old.name)
    new.surface = old.surface
    new.surface_uv_map = old.surface_uv_map
    for material in old.materials:
        new.materials.append(material)
    curves_obj.data = new
    if old.users == 0:
        bpy.data.hair_curves.remove(old)
    return removed


def _find_mask_image(mask_obj: bpy.types.Object) -> bpy.types.Image:
    for slot in mask_obj.material_slots:
        material = slot.material
        if material is None or not material.use_nodes:
            continue
        for node in material.node_tree.nodes:
            if node.type == "TEX_IMAGE" and node.image is not None:
                return node.image
    raise RuntimeError("Mask mesh has no Image Texture node")


def _apply_mesh_scale(mask_obj: bpy.types.Object) -> None:
    """Apply object scale to mesh data without changing its world appearance."""
    scale = mask_obj.scale
    if all(abs(value - 1.0) < 1.0e-6 for value in scale):
        return
    if mask_obj.data.users > 1:
        mask_obj.data = mask_obj.data.copy()
    mask_obj.data.transform(Matrix.Diagonal((scale.x, scale.y, scale.z, 1.0)))
    mask_obj.scale = (1.0, 1.0, 1.0)
    mask_obj.data.update()


def _prepare_empty_curves(curves_obj: bpy.types.Object) -> None:
    if len(curves_obj.data.curves) or len(curves_obj.data.points):
        raise RuntimeError("Curves object must be empty before Mask Plant")

    # Hair objects created on a CC character inherit the armature's 0.01 scale.
    # Generated coordinates are metres in world space, so use an identity object.
    curves_obj.parent = None
    curves_obj.matrix_world = Matrix.Identity(4)
    curves_obj.scale = (1.0, 1.0, 1.0)


def _read_pixels(image: bpy.types.Image) -> tuple[array, int, int]:
    width, height = image.size
    if width <= 0 or height <= 0:
        raise RuntimeError("Mask image has no pixel data")
    pixels = array("f", [0.0]) * (width * height * 4)
    image.pixels.foreach_get(pixels)
    return pixels, width, height


def _darkness(pixels: array, width: int, height: int, uv: Vector) -> float:
    u = min(1.0, max(0.0, uv.x))
    v = min(1.0, max(0.0, uv.y))
    x = min(width - 1, max(0, round(u * (width - 1))))
    y = min(height - 1, max(0, round(v * (height - 1))))
    index = (y * width + x) * 4
    luminance = (pixels[index] + pixels[index + 1] + pixels[index + 2]) / 3.0
    return min(1.0, max(0.0, 1.0 - luminance))


def plant_mask_hair(
    mask_obj: bpy.types.Object,
    strand_count: int,
    max_length_cm: float,
    seed: int = 20260620,
) -> dict:
    """Fill the non-white mask region with fixed-count, variable-length hair.

    White produces zero length, black produces *max_length_cm*, and gray is
    linearly interpolated. Root positions are uniform by painted surface area;
    grayscale controls length only.
    """
    if mask_obj.type != "MESH":
        raise RuntimeError("Ref Object must be the painted MESH")
    if strand_count < 1:
        raise ValueError("Strand count must be at least 1")
    if max_length_cm <= 0.0:
        raise ValueError("Maximum length must be positive")

    curves_obj = _find_single_curves()
    _prepare_empty_curves(curves_obj)
    _apply_mesh_scale(mask_obj)

    mesh = mask_obj.data
    uv_layer = mesh.uv_layers.active
    if uv_layer is None:
        raise RuntimeError("Mask mesh has no active UV map")
    image = _find_mask_image(mask_obj)
    pixels, width, height = _read_pixels(image)

    mesh.calc_loop_triangles()
    world = mask_obj.matrix_world
    triangles = []
    cumulative_areas = []
    total_area = 0.0

    for triangle in mesh.loop_triangles:
        loop_indices = triangle.loops
        vertices = [world @ mesh.vertices[index].co for index in triangle.vertices]
        uvs = [Vector(uv_layer.data[index].uv) for index in loop_indices]
        area = ((vertices[1] - vertices[0]).cross(vertices[2] - vertices[0])).length * 0.5
        if area <= 1.0e-14:
            continue
        centroid_uv = (uvs[0] + uvs[1] + uvs[2]) / 3.0
        max_darkness = max(
            _darkness(pixels, width, height, uvs[0]),
            _darkness(pixels, width, height, uvs[1]),
            _darkness(pixels, width, height, uvs[2]),
            _darkness(pixels, width, height, centroid_uv),
        )
        if max_darkness < MIN_DARKNESS:
            continue
        total_area += area
        triangles.append((vertices, uvs))
        cumulative_areas.append(total_area)

    if not triangles:
        raise RuntimeError("No painted (non-white) mask region found")

    rng = random.Random(seed)
    roots = []
    normals = []
    lengths = []
    root_uvs = []
    max_attempts = strand_count * 100
    attempts = 0
    max_length_m = max_length_cm / 100.0

    while len(roots) < strand_count and attempts < max_attempts:
        attempts += 1
        triangle_index = bisect.bisect_left(
            cumulative_areas, rng.random() * total_area
        )
        vertices, uvs = triangles[min(triangle_index, len(triangles) - 1)]

        a = rng.random()
        b = rng.random()
        if a + b > 1.0:
            a = 1.0 - a
            b = 1.0 - b
        c = 1.0 - a - b

        uv = uvs[0] * c + uvs[1] * a + uvs[2] * b
        darkness = _darkness(pixels, width, height, uv)
        if darkness < MIN_DARKNESS:
            continue

        root = vertices[0] * c + vertices[1] * a + vertices[2] * b
        normal = (vertices[1] - vertices[0]).cross(vertices[2] - vertices[0])
        if normal.length_squared == 0.0:
            continue

        roots.append(root)
        normals.append(normal.normalized())
        lengths.append(max_length_m * darkness)
        root_uvs.append(uv)

    if len(roots) != strand_count:
        raise RuntimeError(
            f"Could only place {len(roots)} of {strand_count} strands"
        )

    points_per_strand = points_per_strand_for_length(max_length_cm)

    curves = curves_obj.data
    curves.add_curves([points_per_strand] * strand_count)
    position = curves.attributes["position"]
    if "surface_uv_coordinate" not in curves.attributes:
        curves.attributes.new(
            name="surface_uv_coordinate", type="FLOAT2", domain="CURVE"
        )
    surface_uv = curves.attributes["surface_uv_coordinate"]

    for curve_index, (root, normal, length, uv) in enumerate(
        zip(roots, normals, lengths, root_uvs)
    ):
        first = curve_index * points_per_strand
        distances = natural_distances(length, max_length_m, points_per_strand)
        for point_index, distance in enumerate(distances):
            position.data[first + point_index].vector = root + normal * distance
        surface_uv.data[curve_index].vector = uv

    curves.update_tag()
    bpy.context.view_layer.update()

    lengths_cm = [length * 100.0 for length in lengths]
    return {
        "n_added": strand_count,
        "total_points": strand_count * points_per_strand,
        "points_per_strand": points_per_strand,
        "max_length_cm": max(lengths_cm),
        "mean_length_cm": sum(lengths_cm) / len(lengths_cm),
        "mask_image": image.name,
    }
