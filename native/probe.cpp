// Phase 2B/4A/4B/4C/5A/5B/5C/5D placeholder module. Module name,
// function names, and phase attribute are experimental and will
// change before any real solver wiring.
//
// Phase history of this file:
//   4A: describe_curves           (metadata round-trip only)
//   4B: probe_position_buffer     (read-only float32 buffer ingest)
//   4C: deform_position_buffer    (C++ allocates new result, writes
//                                  deterministic deformation, returns
//                                  as py::bytes)
//   5A: physx_probe_open/status/close   (PhysX 5 CPU-only lifecycle;
//                                        no simulation, no rigid bodies,
//                                        no collision, no GPU)
//   5B: physx_probe_step          (empty-Scene simulate(dt)/fetchResults;
//                                  still no rigid bodies, no collision,
//                                  no Curves, no GPU)
//   5C: physx_probe_create_rigid_scene / get_actor_pose
//                                 (PhysX-internal ground plane + dynamic
//                                  sphere falling under gravity; still
//                                  no Curves, no collision body read,
//                                  no SolverInterface, no GPU)
//   5D: physx_probe_create_mesh_scene
//                                 (C++-internal triangle mesh + dynamic
//                                  sphere collides at y=9; no Blender
//                                  mesh access, no Curves, no GPU)
#include <pybind11/pybind11.h>

#include <PxPhysicsAPI.h>
#include <cooking/PxCooking.h>

#include <cstddef>
#include <exception>
#include <string>
#include <vector>

namespace py = pybind11;
using namespace physx;

int add(int a, int b) { return a + b; }

py::dict describe_curves(
    const std::string& object_name,
    unsigned int       strand_count,
    unsigned int       points_per_strand,
    unsigned int       point_count,
    unsigned int       floats_per_frame,
    int                frame_current,
    const std::string& attribute_name,
    const std::string& attribute_domain,
    const std::string& data_type)
{
    const bool consistent =
        (point_count == strand_count * points_per_strand) &&
        (floats_per_frame == point_count * 3u);

    const bool attribute_ok =
        (attribute_name   == "position") &&
        (attribute_domain == "POINT")    &&
        (data_type        == "FLOAT_VECTOR");

    const bool accepted = consistent && attribute_ok;

    py::dict d;
    d["accepted"]          = accepted;
    d["object_name_echo"]  = object_name;
    d["strand_count"]      = strand_count;
    d["points_per_strand"] = points_per_strand;
    d["point_count"]       = point_count;
    d["floats_per_frame"]  = floats_per_frame;
    d["frame_current"]     = frame_current;
    d["consistent"]        = consistent;
    d["attribute_ok"]      = attribute_ok;

    std::string msg;
    if (accepted) {
        msg = "metadata consistent; ready for buffer round-trip (Phase 4B)";
    } else if (!consistent) {
        msg = "metadata inconsistent: arithmetic mismatch";
    } else {
        msg = "attribute fingerprint mismatch: expected (position, POINT, FLOAT_VECTOR)";
    }
    d["message"] = msg;

    return d;
}

py::dict probe_position_buffer(
    unsigned int expected_point_count,
    unsigned int expected_float_count,
    int          frame_current,
    py::buffer   buf)
{
    py::buffer_info info = buf.request(/*writable=*/false);

    const bool itemsize_ok  = (info.itemsize == static_cast<py::ssize_t>(sizeof(float)));
    const bool format_ok    = (info.format == py::format_descriptor<float>::format());
    const bool size_ok      = (info.size == static_cast<py::ssize_t>(expected_float_count));
    const bool count_consistent =
        (expected_float_count == expected_point_count * 3u);

    const bool accepted = itemsize_ok && format_ok && size_ok && count_consistent;

    py::dict d;
    d["accepted"]             = accepted;
    d["itemsize"]             = info.itemsize;
    d["itemsize_ok"]          = itemsize_ok;
    d["format"]               = info.format;
    d["format_ok"]            = format_ok;
    d["buffer_size_floats"]   = info.size;
    d["size_ok"]              = size_ok;
    d["expected_float_count"] = expected_float_count;
    d["expected_point_count"] = expected_point_count;
    d["frame_current"]        = frame_current;
    d["consistent"]           = count_consistent;
    d["ndim"]                 = info.ndim;

    if (!accepted) {
        d["message"] = "buffer validation failed";
        return d;
    }

    const float* p = static_cast<const float*>(info.ptr);
    const std::size_t n_floats = static_cast<std::size_t>(info.size);
    const std::size_t n_points = n_floats / 3u;

    double min_x = p[0], min_y = p[1], min_z = p[2];
    double max_x = p[0], max_y = p[1], max_z = p[2];
    double sum_x = 0.0, sum_y = 0.0, sum_z = 0.0;

    for (std::size_t i = 0; i < n_points; ++i) {
        const double x = p[i * 3u + 0];
        const double y = p[i * 3u + 1];
        const double z = p[i * 3u + 2];
        if (x < min_x) min_x = x;
        if (x > max_x) max_x = x;
        if (y < min_y) min_y = y;
        if (y > max_y) max_y = y;
        if (z < min_z) min_z = z;
        if (z > max_z) max_z = z;
        sum_x += x;
        sum_y += y;
        sum_z += z;
    }

    const double avg_x = sum_x / static_cast<double>(n_points);
    const double avg_y = sum_y / static_cast<double>(n_points);
    const double avg_z = sum_z / static_cast<double>(n_points);
    const double checksum = sum_x + sum_y + sum_z;

    d["point_count_actual"] = static_cast<unsigned long long>(n_points);
    d["float_count_actual"] = static_cast<unsigned long long>(n_floats);
    d["first_vec3"]  = py::make_tuple(
        static_cast<double>(p[0]),
        static_cast<double>(p[1]),
        static_cast<double>(p[2]));
    d["last_vec3"]   = py::make_tuple(
        static_cast<double>(p[n_floats - 3u]),
        static_cast<double>(p[n_floats - 2u]),
        static_cast<double>(p[n_floats - 1u]));
    d["min_xyz"]     = py::make_tuple(min_x, min_y, min_z);
    d["max_xyz"]     = py::make_tuple(max_x, max_y, max_z);
    d["sum_xyz"]     = py::make_tuple(sum_x, sum_y, sum_z);
    d["average_xyz"] = py::make_tuple(avg_x, avg_y, avg_z);
    d["checksum_xyz_sum"] = checksum;
    d["message"]     = "buffer accepted and read; pointer not retained";

    return d;
}

