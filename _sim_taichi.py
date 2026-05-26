"""Taichi XPBD solver for hair simulation.

Design choice: all @ti.kernel methods use SCALAR arguments only
(int, float / ti.f32 etc.).  ndarray inputs go through ti.field.from_numpy()
before the kernel, outputs come back via ti.field.to_numpy() after.
This avoids a Python-3.13 + Taichi-1.7.4 incompatibility where
ndarray / ti.template() annotations inside @ti.data_oriented class
kernels raise TaichiSyntaxError.
"""
import sys
import site
import numpy as np

_PYTHON_USER_SITE = r"C:\Users\azoo\AppData\Roaming\Python\Python313\site-packages"

_ti          = None
_SolverClass = None


def _ensure_taichi():
    global _ti
    if _ti is not None:
        return _ti
    if _PYTHON_USER_SITE not in sys.path:
        site.addsitedir(_PYTHON_USER_SITE)
    import taichi as ti
    try:
        ti.init(arch=ti.cuda, device_memory_fraction=0.5)
        print("[hair_sim/taichi] CUDA initialized (sm_120 OK)")
    except Exception as e:
        print(f"[hair_sim/taichi] CUDA failed ({e}), falling back to CPU")
        ti.init(arch=ti.cpu)
        print("[hair_sim/taichi] CPU initialized")
    _ti = ti
    return ti


