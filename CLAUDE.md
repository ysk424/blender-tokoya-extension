# Project Working Notes (for future Claude Code sessions)

This file is a handoff log. Read it before doing anything in this repository.
Treat it as a living context document, updated when phases close.

---

## ⚠️ START HERE — Katsura v0.1.1 (2026-05-27)

**Active branch: `vbd-features-applied`** HEAD = `d1603c6`  
**Install zip**: `dist/hair_sim_physx-0.1.1.zip` (user-validated)  
**N-panel tab**: "Katsura" (not "HairSim")

### Architecture (v0.1.1)

```
_sim_taichi.py        — Taichi XPBD solver (CUDA sm_120 RTX 5070 Ti)
_world_passthrough.py — state mgmt + RAM bake + Taichi integration
__init__.py           — WM props + param conversion + operators
ui.py                 — Katsura N-panel (bl_category="Katsura")
hair_sim_defaults.json — physics-value defaults (NOT display values)
blender_manifest.toml — version=0.1.1, name=Katsura
```

### What works in v0.1.1

1. **Taichi XPBD** on CUDA sm_120 Blackwell (RTX 5070 Ti) — CPU fallback available
2. **Gravity drape** — natural hair behavior
3. **Body collision** — CC_Base_Body, BVHTree, substep-integrated (4× per frame)
4. **Follicle anchor** — point 0 AND point 1 kinematic; first segment locked to
   scalp growth direction (mimics hair follicle embedded in skin)
5. **Katsura panel** — log-scale input, ×100/÷1000 scaled inputs, actual-value display
6. **Save/Load Params** — file browser JSON preset (physics values)

### Parameter display ↔ physics conversions

| WM attr | Display | Physics conversion |
|---|---|---|
| `hair_sim_param_spring_ke` | 4.00 | 10^4.00 = 10,000 |
| `hair_sim_param_damping` | 1.0 | 1.0 / 100 = 0.01 |
| `hair_sim_param_particle_mass` | 1000 | 1000 / 1000 = 1.0 kg |
| `hair_sim_param_gravity` | -9.81 | -9.81 (no conversion) |
| `hair_sim_param_root_bending_ke` | 3.30 | 10^3.30 ≈ 2,000 |
| `hair_sim_param_bending_ke` | 1.00 | 10^1.00 = 10 |

Conversions applied in `_snapshot_params()` at each Start.

### Performance (YOKO__EXT_TEST.blend, 35,792 particles)

| Config | ms/frame |
|---|---|
| XPBD GPU, collision OFF | ~104ms |
| XPBD GPU + BVHTree collision | ~1000ms |

Bottleneck: Python BVHTree × 4 substeps × 35,792 particles (~900ms).

### Known issues / next priorities (user thinking about v0.2.0)

1. **Hair tunneling through head** — fast head movement causes strands to
   pass through skull. Cause: `find_nearest` can't detect path intersections.
   Fix: CCD ray_cast, or Warp-side detection. Follicle fix (point 1 kinematic)
   may reduce frequency. User deferred this.

2. **Collision performance** — ~900ms Python BVH per frame.
   Fix: move collision to Taichi GPU side. Target: <100ms total.

3. **v0.2.0 ideas** (user considering):
   - Clothing simulation (architecture is generic enough)
   - Collision GPU acceleration
   - Simulation quality improvements
   - Tunneling CCD

### Critical Taichi landmines (DO NOT violate)

1. **NO `from __future__ import annotations` in `_sim_taichi.py`**
   → PEP 563 makes Taichi kernel type annotations into strings → compile fail

2. **`@ti.kernel` in `@ti.data_oriented` class: scalar args only**
   → ndarray params break; use `field.from_numpy()` / `to_numpy()` instead

3. **Conditional variable in kernel**: use `ti.select(cond, a, b)`, not if/else

4. **No `ExportHelper`/`ImportHelper` in Blender 5.1 extensions**
   → Use manual `context.window_manager.fileselect_add(self)` instead

5. **Clean reinstall required after any module cache issue**
   → `sys.modules` deletion + pyc deletion is not reliable; uninstall/reinstall is fastest

6. **`SPRING_KD` is dead** — renamed to `DAMPING`. Backward-compat alias exists
   in `_world_passthrough.py` (line ~38). Remove at v0.2.0.

### MCP quick reference

```python
# Check state
import bpy; wm = bpy.context.window_manager
wm.hair_sim_mode  # BYPASS / SIMULATING / PLAYBACK

# Set param (display value, not physics!)
wm.hair_sim_param_spring_ke = 4.0   # → 10,000 physics
wm.hair_sim_param_damping   = 1.0   # → 0.01 physics

# Start sim
bpy.ops.hair_sim.start()
bpy.context.scene.frame_set(2)
```

### Branch geography

```
* vbd-features-applied  d1603c6  Katsura v0.1.1 (current)
  main                  7e7f63a  Phase 7W-G frozen
  vbd-direction         d15f953  Newton VBD probe (abandoned)
```

No push to origin yet — user has not authorized.

---

## Previous sessions (archived)

See git log for full history. Key milestones:
- v0.0.54 (6a7742e): Newton VBD, velocity-driven root — superseded
- v0.0.57 (ab6bb07): First working Taichi XPBD + body collision
- v0.0.60 (9fede78): Follicle anchor (point 1 kinematic)
- v0.1.0 (2c38d01): Katsura panel, log-scale inputs, Save/Load
- v0.1.1 (d1603c6): Label shortening — user-validated ✓

---

## What this project is

Blender 5.1 extension: hair (and future: cloth) physics simulation
using Taichi XPBD on GPU. Target: Windows x64, RTX 5070 Ti.

Owner: `azoo` / `ysk424`. Communication mostly Japanese.

### Phase 1 invariants (still apply)

- `frame_change_post` has exactly ONE handler from `bl_ext.user_default.hair_sim_physx`
- `hair_sim_mode` WM property exists, defaults BYPASS, SKIP_SAVE
- Start/Stop/Bypass operators are idempotent