py::dict deform_position_buffer(
    unsigned int expected_point_count,
    unsigned int expected_float_count,
    unsigned int points_per_strand,
    int          frame_current,
    float        amplitude,
    py::buffer   input_buf)
{
    py::buffer_info info = input_buf.request(/*writable=*/false);

    const bool itemsize_ok = (info.itemsize == static_cast<py::ssize_t>(sizeof(float)));
    const bool format_ok   = (info.format == py::format_descriptor<float>::format());
    const bool size_ok     = (info.size == static_cast<py::ssize_t>(expected_float_count));
    const bool count_consistent =
        (expected_float_count == expected_point_count * 3u);
    const bool pps_ok =
        (points_per_strand >= 2u) &&
        (expected_point_count % points_per_strand == 0u);

    const bool accepted = itemsize_ok && format_ok && size_ok
                       && count_consistent && pps_ok;

    py::dict d;
    d["accepted"]          = accepted;
    d["amplitude"]         = amplitude;
    d["points_per_strand"] = points_per_strand;
    d["frame_current"]     = frame_current;
    d["float_count"]       = info.size;
    d["point_count"]       = info.size / 3;
    d["itemsize_ok"]       = itemsize_ok;
    d["format_ok"]         = format_ok;
    d["size_ok"]           = size_ok;
    d["consistent"]        = count_consistent;
    d["pps_ok"]            = pps_ok;

    if (!accepted) {
        d["message"] = "input validation failed (itemsize/format/size/consistency/pps)";
        return d;
    }

    const float* in_p = static_cast<const float*>(info.ptr);
    const std::size_t n_floats = static_cast<std::size_t>(info.size);
    const std::size_t n_points = n_floats / 3u;
    const std::size_t pps      = static_cast<std::size_t>(points_per_strand);
    const float       inv_max  = 1.0f / static_cast<float>(pps - 1u);
    const std::size_t tip_idx  = pps - 1u;

    const double f0_in[3]  = { in_p[0], in_p[1], in_p[2] };
    const double tip_in[3] = { in_p[tip_idx * 3u + 0],
                               in_p[tip_idx * 3u + 1],
                               in_p[tip_idx * 3u + 2] };

    std::vector<char> result_bytes(n_floats * sizeof(float));
    float* out_p = reinterpret_cast<float*>(result_bytes.data());

    double cs_before = 0.0;
    double cs_after  = 0.0;

    for (std::size_t i = 0; i < n_points; ++i) {
        const std::size_t pps_idx = i % pps;
        const float factor = static_cast<float>(pps_idx) * inv_max;
        const float dz     = factor * amplitude;

        const float x = in_p[i * 3u + 0];
        const float y = in_p[i * 3u + 1];
        const float z = in_p[i * 3u + 2];

        out_p[i * 3u + 0] = x;
        out_p[i * 3u + 1] = y;
        out_p[i * 3u + 2] = z + dz;

        cs_before += static_cast<double>(x) + static_cast<double>(y) + static_cast<double>(z);
        cs_after  += static_cast<double>(out_p[i * 3u + 0])
                  +  static_cast<double>(out_p[i * 3u + 1])
                  +  static_cast<double>(out_p[i * 3u + 2]);
    }

    const double f0_out[3]  = { out_p[0], out_p[1], out_p[2] };
    const double tip_out[3] = { out_p[tip_idx * 3u + 0],
                                out_p[tip_idx * 3u + 1],
                                out_p[tip_idx * 3u + 2] };

    d["first_vec3_before"] = py::make_tuple(f0_in[0],  f0_in[1],  f0_in[2]);
    d["first_vec3_after"]  = py::make_tuple(f0_out[0], f0_out[1], f0_out[2]);
    d["tip_vec3_before"]   = py::make_tuple(tip_in[0], tip_in[1], tip_in[2]);
    d["tip_vec3_after"]    = py::make_tuple(tip_out[0], tip_out[1], tip_out[2]);
    d["checksum_before"]   = cs_before;
    d["checksum_after"]    = cs_after;
    d["checksum_delta"]    = cs_after - cs_before;
    d["message"]           = "deformation applied to new result buffer; input untouched";

    d["result_buffer"] = py::bytes(result_bytes.data(),
                                   static_cast<py::ssize_t>(result_bytes.size()));

    return d;
}