def get_solver_class():
    """Return (creating if needed) the TaichiXPBDSolver class."""
    global _SolverClass
    if _SolverClass is not None:
        return _SolverClass

    ti = _ensure_taichi()

    @ti.data_oriented
    class TaichiXPBDSolver:
        """XPBD strand solver. All coordinates in world space (metres).

        All kernels use only scalar arguments (int / ti.f32 etc.).
        ndarray I/O goes through .from_numpy() / .to_numpy() in
        Python-side helper methods.
        """

        def __init__(
            self,
            n_total:         int,
            n_strands:       int,
            pps:             int,           # points per strand
            init_pos:        np.ndarray,    # (n_total, 3) float32 world
            particle_mass:   float,
            bending_enabled: bool,
        ):
            self.n_total   = n_total
            self.n_strands = n_strands
            self.pps       = pps

            # Main simulation fields
            self.pos       = ti.Vector.field(3, dtype=ti.f32, shape=n_total)
            self.vel       = ti.Vector.field(3, dtype=ti.f32, shape=n_total)
            self.pos_pred  = ti.Vector.field(3, dtype=ti.f32, shape=n_total)
            self.inv_mass  = ti.field(dtype=ti.f32, shape=n_total)

            # Rest-length tables
            self.seg_rest  = ti.field(dtype=ti.f32, shape=(n_strands, pps - 1))
            bend_shape     = (n_strands, max(pps - 2, 1))
            self.bend_rest = ti.field(dtype=ti.f32, shape=bend_shape)

            # Root positions written by Python before each substep
            self.roots     = ti.Vector.field(3, dtype=ti.f32, shape=n_strands)

            self._setup(init_pos, particle_mass, bending_enabled)

        # ------------------------------------------------------------------ #
        # Initialisation
        # ------------------------------------------------------------------ #

        def _setup(self, init_pos: np.ndarray, particle_mass: float, bending_enabled: bool):
            n, ns, pps = self.n_total, self.n_strands, self.pps
            pos_f = np.ascontiguousarray(init_pos, dtype=np.float32)

            self.pos.from_numpy(pos_f)
            self.vel.from_numpy(np.zeros((n, 3), dtype=np.float32))
            self.pos_pred.from_numpy(pos_f)

            inv_m = np.full(n, 1.0 / particle_mass, dtype=np.float32)
            inv_m[np.arange(ns, dtype=np.int32) * pps] = 0.0   # roots kinematic
            self.inv_mass.from_numpy(inv_m)

            # Segment rest lengths
            sr = np.zeros((ns, pps - 1), dtype=np.float32)
            for s in range(ns):
                b = s * pps
                for k in range(pps - 1):
                    sr[s, k] = max(float(np.linalg.norm(pos_f[b+k] - pos_f[b+k+1])), 1e-6)
            self.seg_rest.from_numpy(sr)

            # Bending rest lengths
            if bending_enabled and pps >= 3:
                br = np.zeros((ns, pps - 2), dtype=np.float32)
                for s in range(ns):
                    b = s * pps
                    for k in range(pps - 2):
                        br[s, k] = max(float(np.linalg.norm(pos_f[b+k] - pos_f[b+k+2])), 1e-6)
                self.bend_rest.from_numpy(br)

            # Initialise roots field from init_pos
            root_np = np.ascontiguousarray(pos_f[np.arange(ns)*pps], dtype=np.float32)
            self.roots.from_numpy(root_np)

        # ------------------------------------------------------------------ #
        # Kernels — scalar arguments only
        # ------------------------------------------------------------------ #

        @ti.kernel
        def _predict(self, dt: ti.f32, gravity: ti.f32):
            """Apply gravity, advance free particles; set kinematic roots."""
            for i in range(self.n_total):
                s = i // self.pps
                k = i %  self.pps
                if k == 0:
                    # Kinematic root: set to pre-uploaded roots field
                    self.pos[i]      = self.roots[s]
                    self.pos_pred[i] = self.roots[s]
                else:
                    self.vel[i][2]   += gravity * dt
                    self.pos_pred[i]  = self.pos[i] + self.vel[i] * dt

        @ti.kernel
        def _solve_springs(
            self,
            dt: ti.f32, seg_ke: ti.f32,
            root_bend_ke: ti.f32, bend_ke: ti.f32,
            do_bend: int,
        ):
            """XPBD distance constraints — parallel over strands,
            sequential within each strand (Gauss-Seidel).

            Bending stiffness gradient: first 2 bending springs from root
            use root_bend_ke (stiff → hair stands up from scalp);
            remaining springs use bend_ke (soft → hair drapes naturally).
            """
            for s in range(self.n_strands):   # parallel
                base = s * self.pps

                # Segment springs (i, i+1)
                for k in range(self.pps - 1):
                    i  = base + k
                    j  = base + k + 1
                    wi = self.inv_mass[i]
                    wj = self.inv_mass[j]
                    if wi + wj > 1e-10:
                        d    = self.pos_pred[i] - self.pos_pred[j]
                        dist = d.norm()
                        if dist > 1e-8:
                            C     = dist - self.seg_rest[s, k]
                            alpha = 1.0 / (seg_ke * dt * dt)
                            dlam  = -C / (wi + wj + alpha)
                            grad  = d / dist
                            self.pos_pred[i] += wi * dlam * grad
                            self.pos_pred[j] -= wj * dlam * grad

                # Bending springs (i, i+2) with stiffness gradient
                if do_bend == 1:
                    for k in range(self.pps - 2):
                        i  = base + k
                        j  = base + k + 2
                        wi = self.inv_mass[i]
                        wj = self.inv_mass[j]
                        if wi + wj > 1e-10:
                            d    = self.pos_pred[i] - self.pos_pred[j]
                            dist = d.norm()
                            if dist > 1e-8:
                                # Root area (k < 2): stiff → stands up from scalp
                                # Distal area (k >= 2): soft → drapes naturally
                                ke    = ti.select(k < 2, root_bend_ke, bend_ke)
                                C     = dist - self.bend_rest[s, k]
                                alpha = 1.0 / (ke * dt * dt)
                                dlam  = -C / (wi + wj + alpha)
                                grad  = d / dist
                                self.pos_pred[i] += wi * dlam * grad
                                self.pos_pred[j] -= wj * dlam * grad

        @ti.kernel
        def _update_vel_pos(self, dt: ti.f32, damping: ti.f32):
            """Derive velocity from position change, apply damping, advance pos."""
            for i in range(self.n_total):
                if self.inv_mass[i] > 0.0:
                    self.vel[i] = (self.pos_pred[i] - self.pos[i]) / dt * (1.0 - damping)
                    self.pos[i] = self.pos_pred[i]

        # ------------------------------------------------------------------ #
        # Python-side upload / download
        # ------------------------------------------------------------------ #

        def set_positions_velocities(self, pos_np: np.ndarray, vel_np: np.ndarray):
            self.pos.from_numpy(np.ascontiguousarray(pos_np, dtype=np.float32))
            self.vel.from_numpy(np.ascontiguousarray(vel_np, dtype=np.float32))

        def upload_corrected_positions(self, pos_np: np.ndarray):
            """Sync corrected positions (e.g. after body collision) into pos."""
            self.pos.from_numpy(np.ascontiguousarray(pos_np, dtype=np.float32))

        def upload_pred_positions(self, pred_np: np.ndarray):
            """Sync corrected positions into pos_pred (called within substep
            after body collision, before _update_vel_pos)."""
            self.pos_pred.from_numpy(np.ascontiguousarray(pred_np, dtype=np.float32))

        def get_positions_numpy(self) -> np.ndarray:
            return self.pos.to_numpy()

        def get_velocities_numpy(self) -> np.ndarray:
            return self.vel.to_numpy()

        # ------------------------------------------------------------------ #
        # High-level entry point
        # ------------------------------------------------------------------ #

        def run_frame(
            self,
            dt:              float,
            n_substeps:      int,
            n_iter:          int,
            gravity:         float,
            new_root_world:  np.ndarray,    # (n_strands, 3)
            seg_ke:          float,
            root_bend_ke:    float,
            bend_ke:         float,
            damping:         float,
            bending_enabled: bool,
            body_collision_fn = None,       # callable(pred_np) → None, or None
        ) -> np.ndarray:
            """Run one Blender frame → return final (n_total, 3) positions.

            body_collision_fn: if given, called on pos_pred (n_total,3) float32
            after each substep's constraint loop and BEFORE _update_vel_pos.
            It modifies the array in-place (push particles out of body).
            Because the correction lands in pos_pred, _update_vel_pos derives
            velocity = (pos_pred - pos) / dt which automatically includes the
            collision push — no separate velocity clamping needed.
            """
            dt_sub   = float(dt) / float(n_substeps)
            roots_np = np.ascontiguousarray(new_root_world, dtype=np.float32)
            do_bend  = int(bending_enabled)

            for _ in range(n_substeps):
                self.roots.from_numpy(roots_np)
                self._predict(dt_sub, float(gravity))
                for _ in range(n_iter):
                    self._solve_springs(dt_sub, float(seg_ke),
                                        float(root_bend_ke), float(bend_ke),
                                        do_bend)
                # Body collision: modify pos_pred, then derive velocity normally.
                if body_collision_fn is not None:
                    pred_np = self.pos_pred.to_numpy()
                    body_collision_fn(pred_np)          # push out, in-place
                    self.upload_pred_positions(pred_np)
                self._update_vel_pos(dt_sub, float(damping))

            return self.pos.to_numpy()

    _SolverClass = TaichiXPBDSolver
    return TaichiXPBDSolver