// ---------------------------------------------------------------------- //
// Phase 5A: PhysX lifecycle probe
//
// CPU only. No GPU dispatcher, no CUDA context, no simulation step, no
// rigid actors, no collision data, no Curves access. The PhysX state is
// confined to this translation unit and exists only through the three
// functions below.
// ---------------------------------------------------------------------- //

namespace {

PxDefaultAllocator       g_allocator;
PxDefaultErrorCallback   g_error_callback;

PxFoundation*            g_foundation  = nullptr;
PxPhysics*               g_physics     = nullptr;
PxDefaultCpuDispatcher*  g_dispatcher  = nullptr;
PxScene*                 g_scene       = nullptr;
PxMaterial*              g_material    = nullptr;

// Phase 5B: step probe state. Reset to zero in physx_probe_close().
unsigned long long       g_step_count  = 0ULL;
float                    g_last_dt     = 0.0f;

// Phase 5C: minimal rigid scene actors. Owned by the PxScene once added;
// released in physx_probe_close() before scene teardown.
PxRigidStatic*           g_ground_static  = nullptr;
PxRigidDynamic*          g_dynamic_actor  = nullptr;

// Phase 5D: triangle-mesh scene state. g_triangle_mesh is reference
// counted by PhysX; the mesh shape attached to g_ground_mesh_static
// holds a reference, so the mesh must be released after that actor.
PxRigidStatic*           g_ground_mesh_static = nullptr;
PxTriangleMesh*          g_triangle_mesh      = nullptr;

}  // anonymous namespace

py::dict physx_probe_open()
{
    py::dict d;

    if (g_foundation != nullptr) {
        d["accepted"]       = true;
        d["already_open"]   = true;
        d["opened"]         = true;
        d["message"]        = "PhysX context already open";
        return d;
    }

    g_foundation = PxCreateFoundation(PX_PHYSICS_VERSION, g_allocator, g_error_callback);
    if (g_foundation == nullptr) {
        d["accepted"] = false;
        d["opened"]   = false;
        d["message"]  = "PxCreateFoundation failed";
        return d;
    }

    g_physics = PxCreatePhysics(
        PX_PHYSICS_VERSION,
        *g_foundation,
        PxTolerancesScale(),
        /*trackOutstandingAllocations*/ false,
        /*pvd*/ nullptr);
    if (g_physics == nullptr) {
        g_foundation->release();
        g_foundation = nullptr;
        d["accepted"] = false;
        d["opened"]   = false;
        d["message"]  = "PxCreatePhysics failed";
        return d;
    }

    g_dispatcher = PxDefaultCpuDispatcherCreate(/*numThreads*/ 2);
    if (g_dispatcher == nullptr) {
        g_physics->release();    g_physics = nullptr;
        g_foundation->release(); g_foundation = nullptr;
        d["accepted"] = false;
        d["opened"]   = false;
        d["message"]  = "PxDefaultCpuDispatcherCreate failed";
        return d;
    }

    PxSceneDesc scene_desc(g_physics->getTolerancesScale());
    scene_desc.gravity        = PxVec3(0.0f, -9.81f, 0.0f);
    scene_desc.cpuDispatcher  = g_dispatcher;
    scene_desc.filterShader   = PxDefaultSimulationFilterShader;
    g_scene = g_physics->createScene(scene_desc);
    if (g_scene == nullptr) {
        g_dispatcher->release(); g_dispatcher = nullptr;
        g_physics->release();    g_physics    = nullptr;
        g_foundation->release(); g_foundation = nullptr;
        d["accepted"] = false;
        d["opened"]   = false;
        d["message"]  = "createScene failed";
        return d;
    }

    g_material = g_physics->createMaterial(0.5f, 0.5f, 0.6f);
    // material is optional for open/close probe; ignore if it fails

    d["accepted"]      = true;
    d["already_open"]  = false;
    d["opened"]        = true;
    d["px_version"]    = static_cast<unsigned int>(PX_PHYSICS_VERSION);
    d["px_version_str"] = std::string("major=") + std::to_string(PX_PHYSICS_VERSION_MAJOR)
                        + " minor=" + std::to_string(PX_PHYSICS_VERSION_MINOR)
                        + " bugfix=" + std::to_string(PX_PHYSICS_VERSION_BUGFIX);
    d["gpu_enabled"]   = false;
    d["message"]       = "PhysX context opened (CPU only, no simulation, no rigid bodies)";
    return d;
}

py::dict physx_probe_status()
{
    const bool has_foundation = (g_foundation != nullptr);
    const bool has_physics    = (g_physics    != nullptr);
    const bool has_dispatcher = (g_dispatcher != nullptr);
    const bool has_scene      = (g_scene      != nullptr);
    const bool has_material   = (g_material   != nullptr);
    const bool opened         = has_foundation;

    const bool has_dynamic_actor    = (g_dynamic_actor != nullptr);
    const bool has_ground_static    = (g_ground_static != nullptr);
    const bool has_ground_mesh      = (g_ground_mesh_static != nullptr);
    const bool has_triangle_mesh    = (g_triangle_mesh != nullptr);
    const bool has_rigid_scene      = has_dynamic_actor && has_ground_static;
    const bool has_mesh_scene       = has_dynamic_actor && has_ground_mesh;
    const int  static_actor_count   = (has_ground_static ? 1 : 0)
                                    + (has_ground_mesh   ? 1 : 0);

    py::dict d;
    // Phase 5B/5C/5D status surface.
    d["opened"]              = opened;
    d["state"]               = opened ? "opened" : "closed";
    d["step_count"]          = g_step_count;
    d["last_dt"]             = g_last_dt;
    d["gpu_enabled"]         = false;
    d["has_foundation"]      = has_foundation;
    d["has_physics"]         = has_physics;
    d["has_dispatcher"]      = has_dispatcher;
    d["has_scene"]           = has_scene;
    d["has_material"]        = has_material;
    d["has_rigid_scene"]     = has_rigid_scene;
    d["has_mesh_scene"]      = has_mesh_scene;
    d["has_triangle_mesh"]   = has_triangle_mesh;
    d["dynamic_actor_count"] = has_dynamic_actor ? 1 : 0;
    d["static_actor_count"]  = static_actor_count;
    d["message"]             = opened
        ? (has_mesh_scene
               ? "PhysX context open with mesh scene (triangle mesh + dynamic sphere)"
               : (has_rigid_scene
                      ? "PhysX context open with rigid scene (ground plane + dynamic sphere)"
                      : "PhysX context open (empty scene; no rigid bodies)"))
        : "PhysX context closed";

    // Phase 5A back-compat fields (kept so older probe scripts keep working).
    d["foundation_ptr_nonnull"] = has_foundation;
    d["physics_ptr_nonnull"]    = has_physics;
    d["dispatcher_ptr_nonnull"] = has_dispatcher;
    d["scene_ptr_nonnull"]      = has_scene;
    d["material_ptr_nonnull"]   = has_material;
    return d;
}

// Phase 5C: dynamic sphere initial position and geometry. PhysX-internal
// coordinates only; no Blender mapping is implied here.
namespace {
constexpr float  kDynamicRadius      = 0.5f;
constexpr float  kDynamicInitialY    = 10.0f;
constexpr float  kDynamicDensity     = 1.0f;
}  // anonymous namespace