# ------------------------------------------------------------------ #
# Body collision (Python / Blender BVHTree — called after run_frame)
# ------------------------------------------------------------------ #

def build_body_bvh(body_name: str):
    """Build a BVHTree from the evaluated (skinned) body mesh."""
    import bpy
    from mathutils.bvhtree import BVHTree
    body_obj = bpy.data.objects.get(body_name)
    if body_obj is None or body_obj.type != "MESH":
        return None
    dg = bpy.context.evaluated_depsgraph_get()
    return BVHTree.FromObject(body_obj.evaluated_get(dg), dg, epsilon=0.0)


def apply_body_collision(
    positions:  np.ndarray,     # (n_total, 3) float32, world — modified in-place
    bvh,
    root_mask:  np.ndarray = None,  # (n_total,) bool — True = kinematic root, skip
    margin:     float = 0.005,
) -> int:
    """Push hair particles out of the body mesh surface.

    Returns the number of particles that were corrected (for diagnostics).

    Uses BVHTree.find_nearest: compute depth = (pt - nearest_surface).dot(face_normal).
    depth > 0 → outside; depth < 0 → inside.
    Any particle with depth < margin is pushed outward to depth == margin.

    Kinematic root particles (root_mask[i] == True) are skipped because
    they are driven by the head animation and must stay on the scalp.
    """
    from mathutils import Vector
    n_pushed = 0
    n = len(positions)
    for i in range(n):
        if root_mask is not None and root_mask[i]:
            continue                        # skip kinematic roots
        pt             = Vector(positions[i])
        loc, normal, _, _ = bvh.find_nearest(pt)
        if loc is None or normal is None:
            continue
        depth = (pt - loc).dot(normal)      # >0 outside, <0 inside
        if depth < margin:
            c = normal * (margin - depth)
            positions[i, 0] += c.x
            positions[i, 1] += c.y
            positions[i, 2] += c.z
            n_pushed += 1
    return n_pushed