// Phase 5C: create the minimal rigid scene inside the already-open
// PxScene: one infinite static ground plane (normal +Y at y=0) and one
// dynamic sphere at (0, 10, 0). Gravity comes from the scene that
// physx_probe_open() configured, i.e. (0, -9.81, 0). No Blender data is
// touched.
py::dict physx_probe_create_rigid_scene()
{
    py::dict d;
    const bool is_open =
        (g_foundation != nullptr) &&
        (g_physics    != nullptr) &&
        (g_scene      != nullptr) &&
        (g_material   != nullptr);

    if (!is_open) {
        d["accepted"]        = false;
        d["has_rigid_scene"] = false;
        d["message"]         = "rejected: PhysX context not fully open (need foundation/physics/scene/material)";
        return d;
    }

    if (g_ground_mesh_static != nullptr || g_triangle_mesh != nullptr) {
        d["accepted"]        = false;
        d["has_rigid_scene"] = false;
        d["message"]         = "rejected: a mesh scene exists (close first to switch back to plane scene)";
        return d;
    }

    if (g_dynamic_actor != nullptr || g_ground_static != nullptr) {
        const PxVec3 g = g_scene->getGravity();
        d["accepted"]            = true;
        d["already_created"]     = true;
        d["has_rigid_scene"]     = true;
        d["dynamic_actor_count"] = (g_dynamic_actor != nullptr) ? 1 : 0;
        d["static_actor_count"]  = (g_ground_static != nullptr) ? 1 : 0;
        d["gravity"]             = py::make_tuple(g.x, g.y, g.z);
        d["gravity_axis"]        = "-Y";
        d["message"]             = "rigid scene already created (no-op)";
        return d;
    }

    // Ground plane: n=(0,1,0), d=0 -> y=0
    g_ground_static = PxCreatePlane(*g_physics, PxPlane(0.0f, 1.0f, 0.0f, 0.0f), *g_material);
    if (g_ground_static == nullptr) {
        d["accepted"]        = false;
        d["has_rigid_scene"] = false;
        d["message"]         = "PxCreatePlane failed";
        return d;
    }
    g_scene->addActor(*g_ground_static);

    // Dynamic sphere at (0, 10, 0). Damping zero so free fall is
    // analytically predictable in the test.
    const PxTransform dyn_pose(PxVec3(0.0f, kDynamicInitialY, 0.0f));
    g_dynamic_actor = PxCreateDynamic(
        *g_physics, dyn_pose,
        PxSphereGeometry(kDynamicRadius),
        *g_material, kDynamicDensity);
    if (g_dynamic_actor == nullptr) {
        g_ground_static->release();
        g_ground_static = nullptr;
        d["accepted"]        = false;
        d["has_rigid_scene"] = false;
        d["message"]         = "PxCreateDynamic failed; ground rolled back";
        return d;
    }
    g_dynamic_actor->setLinearDamping(0.0f);
    g_dynamic_actor->setAngularDamping(0.0f);
    g_scene->addActor(*g_dynamic_actor);

    const PxVec3 g = g_scene->getGravity();

    d["accepted"]                 = true;
    d["already_created"]          = false;
    d["has_rigid_scene"]          = true;
    d["dynamic_actor_count"]      = 1;
    d["static_actor_count"]       = 1;
    d["dynamic_geometry"]         = std::string("PxSphereGeometry(radius=0.5)");
    d["dynamic_initial_position"] = py::make_tuple(dyn_pose.p.x, dyn_pose.p.y, dyn_pose.p.z);
    d["dynamic_density"]          = kDynamicDensity;
    d["ground_plane"]             = std::string("PxPlane(n=(0,1,0), d=0)");
    d["gravity"]                  = py::make_tuple(g.x, g.y, g.z);
    d["gravity_axis"]             = "-Y";
    d["message"]                  = "rigid scene created (ground plane + dynamic sphere @ y=10)";
    return d;
}

// Phase 5D: build a 4-vertex / 2-triangle horizontal mesh at y=9 (square
// from x,z in [-5, +5]) via PhysX cooking, and a dynamic sphere @ y=10.
// The mesh is single-sided; vertex winding is chosen so the surface
// normal points +Y, facing the falling sphere.
//
// Spec triangles (0,1,2) and (0,2,3) produce -Y normals under PhysX's
// right-hand rule (n = (v1-v0) x (v2-v0)); winding is flipped here to
// (0,2,1) and (0,3,2) for +Y normals.
py::dict physx_probe_create_mesh_scene()
{
    py::dict d;
    const bool is_open =
        (g_foundation != nullptr) &&
        (g_physics    != nullptr) &&
        (g_scene      != nullptr) &&
        (g_material   != nullptr);

    if (!is_open) {
        d["accepted"]       = false;
        d["has_mesh_scene"] = false;
        d["message"]        = "rejected: PhysX context not fully open (need foundation/physics/scene/material)";
        return d;
    }

    // Own mesh scene already present -> idempotent no-op. This must be
    // checked before the cross-conflict guard below, because a mesh scene
    // also owns g_dynamic_actor (shared with the Phase 5C plane path).
    if (g_ground_mesh_static != nullptr || g_triangle_mesh != nullptr) {
        const PxVec3 g = g_scene->getGravity();
        d["accepted"]            = true;
        d["already_created"]     = true;
        d["has_mesh_scene"]      = true;
        d["dynamic_actor_count"] = (g_dynamic_actor != nullptr) ? 1 : 0;
        d["static_actor_count"]  = (g_ground_mesh_static != nullptr) ? 1 : 0;
        d["gravity"]             = py::make_tuple(g.x, g.y, g.z);
        d["gravity_axis"]        = "-Y";
        d["message"]             = "mesh scene already created (no-op)";
        return d;
    }

    // No mesh actor of our own, but a plane rigid scene is up -> reject.
    if (g_dynamic_actor != nullptr || g_ground_static != nullptr) {
        d["accepted"]       = false;
        d["has_mesh_scene"] = false;
        d["message"]        = "rejected: a plane rigid scene exists (close first to switch to mesh scene)";
        return d;
    }

    // ------------------------------------------------------------------ //
    // Triangle mesh: 4 verts (square at y=9, side=10), 2 tris (+Y normal).
    // ------------------------------------------------------------------ //
    static const PxVec3 mesh_verts[4] = {
        PxVec3(-5.0f, 9.0f, -5.0f),  // v0
        PxVec3( 5.0f, 9.0f, -5.0f),  // v1
        PxVec3( 5.0f, 9.0f,  5.0f),  // v2
        PxVec3(-5.0f, 9.0f,  5.0f),  // v3
    };
    static const PxU32 mesh_indices[6] = {
        0u, 2u, 1u,   // t0: +Y normal
        0u, 3u, 2u,   // t1: +Y normal
    };

    PxTriangleMeshDesc mesh_desc;
    mesh_desc.points.count     = 4u;
    mesh_desc.points.stride    = sizeof(PxVec3);
    mesh_desc.points.data      = mesh_verts;
    mesh_desc.triangles.count  = 2u;
    mesh_desc.triangles.stride = 3u * sizeof(PxU32);
    mesh_desc.triangles.data   = mesh_indices;

    PxCookingParams cook_params(g_physics->getTolerancesScale());
    g_triangle_mesh = PxCreateTriangleMesh(
        cook_params, mesh_desc, g_physics->getPhysicsInsertionCallback());
    if (g_triangle_mesh == nullptr) {
        d["accepted"]       = false;
        d["has_mesh_scene"] = false;
        d["message"]        = "PxCreateTriangleMesh failed";
        return d;
    }

    // Static actor at identity transform (verts are already at y=9 in
    // mesh-local space, which equals world here).
    g_ground_mesh_static = g_physics->createRigidStatic(PxTransform(PxIdentity));
    if (g_ground_mesh_static == nullptr) {
        g_triangle_mesh->release();
        g_triangle_mesh = nullptr;
        d["accepted"]       = false;
        d["has_mesh_scene"] = false;
        d["message"]        = "createRigidStatic failed; triangle mesh rolled back";
        return d;
    }
    PxTriangleMeshGeometry mesh_geom(g_triangle_mesh);
    PxShape* mesh_shape = g_physics->createShape(mesh_geom, *g_material);
    if (mesh_shape == nullptr) {
        g_ground_mesh_static->release();
        g_ground_mesh_static = nullptr;
        g_triangle_mesh->release();
        g_triangle_mesh = nullptr;
        d["accepted"]       = false;
        d["has_mesh_scene"] = false;
        d["message"]        = "createShape(PxTriangleMeshGeometry) failed";
        return d;
    }
    g_ground_mesh_static->attachShape(*mesh_shape);
    // attachShape took its own reference; release our local handle so
    // the shape's lifetime is owned by the actor.
    mesh_shape->release();
    g_scene->addActor(*g_ground_mesh_static);

    // Dynamic sphere identical to Phase 5C config.
    const PxTransform dyn_pose(PxVec3(0.0f, kDynamicInitialY, 0.0f));
    g_dynamic_actor = PxCreateDynamic(
        *g_physics, dyn_pose,
        PxSphereGeometry(kDynamicRadius),
        *g_material, kDynamicDensity);
    if (g_dynamic_actor == nullptr) {
        g_ground_mesh_static->release();
        g_ground_mesh_static = nullptr;
        g_triangle_mesh->release();
        g_triangle_mesh = nullptr;
        d["accepted"]       = false;
        d["has_mesh_scene"] = false;
        d["message"]        = "PxCreateDynamic failed; mesh actor rolled back";
        return d;
    }
    g_dynamic_actor->setLinearDamping(0.0f);
    g_dynamic_actor->setAngularDamping(0.0f);
    g_scene->addActor(*g_dynamic_actor);

    const PxVec3 g = g_scene->getGravity();

    d["accepted"]                 = true;
    d["already_created"]          = false;
    d["has_mesh_scene"]           = true;
    d["dynamic_actor_count"]      = 1;
    d["static_actor_count"]       = 1;
    d["dynamic_geometry"]         = std::string("PxSphereGeometry(radius=0.5)");
    d["dynamic_initial_position"] = py::make_tuple(dyn_pose.p.x, dyn_pose.p.y, dyn_pose.p.z);
    d["dynamic_density"]          = kDynamicDensity;
    d["mesh_vertex_count"]        = 4;
    d["mesh_triangle_count"]      = 2;
    d["mesh_winding"]             = std::string("(0,2,1),(0,3,2) -> +Y normal");
    d["mesh_y"]                   = 9.0f;
    d["mesh_extent_xz"]           = 5.0f;
    d["gravity"]                  = py::make_tuple(g.x, g.y, g.z);
    d["gravity_axis"]             = "-Y";
    d["message"]                  = "mesh scene created (cooked triangle mesh @ y=9 + dynamic sphere @ y=10)";
    return d;
}

// Phase 5C: read-only pose snapshot of the dynamic actor. No raw
// PhysX pointers cross the boundary.
py::dict physx_probe_get_actor_pose()
{
    py::dict d;
    const bool is_open = (g_foundation != nullptr && g_scene != nullptr);
    if (!is_open) {
        d["accepted"]        = false;
        d["has_rigid_scene"] = false;
        d["message"]         = "rejected: PhysX context not open";
        return d;
    }
    if (g_dynamic_actor == nullptr) {
        d["accepted"]        = false;
        d["has_rigid_scene"] = false;
        d["message"]         = "rejected: rigid scene not created (call physx_probe_create_rigid_scene first)";
        return d;
    }

    const PxTransform pose = g_dynamic_actor->getGlobalPose();
    const PxVec3      vel  = g_dynamic_actor->getLinearVelocity();
    const PxVec3      g    = g_scene->getGravity();

    d["accepted"]        = true;
    d["has_rigid_scene"] = true;
    d["position"]        = py::make_tuple(pose.p.x, pose.p.y, pose.p.z);
    d["orientation_xyzw"] = py::make_tuple(pose.q.x, pose.q.y, pose.q.z, pose.q.w);
    d["linear_velocity"] = py::make_tuple(vel.x, vel.y, vel.z);
    d["gravity"]         = py::make_tuple(g.x, g.y, g.z);
    d["gravity_axis"]    = "-Y";
    d["step_count"]      = g_step_count;
    d["message"]         = "actor pose snapshot";
    return d;
}

// Phase 5B/5C: empty-or-rigid Scene simulate(dt) + fetchResults(true).
// When a rigid scene is present (Phase 5C), capture before/after pose
// and linear velocity of the dynamic actor.
py::dict physx_probe_step(float dt)
{
    const bool is_open =
        (g_foundation != nullptr) &&
        (g_physics    != nullptr) &&
        (g_scene      != nullptr);
    const bool has_rigid_scene = (g_dynamic_actor != nullptr) && (g_ground_static != nullptr);
    const bool has_mesh_scene  = (g_dynamic_actor != nullptr) && (g_ground_mesh_static != nullptr);
    const bool has_actor       = (g_dynamic_actor != nullptr);

    py::dict d;
    d["accepted"]              = false;
    d["opened"]                = is_open;
    d["has_rigid_scene"]       = has_rigid_scene;
    d["has_mesh_scene"]        = has_mesh_scene;
    d["dynamic_actor_count"]   = has_actor ? 1 : 0;
    d["static_actor_count"]    = (g_ground_static != nullptr ? 1 : 0)
                               + (g_ground_mesh_static != nullptr ? 1 : 0);
    d["dt"]                    = dt;
    d["step_count_before"]     = g_step_count;
    d["step_count_after"]      = g_step_count;
    d["simulate_called"]       = false;
    d["fetch_results_called"]  = false;

    if (!is_open) {
        d["message"] = "rejected: PhysX context not open (call physx_probe_open first)";
        return d;
    }
    // dt > 0 also rejects NaN (NaN > 0 is false).
    if (!(dt > 0.0f)) {
        d["message"] = "rejected: dt must be > 0 (got non-positive or NaN)";
        return d;
    }

    // Capture pre-step pose/velocity whenever a dynamic actor exists.
    PxVec3 pos_before(0.0f, 0.0f, 0.0f);
    PxVec3 vel_before(0.0f, 0.0f, 0.0f);
    if (has_actor) {
        const PxTransform t = g_dynamic_actor->getGlobalPose();
        pos_before = t.p;
        vel_before = g_dynamic_actor->getLinearVelocity();
    }

    bool simulate_ok = false;
    bool fetch_ok    = false;
    std::string err_msg;

    try {
        g_scene->simulate(dt);
        simulate_ok = true;
        g_scene->fetchResults(/*block=*/true);
        fetch_ok = true;
    } catch (const std::exception& e) {
        err_msg = std::string("std::exception during simulate/fetchResults: ") + e.what();
    } catch (...) {
        err_msg = "unknown C++ exception during simulate/fetchResults";
    }

    d["simulate_called"]      = simulate_ok;
    d["fetch_results_called"] = fetch_ok;

    if (simulate_ok && fetch_ok) {
        g_step_count += 1ULL;
        g_last_dt     = dt;
        d["accepted"]         = true;
        d["step_count_after"] = g_step_count;
        d["last_dt"]          = g_last_dt;
        d["message"]          = has_actor
            ? "simulate(dt) + fetchResults(true) succeeded; pose advanced"
            : "simulate(dt) + fetchResults(true) succeeded on empty scene";
    } else {
        d["accepted"] = false;
        d["step_count_after"] = g_step_count;
        d["last_dt"]          = g_last_dt;
        d["message"] = err_msg.empty()
            ? std::string("simulate or fetchResults did not complete (no exception captured)")
            : err_msg;
    }

    if (has_actor) {
        const PxTransform t_after = g_dynamic_actor->getGlobalPose();
        const PxVec3      v_after = g_dynamic_actor->getLinearVelocity();
        const PxVec3      g_vec   = g_scene->getGravity();
        d["actor_position_before"] = py::make_tuple(pos_before.x, pos_before.y, pos_before.z);
        d["actor_position_after"]  = py::make_tuple(t_after.p.x,  t_after.p.y,  t_after.p.z);
        d["actor_velocity_before"] = py::make_tuple(vel_before.x, vel_before.y, vel_before.z);
        d["actor_velocity_after"]  = py::make_tuple(v_after.x,    v_after.y,    v_after.z);
        d["gravity"]               = py::make_tuple(g_vec.x, g_vec.y, g_vec.z);
        d["gravity_axis"]          = "-Y";
    }
    return d;
}

py::dict physx_probe_close()
{
    py::dict d;

    if (g_foundation == nullptr) {
        d["accepted"]            = true;
        d["already_closed"]      = true;
        d["opened"]              = false;
        d["step_count"]          = g_step_count;
        d["last_dt"]             = g_last_dt;
        d["has_rigid_scene"]     = false;
        d["has_mesh_scene"]      = false;
        d["dynamic_actor_count"] = 0;
        d["static_actor_count"]  = 0;
        d["message"]             = "PhysX context already closed";
        return d;
    }

    // Release in reverse order of dependency.
    //
    // Phase 5C/5D: rigid actors first. PxActor::release() removes the
    // actor from its containing scene automatically, and the actor
    // releases the shapes it owns. Shapes drop their material reference
    // here, so the material must outlive them and is released after.
    // The triangle mesh is reference counted: the mesh shape held a
    // reference, so after the mesh actor releases its shape we drop the
    // last reference explicitly.
    if (g_dynamic_actor != nullptr) {
        g_dynamic_actor->release();
        g_dynamic_actor = nullptr;
    }
    if (g_ground_mesh_static != nullptr) {
        g_ground_mesh_static->release();
        g_ground_mesh_static = nullptr;
    }
    if (g_ground_static != nullptr) {
        g_ground_static->release();
        g_ground_static = nullptr;
    }
    if (g_triangle_mesh != nullptr) {
        g_triangle_mesh->release();
        g_triangle_mesh = nullptr;
    }
    if (g_material != nullptr) {
        g_material->release();
        g_material = nullptr;
    }
    if (g_scene != nullptr) {
        g_scene->release();
        g_scene = nullptr;
    }
    if (g_dispatcher != nullptr) {
        g_dispatcher->release();
        g_dispatcher = nullptr;
    }
    if (g_physics != nullptr) {
        g_physics->release();
        g_physics = nullptr;
    }
    if (g_foundation != nullptr) {
        g_foundation->release();
        g_foundation = nullptr;
    }

    // Phase 5B: clear step probe state alongside lifecycle pointers.
    g_step_count = 0ULL;
    g_last_dt    = 0.0f;

    d["accepted"]            = true;
    d["already_closed"]      = false;
    d["opened"]              = false;
    d["step_count"]          = g_step_count;
    d["last_dt"]             = g_last_dt;
    d["has_rigid_scene"]     = false;
    d["has_mesh_scene"]      = false;
    d["dynamic_actor_count"] = 0;
    d["static_actor_count"]  = 0;
    d["message"]             = "PhysX context closed cleanly; all pointers nulled";
    return d;
}

PYBIND11_MODULE(phase2b_probe, m) {
    m.attr("phase") = "2B";
    m.def("add", &add);
    m.def("describe_curves", &describe_curves,
          py::arg("object_name"),
          py::arg("strand_count"),
          py::arg("points_per_strand"),
          py::arg("point_count"),
          py::arg("floats_per_frame"),
          py::arg("frame_current"),
          py::arg("attribute_name"),
          py::arg("attribute_domain"),
          py::arg("data_type"));
    m.def("probe_position_buffer", &probe_position_buffer,
          py::arg("expected_point_count"),
          py::arg("expected_float_count"),
          py::arg("frame_current"),
          py::arg("buf"));
    m.def("deform_position_buffer", &deform_position_buffer,
          py::arg("expected_point_count"),
          py::arg("expected_float_count"),
          py::arg("points_per_strand"),
          py::arg("frame_current"),
          py::arg("amplitude"),
          py::arg("input_buf"));
    m.def("physx_probe_open",                &physx_probe_open);
    m.def("physx_probe_status",              &physx_probe_status);
    m.def("physx_probe_create_rigid_scene",  &physx_probe_create_rigid_scene);
    m.def("physx_probe_create_mesh_scene",   &physx_probe_create_mesh_scene);
    m.def("physx_probe_get_actor_pose",      &physx_probe_get_actor_pose);
    m.def("physx_probe_step",                &physx_probe_step,
          py::arg("dt"));
    m.def("physx_probe_close",               &physx_probe_close);
}
