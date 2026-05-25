# Project Working Notes (for future Claude Code sessions)

This file is a handoff log. Read it before doing anything in this repository.
Treat it as a living context document, updated when phases close.

---

## ⚠️ START HERE — Direction change to VBD (2026-05-25 PM)

**The active branch is now `vbd-direction`, not `main`.** Run
`git branch` and check the asterisk. If you find yourself on `main`
by mistake, the project's direction has changed and `main`'s HEAD
(7e7f63a, Phase 7W-G) is no longer the working line.

### Why the branch change

1. PhysX PBD particle direction was **stopped** at Phase 7A-2 (PhysX
   5.6.1 deprecated cloth-buffer API has a silent `nbTriangles >= 1`
   precondition; spring-only hair configurations crash the process —
   see the "PBD distance constraint blocker" section below).
2. NVIDIA Warp lineage (Phase 7W-A through 7W-G) ran on `main` and
   reached a working Verlet+PBD strand-chain solver that did achieve
   gravity settling visually. The user then decided that the **final**
   solver will be **NVIDIA Newton's built-in VBD** (Vertex Block
   Descent) — not our hand-written Warp PBD. Possible Warp re-use for
   body-mesh collision queries; the hand-written hair-strand kernels
   are not.
3. `main` was left at Phase 7W-G `7e7f63a` (preserved, not rebased,
   not force-pushed). The new working line `vbd-direction` was
   branched from **`499b92e` (Phase 7W-B)** — the last commit before
   any hair-strand Warp kernels landed. That commit retains the
   minimum Warp infrastructure (`_warp_kernels.py` with two trivial
   probes) but `SolverInterface` is still wired to the Phase 6C C++
   `NativeHairSolver` and no Warp hair kernels exist.

### Current state on `vbd-direction`

```
* vbd-direction d15f953   Bump manifest to 0.0.25 to avoid overwriting prior builds
                baefb55   VBD-prep: world-coord passthrough probe (no physics yet)
                499b92e   Phase 7W-B: bundle Warp kernel module for Blender runtime  (base)
                1c05cc5   Close Phase 7A-2 line: standalone diag result + NVIDIA Warp pivot
                ...
  main          7e7f63a   (frozen — Phase 7W-G line)
```

- **Active solver in `SolverInterface`**: `WorldPassthrough` (in
  `_world_passthrough.py`). NO physics. Identity passthrough: read
  Curves positions → convert to world via `obj.matrix_world` → call
  dummy `_dummy_identity_simulation(world_np)` (returns input) →
  convert back to local via `matrix_world.inverted()` → foreach_set
  + update_tag. Exactly one frame_change_post call per Blender
  frame change.
- **Surface Deform GN modifier "サーフェス変形" is muted on Start**
  (`mod.show_viewport = False`), restored on Stop. `unregister()`
  calls `_solver.stop()` as a safety net.
- **NVIDIA Newton 1.2.0** installed in Blender's bundled Python via
  user site
  (`C:\Users\azoo\AppData\Roaming\Python\Python313\site-packages\newton`).
  Verified `newton.solvers.SolverVBD` exists and the empty-model
  smoke test passed (CUDA narrow-phase kernels compile on
  `cuda:0 = RTX 5070 Ti`).
- **Bundled zip ready to install**: `dist/hair_sim_physx-0.0.25.zip`.
  Prior builds (0.0.18–0.0.24) also still in `dist/`; install-from-
  disk should pick `0.0.25` by version.

### Open design question (left for tomorrow)

When `WorldPassthrough.start()` mutes the Surface Deform GN modifier,
the hair visually detaches from the head (sea-urchin cluster shifts
~tens of cm away from the scalp in viewport). Image evidence captured
on 2026-05-25 PM.

This means the GN modifier does **more than** the ~1-2 cm per-point
offset that earlier MCP probes (frame 1) measured: it appears to
contain non-trivial logic that maps a "rest-pose" hair cluster onto
the body's evaluated scalp surface. Muting it exposes the unmapped
rest pose.

Implication for VBD: VBD's anchor input must come from the
**body-tracked head position**, not from the original Curves data
block. The options on the table (no decision yet):

| | approach | suitability |
|---|---|---|
| (a) | keep SD active; compute the SD per-anchor offset each frame and write `local_to_write = world_target − SD_offset` | math is workable but adds an inverse pass per frame |
| (b) | snapshot evaluated anchors at Start while SD is still active, then mute SD and use the snapshot for the whole session | only works if the body does not animate per frame (this scene appears not to, but fragile) |
| (c) | replace SD entirely: read body mesh evaluated vertices (e.g., via UV-anchored closest-vertex map) to compute anchor world positions | most robust; biggest engineering lift; this is the real VBD shape |
| (d) | accept the identity-passthrough behaviour as a data-path verifier only; visual quality is not the bar today | what we are doing for today's mechanical test |

Phase 1 invariants and the Phase 4D2 canonical round-trip rules
**still apply on this branch**. They are not negated by the VBD
pivot — they describe how the extension talks to Blender, not which
solver runs inside.

### What to do first when resuming

1. Confirm branch: `git branch` → expect `* vbd-direction`.
2. Confirm HEAD: `git log --oneline -1` → expect `d15f953`.
3. If Blender is closed, the user will install
   `dist/hair_sim_physx-0.0.25.zip` and bring up
   `YOKO_EXT_TEST.blend`.
4. Re-read the "Open design question" above and continue from one
   of (a)/(b)/(c)/(d) per the user's decision.
5. Do **not** push `vbd-direction` to `origin` without explicit GO.
   `main` on `origin` is still at `7e7f63a`.

---

## What this project is

A Blender 5.1 extension that will eventually host a **NVIDIA PhysX**-backed
hair simulation. Today the extension is a minimal skeleton; PhysX, GPU,
and C++ solver code are all deliberately deferred to later phases.

Target platform initially: **Windows x64 only**. Avoid choices that
permanently lock out Linux/macOS, but do not test or implement them.

Owner / single developer: `azoo` (GitHub `ysk424`). Communication is
mostly in Japanese — when in doubt, mirror the user's language.

---

## Repository layout (current)

Flat Blender-extension layout at the repo root; native build sources
isolated under `native/`.

```
.
├── CLAUDE.md                    this file
├── blender_manifest.toml        extension manifest (id=hair_sim_physx)
├── __init__.py                  add-on entry (register / unregister, operators,
│                                SolverInterface stub, frame_change_post handler,
│                                Phase 2C probe operator)
├── ui.py                        3D-View N-panel "HairSim" category
├── _native_loader.py            Phase 2D loader: env-var first, bundled fallback
├── native/                      out-of-extension build sources (NOT in zip)
│   ├── probe.cpp                placeholder pybind11 module (PYBIND11_MODULE
│   │                            phase2b_probe { add, phase=2B })
│   ├── setup.py                 setuptools + pybind11 build
│   └── build.cmd                VS 2022 BuildTools wrapper, invokes setup.py
│                                via .venv python; produces
│                                native/phase2b_probe.cp313-win_amd64.pyd
├── .venv/                       (gitignored) system Python 3.13 venv
├── dist/                        (gitignored) built extension zips
├── build/, *.pyd, *.obj, ...    (gitignored) native build artifacts
└── .git, .gitignore, .gitattributes
```

The `[build].paths` whitelist in `blender_manifest.toml` controls
exactly what enters the zip: manifest + `__init__.py` + `ui.py` +
`_native_loader.py` + `native/phase2b_probe.cp313-win_amd64.pyd`. The
.pyd must be present at build time or the extension build fails.

---

## Phase history (load-bearing)

The user enforces strict phase discipline: each phase has a written
design, an explicit GO from the user, and a minimal scope. **Do not
expand scope or merge phases without explicit approval.**

| Phase | Outcome | Commit |
|---|---|---|
| **1** | Minimal extension: Start/Stop/Reset operators, `SolverInterface` stub, `frame_change_post @persistent` handler, WindowManager `hair_sim_running` (SKIP_SAVE), N-panel "HairSim" | `ec6e468` (then layout flatten `5772e97`, manifest paths `2343791`) |
| **2A** | One-shot pybind11 .pyd built with system Python 3.13 imports successfully into Blender 5.1's bundled Python 3.13.9 via sys.path injection. Confirmed ABI compatibility despite patch-level mismatch | (no commit — temp dir experiment) |
| **2B** | Repo-tracked build: `native/probe.cpp`, `native/setup.py`, `native/build.cmd`. Built .pyd is gitignored; built artifact loads from repo via MCP sys.path test | `98a12d6` |
| **2C** | Extension reaches native via `_native_loader.py`. `HAIR_SIM_NATIVE_DIR` env var only. `hair_sim.probe_native` operator (INTERNAL, no UI). Phase 1 invariants preserved | `3dfb125` |
| **2D** | Native .pyd bundled inside extension zip at `<pkg>/native/`. Loader priority γ: **env var first, bundled fallback, None**. Loader uses `importlib.util.spec_from_file_location` and overrides `__file__` to defeat CPython's single-phase extension cache (so the chosen path is visible to callers). `platforms = ["windows-x64"]` added | `4c7e0ec` |
| **3A** | Read-only investigation of `YOKO__EXT_TEST.blend` (`C:\Users\azoo\Documents\Blender\QueSera2\YOKO__EXT_TEST.blend`). Hair = single Curves object `カーブ.001`, 4474 strands × 8 points = 35,792 points, uniform 8 points/curve. Modifier stack: Geometry Nodes "サーフェス変形" (Surface Deform). Evaluated data differs from original (Surface Deform applied). Memory budget table for 1411 frames | (MCP only) |
| **3B** | Read evaluated `position` via `foreach_get` into `array.array('f')` (107,376 floats / 419 KiB per frame) and into `bytearray + memoryview.cast('f')`. Per-frame and 32-frame multi-frame chunks behave identically. Dominant cost = `frame_set` + depsgraph eval ≈ 60 ms/frame; foreach itself is sub-ms | (MCP only) |
| **3C** | Writeback to **original** Curves data works. Direct assignment and `foreach_set` both succeed. `obj.data.update_tag()` + re-`evaluated_depsgraph_get()` propagates to evaluated data. Surface Deform consumes original positions (applies a roughly linear ~0.91× transform on the offset before reaching evaluated coords). Viewport visibly changes once enough strands are moved (~1000+) | (MCP only) |
| **3D** | Full-frame writeback (all 35,792 points). Per-frame deformation total ≈ **46 ms**: depsgraph re-eval **37 ms (~81%)**, Python loop 6.4 ms, foreach_get+set 0.14 ms combined | (MCP only) |
| **3E** | Temporary `frame_change_post` handler drives non-cumulative deformation across frames 800–840. Deterministic (revisit same frame → same shape), Phase 1 handler count unaffected, handler removed cleanly after test. ~110 ms/frame end-to-end via `frame_set` | (MCP only) |
| **4A** | `describe_curves(name, counts, attribute fingerprint, ...)` in `native/probe.cpp`. Metadata-only round-trip Python → C++ → Python via `py::dict`. UTF-8 string round-trip OK | `fabf63c` |
| **4B** | `probe_position_buffer(metadata, py::buffer)`. Read-only ingest of one frame's float32 buffer (107,376 floats) via the Python buffer protocol. Both `array.array('f')` and `bytearray+memoryview.cast('f')` accepted identically. Computes min/max/sum/avg/checksum; returns dict. Pointer not retained; input not mutated. `first_vec3` matches Phase 3B baseline bit-for-bit | `5698baa` |
| **4C** | `deform_position_buffer(metadata, amplitude, py::buffer)` returns a **new** `py::bytes` result buffer alongside summary. Deterministic per-strand z-offset: root 0, tip +amplitude, linear interpolation. Input not mutated; result memory is Python-owned. `checksum_delta` matches closed-form theory (`amplitude × 4 × n_strands`) | `c96d147` |
| **4D** | First end-to-end round-trip Blender↔C++↔Blender attempted with **evaluated→original** writeback. **Mechanically passed all API checks** but caused a double Surface Deform application — hair detached from head (`eval_first` shifted from -0.319 to -0.620). Documented as the textbook landmine #2 outcome; path **rejected as the canonical route** | (MCP only) |
| **4D2** | Canonical round-trip: **original→C++→original**. Hair deforms naturally and stays attached to the head. Root completely fixed (eval delta = (0,0,0)), tip lifts (eval z delta +0.236 from input +0.25). Surface Deform applies its transform once on the modified rest pose | (MCP only) |
| **4E** | Time-driven non-cumulative C++ deformation across frames 800–840 via temporary `frame_change_post` handler. C++ replaces Phase 3E's pure Python loop: handler-internal cost **0.24 ms** (vs 12 ms in 3E, ~50× faster). 1-frame end-to-end stays at ~100 ms because Blender-side depsgraph/Surface Deform/rig dominates. Determinism, baseline restore, handler cleanup, Phase 1 invariants all verified | (MCP only) |
| **5A** | PhysX 5.6.1 lifecycle probe: `physx_probe_open / status / close` in `native/probe.cpp`. CPU only (no GPU, no CUDA, no simulation, no rigid bodies). PhysX SDK cloned to **`C:\Users\azoo\git\PhysX`** (sibling dir, not in this repo), built with custom preset `vc17win64-cpu-md` (CPU only + dynamic CRT `/MD` to match pybind11). Open → status → close round-trips, idempotent re-open/re-close, Blender never crashes. First crash on 0.0.8 (`PhysX_64.dll` delay-loads `PhysXCommon_64.dll`, which `os.add_dll_directory` does NOT cover) → fixed in 0.0.9 by preloading the 3 PhysX DLLs in dependency order via `ctypes.WinDLL` inside `_native_loader.py` | this commit |
| **5F** | MCP-only practical-scale verification of the Phase 5E pipeline against **CC_Base_Body** (225,184 verts / 397,024 loop triangles, Blender `Armature` modifier). Same Blender (x,y,z) → PhysX (x,z,-y) axis remap as 5E. Buffer build (matrix_world + remap + index extraction) via numpy fast path = **71.8 ms**. PhysX **CPU cooking = 130.1 ms** for 397k triangles. Per-step simulation = **0.081 ms/step** (dominated by BVH traversal). Sphere bounced at step 28 (meaningful interaction confirmed), then exited the body footprint as in 5E. Two cycles bit-deterministic. Blender did not crash. GPU/CUDA unused, Curves/SolverInterface untouched. **No code changes** | (MCP only — see Phase 5E commit `0ee4918`) |
| **5G** | **GPU / CUDA PhysX lifecycle opened.** Custom preset `vc17win64-gpu-md` (CUDA 12.9, `/MD`, `PX_GENERATE_GPU_PROJECTS=True`, `PX_GENERATE_GPU_REDUCED_ARCHITECTURES=True` → SASS 80/86/89/90/100/120 + PTX 120, Blackwell SM_120 covered) built `PhysXGpu_64.dll` (324 MB). New entry points `physx_gpu_probe_open / status / step / close` in `native/probe.cpp` — **case A: completely separate GPU globals** from the CPU path, mutually exclusive open. `PxCreateCudaContextManager` succeeded, `cuda_device_name = "NVIDIA GeForce RTX 5070 Ti"`, `broadphase_type="GPU"`, `gpu_dynamics_enabled=true`, **`fallback_detected=false`**. Empty-scene `simulate/fetchResults` succeeded across 2 cycles. CPU path regression-free. Blender did not crash | `052cffe` |
| **5H** | CPU vs GPU **rigid-grid benchmark** (`physx_benchmark_rigid_grid_cpu/gpu` — local PhysX per call, no global pollution; sphere grid on ground plane; restitution=0). 100 / 1000 actors × 120 steps × dt=1/60. **Headline (avg step time)**: CPU 0.067 / GPU 0.789 ms @ 100 → CPU 0.778 / GPU 1.805 ms @ 1000. GPU **`fallback_detected=false`** confirmed both runs (device="NVIDIA GeForce RTX 5070 Ti", broadphase="GPU"). All runs `finite_check=true`, `nan_inf_count=0`. 100-actor checksums CPU/GPU near-identical; 1000-actor GPU settled less in 120 steps (solver-difference, spec allows). 5000-actor + Blender-mesh-collider variants deferred to a later phase | `e7c435a` |
| **7A-1** | **First real PhysX PBD particle ingestion.** 4000 Curves root points (`i%8==0` of `カーブ.001`) injected as anchor particles into `PxPBDParticleSystem` with `PxVec4.w = 0.0f` → fixed (confirmed in `particlesystem.cu:1596` `if(invMass==0) continue;`). Empty phase (`PxParticlePhaseFlags(0)`, no self-collide, no fluid). `gravity=(0,0,0)/1 step` and `gravity=(0,0,-9.81)/10 steps`: `max_displacement_from_initial=0` both runs, `nan_inf_count=0`, `fallback_detected=false`. GPU device confirmed = "NVIDIA GeForce RTX 5070 Ti". env-var dev mode, no zip bundle, no manifest bump. Local PhysX one-shot per call (no global pollution) | `c0ed932` |
| **7A-2** | **Broken-path record (NOT committed).** Same probe + 4000 child particles (`invMass=1`) + 4000 distance constraints via the deprecated `PxParticleClothBufferHelper` / `PxParticleSpring` / `PxParticleClothPreProcessor` / `ExtGpu::PxCreateAndPopulateParticleClothBuffer` path with `numTriangles=0`. Result: PhysX internally issued `cuMemAlloc(0 bytes)` for the triangle buffer; CUDA returned `CUDA_ERROR_INVALID_VALUE`; `PxCudaContextManager` entered OOM state; subsequent `simulate()` then `fetchResults()` triggered `EXCEPTION_ACCESS_VIOLATION` in `PhysX_64.dll` → **Blender crash** (`YOKO__EXT_TEST.crash.txt`). Crash impl rolled back from working tree; **no commit produced**. Conclusion: the deprecated cloth-buffer path **does not safe-fail** for spring-only / no-triangle constructions; cannot be used as the primary PBD distance-constraint route. Next step undecided — see "PBD distance constraint blocker" section | (no commit — `git restore`) |

**Phase 3 left no repo changes by design.** Phases 4D, 4D2, 4E left no
repo changes either (MCP-only). The committed Phase 4 surface is
`4A` + `4B` + `4C` in `native/probe.cpp`. Phase 5A adds open/status/close
to the same file plus PhysX runtime DLL preloading in
`_native_loader.py` and PhysX link settings in `native/setup.py`.
Phase 5F left no repo changes either (MCP-only); it reuses the Phase 5E
implementation against a production-scale Blender mesh.

---

## GPU PhysX env-var dev mode (Phase 5G) — load-bearing

Phase 5G is the first phase that opens a GPU-enabled `PxScene` inside
Blender. The integration intentionally stays in **dev-mode env-var
discovery** — production bundling is deferred.

* **PhysX SDK build**: custom preset `vc17win64-gpu-md` (in the sibling
  PhysX source tree, **not** in this repo). Flags: `/MD` release CRT,
  `PX_GENERATE_GPU_PROJECTS=True`, `PX_GENERATE_GPU_REDUCED_ARCHITECTURES=True`
  (SASS 80/86/89/90/100/120 + PTX 120 — Blackwell SM_120 covered for the
  RTX 5070 Ti). Stock `vc17win64.xml` is `/MT` debug CRT and incompatible
  with the pybind11 module.
* **CUDA toolchain**: CUDA Toolkit 12.9 with `nvcc.exe` on PATH. CUDA's
  VS 2022 BuildTools MSBuild integration files (`CUDA 12.9.props`,
  `.targets`, `.xml`, `Nvda.Build.CudaTasks.v12.9.dll`) must be copied
  from `CUDA\v12.9\extras\visual_studio_integration\MSBuildExtensions\`
  to `Microsoft Visual Studio\2022\BuildTools\MSBuild\Microsoft\VC\v170\BuildCustomizations\`
  (one-time admin step; CUDA installer only does this automatically for
  full VS, not BuildTools).
* **Locale fix**: PhysX GPU build trips warning `C4819` in CUDA 12.9
  `cuda.h(23862)` on Japanese-locale Windows (CP932). PhysX uses `/WX`,
  so the benign C4819 becomes an error. Workaround: build with
  `set CL=/wd4819 %CL%` (encoded in the sibling `physx/build_gpu_md.cmd`
  wrapper). Does not affect codegen.
* **Artifacts shipped with the GPU build** (~324 MB DLL because of
  per-SM compiled CUDA kernels): `PhysXGpu_64.dll` plus the same
  Foundation/Common/Cooking/PhysX_64 set as the CPU build. The GPU DLL
  delay-loads only `nvcuda.dll` (NVIDIA driver, System32). No
  `cudart64_*.dll` runtime is needed.
* **Distribution strategy in Phase 5G**: **env-var only**. `native/`
  holds all 5 PhysX DLLs (`*.dll` gitignored). The extension zip is
  **not** rebuilt for 5G; `blender_manifest.toml` keeps its prior
  version and `[build].paths` does **not** include `PhysXGpu_64.dll`.
  The 324 MB DLL would inflate install/uninstall cycles for a
  development probe. Production bundling is a later decision.
* **Activation**: launch Blender from a PowerShell session that sets
  `$env:HAIR_SIM_NATIVE_DIR = "C:\Users\azoo\git\blender-hair-extension\native"`.
  The loader prefers that path over the bundled `<pkg>/native/`.
* **Preload fix**: `PhysX_64.dll` resolves `PhysXGpu_64.dll` via a plain
  `LoadLibrary("PhysXGpu_64.dll")` inside `PxCreateCudaContextManager`.
  That call does not search `os.add_dll_directory` paths (same family
  as the Phase 5A delay-load problem). `_native_loader.py` therefore
  ctypes-preloads `PhysXGpu_64.dll` by absolute path; once loaded, the
  process's DLL handle cache satisfies PhysX's later bare-name lookup.
  Preload order: Foundation → Common → Cooking → PhysX_64 → **Gpu**.
* **Lifecycle isolation (case A)**: GPU globals
  (`g_gpu_foundation / g_gpu_physics / g_gpu_cuda_ctx / g_gpu_dispatcher
  / g_gpu_scene`) are entirely separate from the CPU path. `physx_probe_open`
  rejects when a GPU context exists, and vice versa. Do not share
  `PxFoundation` / `PxPhysics` across the two paths in this phase.
* **Verified result on RTX 5070 Ti + driver 596.36 + CUDA 12.9**:
  `cuda_context_created=true`, `gpu_dynamics_enabled=true`,
  `broadphase_type="GPU"`, `gpu_broadphase_enabled=true`,
  **`fallback_detected=false`**, `cuda_device_name="NVIDIA GeForce RTX 5070 Ti"`.
  Empty-scene `simulate/fetchResults` succeeds. Two open/step/close
  cycles per session, CPU path regression-free.
* **Bundled-extension drift**: during Phase 5G the `_native_loader.py`
  inside the installed extension was hand-overwritten from this repo's
  version so the preload list matches the GPU build. Re-installing the
  existing v0.0.14 zip would revert that file and break GPU mode. The
  next zip build (whenever Phase 5G is promoted from dev-mode) must
  carry the updated loader. The committed repo `_native_loader.py` is
  the source of truth.

---

## PBD distance constraint blocker (Phase 7A-2) — load-bearing

Phase 7A-2 attempted to attach 4000 child particles to 4000 anchors with
one distance constraint per pair. The conclusion is a **hard blocker**
on the deprecated path and must inform any future hair-strand work
that tries to use PhysX PBD particles for distance constraints.

* **The only PhysX 5.6.1 route for particle-particle distance constraints
  is the deprecated cloth-buffer family**:
  `ExtGpu::PxParticleClothBufferHelper`, `PxParticleSpring`,
  `PxParticleClothPreProcessor`, `PxPartitionedParticleCloth`,
  `ExtGpu::PxCreateAndPopulateParticleClothBuffer`,
  `PxParticleClothBuffer`. The non-deprecated `PxParticleBufferDesc` /
  `ExtGpu::PxCreateAndPopulateParticleBuffer` carries positions,
  velocities, phases only — no spring field.
* **That path does not safe-fail with `numTriangles=0`.** What happens
  on this RTX 5070 Ti + driver 596.36 + CUDA 12.9 + PhysX 5.6.1 stack:
  PhysX internally issues `cuMemAlloc(0)` for the triangle buffer →
  CUDA returns `CUDA_ERROR_INVALID_VALUE` → `PxCudaContextManager` is
  left in an OOM state → next `simulate()` aborts with `NpScene.cpp
  abort: "PhysX cannot start GPU simulation because the
  PxCudaContextManager is still in out-of-memory state"` → following
  `fetchResults()` triggers `EXCEPTION_ACCESS_VIOLATION` inside
  `PhysX_64.dll` → **Blender process dies** with a `*.crash.txt`.
* The error is not raised back to the C++ caller; cloth-buffer creation
  appears to succeed. The crash is one `simulate()` call later.
* **Implication:** PBD particle distance constraints cannot be obtained
  by passing springs-with-no-triangles. The cloth path expects at
  least one triangle. Injecting a fake/degenerate triangle to get past
  the allocator is "preprocessing to suppress a failure" and was
  rejected by the user when Phase 7A-2 was scoped, so do not try it
  without an explicit GO.
* **Status of Phase 7A-2:** test executed, broken-path observed and
  recorded; **no commit was produced for the crash implementation**.
  Phase 7A-1 (`c0ed932`) remains the anchor-only baseline.
* **Forbidden quick-fixes** (per user, until explicitly re-scoped):
  - dummy / degenerate triangle injection
  - making the deprecated cloth buffer the primary route
  - jumping to `PxD6Joint` rigid bodies as a "drop-in"
  - writing custom CUDA kernels via `PxParticleSystemCallback::onPostSolve`
  - tuning damping / stiffness / mass / gravity to mask the crash
* **Open question for the next phase:** which constraint mechanism
  will replace this for hair strands? Candidates (none authorized
  yet): cloth buffer with 1 honest triangle per strand-triple,
  `PxParticleAttachment` (also deprecated), deformable surface FEM,
  rigid-body chain with `PxD6Joint`, or a fully custom CUDA-side
  constraint solver invoked from `PxParticleSystemCallback`.

### Source-level follow-up (Phase 7A-2H hypothesis probe — also rolled back)

A second in-Blender probe with `maxTriangles=1000` (capacity > 0, but
`nbTriangles=0`, no dummy triangle data) was attempted to test whether
the previous crash was specifically a capacity-zero allocation issue.
It **crashed identically** (same `cuMemAlloc(0 bytes)`, same access
violation in `PhysX_64.dll` at the same DLL-internal offset, just a
different ASLR base). That hypothesis is therefore **falsified** — the
0-byte allocation is not solely tied to `maxTriangles`.

A PhysX 5.6.1 source-trace narrowed the cause down further. Key facts
verified by reading the PhysX SDK source tree directly:

* **Crash origin** is `physx/source/gpucommon/src/PxgCudaMemoryAllocator.cpp:135–141` —
  `cudaContext.memAlloc(&ptr, size)` with `size == 0` returns
  `CUDA_ERROR_INVALID_VALUE (=1)`. The allocator then calls
  `cudaContext.setAbortMode(true)`, which is the OOM-state ratchet
  reported by the next `simulate()` call (`NpScene.cpp:3036`). Any
  `nElements * sizeof(T) == 0` reaches this path.
* **maxTriangles=0 case** allocates 0 bytes at
  `PxgParticleSystemCore.cpp:380`
  (`PX_DEVICE_MEMORY_ALLOC(PxU32, ctx, maxNumTriangles * 3)`) inside
  `PxgParticleClothBuffer::PxgParticleClothBuffer`. The
  `PX_ASSERT(maxNumParticles > 0 && maxNumTriangles > 0)` directly
  above this is a release-build no-op, so the contract is silently
  violated.
* **maxTriangles=1000 case**: the constructor allocation succeeds, but
  `setCloths(output)` (`PxgParticleSystemCore.cpp:405–466`) does
  further device allocations sized by `mNumActiveParticles`,
  `mNumPartitions`, `mNumSprings` (guarded), `mNumCloths` (unguarded),
  and `mRemapOutputSize` (unguarded). Any one of these being 0
  reproduces the same crash signature. The downstream solver kernels
  themselves are guarded (`solveSprings`, `solveInflatables`,
  `solveAerodynamics` all have `> 0` early-outs) — the failure is
  purely in the allocator path.
* **Architectural implication**: the cloth path was designed for woven
  cloth, not spring-only rigs. `nbTriangles == 0` is not a supported
  configuration even when the kernels could handle it. The deprecation
  tags throughout (`PxParticleSpring`, `PxParticleCloth*`,
  `addRigidAttachment`, etc.) reinforce that NVIDIA isn't maintaining
  edge cases of this path. The snippet header comment in
  `SnippetPBDCloth.cpp` literally says "Particle cloth has been
  DEPRECATED. Please use PxDeformableSurface instead."
* **Open candidates that remain** (without an out-of-Blender probe we
  can't pick one):
  - `nbCloths == 0` at `setCloths` time (`PxgParticleSystemCore.cpp`
    lines 444 / 445 / 448).
  - `output.nbPartitions == 0` (line 431) — only possible if
    `partitionSprings` was skipped or output was default-constructed.
  - `numActiveParticles == 0` (line 430) — only possible if
    `setNbActiveParticles` wasn't called.
* **Recovery**: once `setAbortMode(true)` ratchets on a
  `PxCudaContext`, the process must be torn down and a fresh
  `PxCudaContextManager` created. There is no in-process recovery —
  this is why Blender dies even though our `try/except` catches the
  Python-level exception.
* **Forbidden quick-fixes (still)**: dummy triangle injection,
  `setAbortMode` workaround, in-process retry. Adding 1 dummy triangle
  alone may not even fix the crash if the second unguarded zero
  (e.g., `nbCloths == 0`) is actually what's biting in our setup.

**Next-phase plan**: a standalone C++ probe outside Blender, derived
from `SnippetPBDCloth.cpp`, toggling Arm A (`addCloth` called once,
`nbCloths=1`, `nbTriangles=0`, partitioned springs) vs Arm B
(`addCloth` skipped, default-constructed `PxPartitionedParticleCloth`)
to isolate which unguarded allocation actually fires for our 4000
anchor + 4000 child + 4000 springs configuration. **No in-Blender
retry until that standalone probe disambiguates.**

### Step 2 standalone probe result (PhysX direction closed)

The standalone probe (`native/diag/arm_a_b_probe.cpp`) ran outside
Blender and produced an unambiguous source-level conclusion:

* Arm A Stage 1 (descriptor only, no GPU alloc):
  `clothDesc.nbCloths=1, nbTriangles=0, nbSprings=4000, nbParticles=8000`,
  `output.nbCloths=1, nbPartitions=8, nbSprings=4000, remapOutputSize=16000`.
  Every count except `nbTriangles` is non-zero, ruling out the
  "missing partitioned output" and "addCloth never called" candidates
  that Desktop's source trace had listed.
* Arm A Stage 2 (cloth buffer creation): emits **exactly one**
  `PxgCudaMemoryAllocator.cpp(140): out of memory: failed to
  allocate memory 0 bytes! Result = 1`, then returns a non-null
  cloth-buffer pointer with `contextIsValid() == 1`. The simulate-
  time abort chain (`NpScene.cpp(3036)`, `EXCEPTION_ACCESS_VIOLATION`
  in `PhysX_64.dll`) does not fire here because the standalone exe
  doesn't call `simulate()`; the exit code is non-zero on process
  teardown, but no Blender process is at risk.
* Arm B Stage 2 (all counts zero) also emits **exactly one** identical
  error message. If multiple unguarded allocations in `setCloths`
  were the cause, Arm B would emit several — it does not.
* Conclusion: the single 0-byte CUDA allocation is inside
  `PxgParticleClothBuffer`'s constructor, sized by
  `clothDesc.nbTriangles` (which `PxCreateAndPopulateParticleClothBuffer`
  passes to the constructor as `maxNumTriangles`). The helper's
  `maxTriangles` parameter does **not** participate in this path.
  Desktop's section D2 conjecture (that `maxTriangles=1000` would
  satisfy the constructor) was wrong on this specific point.
* **Hard structural finding**: `clothDesc.nbTriangles >= 1` is a
  silent precondition of the cloth-buffer construction in PhysX
  5.6.1. Spring-only configurations (no triangles at all) cannot be
  expressed through this API. Avoiding dummy-triangle injection
  therefore closes the cloth-buffer route entirely for the
  hair-strand use case.

### Direction change after Step 2: PhysX PBD path is stopped

The Phase 7 PhysX-PBD-particle direction is **stopped**. The
deprecated cloth-buffer API is the only PhysX 5.6.1 surface that
exposes particle-particle distance constraints, and the source-level
investigation above shows it cannot be used in a spring-only hair
configuration without injecting fake triangle data — which was
explicitly forbidden during scoping ("前処理で抑えない").

The project continues from the working baseline at and including
Phase 6C (commit `79a9fb3`). The native solver shell, the original
→ C++ → original round-trip, and the Start/Stop/Reset lifecycle are
all retained. The next phase line moves to **NVIDIA Warp** as the
GPU compute backend; see the Phase 7W history rows once those
commits land. The Phase 7A-1 anchor-only PBD commit (`c0ed932`)
remains in the history as a record of the API surface that was
explored, but is not the active path forward. The standalone
`native/diag/` exe is kept as the reproducible evidence behind this
decision, not as a probe that will run again.

---

## Phase 5H benchmark headline (CPU vs GPU rigid grid)

First side-by-side comparison of CPU vs GPU PhysX on a controlled
workload. Method: local PhysX stack per call, sphere grid above a static
ground plane, restitution=0, 120 steps, dt=1/60, sphere radius=0.05,
density=1.0, spacing=0.2, grid_origin_y=1.0.

| actors | CPU avg step | GPU avg step | GPU / CPU |
|---:|---:|---:|---:|
| 100  | **0.067 ms** | **0.789 ms** | 11.8× slower (GPU loses) |
| 1000 | **0.778 ms** | **1.805 ms** | 2.3× slower (GPU loses, gap narrows) |

Scaling exponent across 100 → 1000 actors (10× workload):

* CPU: time × 11.6 → exponent ~1.07 (super-linear)
* GPU: time × 2.29 → exponent ~0.36 (sub-linear)

**Stance:** GPU fixed overhead (CUDA scene_create ~86–110 ms,
warmup_step ~1.6–1.9 ms) dominates at small actor counts, so GPU is
not the answer for handfuls of actors. As the workload grows the GPU
scaling curve is much flatter than the CPU one, so a crossover exists
somewhere above 1000 actors. Phase 5H deliberately stopped at 1000 to
keep the implementation phases moving — the 5000-actor data point and
the Blender-mesh-collider variant (5H-B) are deferred until a phase
that actually needs them.

`fallback_detected=false` on every GPU run (`device="NVIDIA GeForce
RTX 5070 Ti"`, `broadphase_type="GPU"`, `gpu_dynamics_enabled=true`).
All runs `finite_check=true`, `nan_inf_count=0`. CPU and GPU final
positions are not bit-identical (PhysX CPU and GPU solvers differ
numerically) but are physically plausible; 100-actor checksums matched
to ~1e-5, 1000-actor GPU settled slightly less in 120 steps.

---

## CPU PhysX baseline (Phase 5F) — future GPU comparison anchor

Phase 5F measured the end-to-end CPU path for a real collision-body
candidate. These numbers serve as the **CPU baseline for any later
CUDA / GPU PhysX work** in this project:

| stage | cost (CC_Base_Body @ frame 800) |
|---|---:|
| evaluated mesh + `to_mesh()` | 0.055 ms |
| `calc_loop_triangles()` | 0.003 ms |
| numpy buffer build (`matrix_world`, axis remap, `foreach_get`) | **71.8 ms** |
| `PxCreateTriangleMesh` (397k tris, BVH build) | **130.1 ms** |
| `createRigidStatic` + shape | 0.035 ms |
| `simulate(1/60)` + `fetchResults(true)` | **0.081 ms/step** |

Scale anchors:

* 397k triangles is ~227× Phase 5E's High_Heels mesh; cook time scaled
  ~271×, consistent with O(n log n) BVH construction.
* Per-step CPU cost stays sub-ms even against a 397k-tri collider —
  collision sweep against PhysX's BVH is essentially free for a single
  sphere.
* The numpy fast path (`foreach_get` + `matrix_world` as a single
  `np.array(mw) @ co.T`) is ~10× faster than a per-vertex
  `mathutils.Matrix @ Vector` loop would have been at this scale.

Interpretation: at this CPU baseline, the CC_Base_Body cook is a one-time
~130 ms cost that fits comfortably inside a session-start budget. There
is no Phase-5F-level argument yet for moving cooking to GPU. Decide that
again when a phase introduces multi-body or per-frame-recook scenarios.

---

## External PhysX SDK location (Phase 5A onward)

PhysX 5 is **not** vendored in this repo. It lives outside:

```
C:\Users\azoo\git\PhysX                  ← shallow clone of NVIDIA-Omniverse/PhysX (5.6.1)
└── physx\
    ├── include\                          # source headers (unused; we use install/)
    ├── source\, compiler\, ...           # SDK sources + generated VS projects
    ├── buildtools\presets\public\
    │   └── vc17win64-cpu-md.xml         # custom preset (CPU only + /MD CRT)
    └── install\vc17win64-cpu-md\PhysX\   # build output, consumed by setup.py
        ├── include\                      # public headers
        └── bin\win.x86_64.vc143.md\release\
            ├── PhysXFoundation_64.{lib,dll}
            ├── PhysXCommon_64.{lib,dll}
            ├── PhysX_64.{lib,dll}
            └── PhysXExtensions_static_64.lib, PhysXPvdSDK_static_64.lib (link only)
```

**Why a custom preset:** the stock `vc17win64-cpu-only.xml` preset
builds with `/MT` (static CRT) which is ABI-incompatible with the
pybind11 module (built `/MD`). The custom `vc17win64-cpu-md.xml`
preset flips `NV_USE_STATIC_WINCRT=False` and also disables snippets
and OmniPVD to keep the build minimum.

**To rebuild PhysX from scratch:**
1. `cd C:\Users\azoo\git\PhysX\physx`
2. `generate_projects.bat vc17win64-cpu-md` (needs VS cmake on PATH)
3. Open `compiler\vc17win64-cpu-md\PhysXSDK.sln` in MSBuild (or VS),
   build the `INSTALL` project, configuration `release`, platform `x64`.
4. Re-run `native/build.cmd` to re-link `phase2b_probe.pyd` against the
   updated PhysX libs.
5. Re-copy `PhysX_64.dll`, `PhysXCommon_64.dll`, `PhysXFoundation_64.dll`
   into `native/` (they are `.gitignore`d).

**Override the PhysX install path** by setting `PHYSX_INSTALL_DIR`
before running `native/build.cmd`. Default is the sibling path above.

**Delay-load caveat:** `PhysX_64.dll` declares `PhysXCommon_64.dll` as
a *delay-loaded* dependency. The Microsoft delay-load helper uses raw
`LoadLibrary` calls that do NOT respect `os.add_dll_directory`. The
loader (`_native_loader.py`) therefore explicitly preloads PhysX DLLs
in dependency order (Foundation → Common → PhysX) via `ctypes.WinDLL`
with absolute paths before importing the extension module. Without
that preload, `PxCreatePhysics` crashes with VC EH delay-load failure
`0xc06d007e`.

---

## Performance stance (Phase 4 conclusion — load-bearing)

After Phase 4E, per-call cost is dissected as follows for the
YOKO__EXT_TEST.blend / カーブ.001 scene (35,792 points, single Curves
object, Surface Deform Geometry Nodes + Armature rig):

| Layer | Per-frame cost | Status |
|---|---|---|
| C++ deformation (`deform_position_buffer`) | ~0.14 ms | negligible |
| Python ↔ C++ buffer transfer (in/out, copy via `py::bytes`) | ~0.10 ms total | negligible |
| `foreach_get` / `foreach_set` on 107,376 floats | ~0.10 ms total | negligible |
| **Blender depsgraph + Surface Deform + rig evaluation** | **~95–100 ms** | **dominant, accepted** |

**Stance:**

1. The hair-extension code path (C++ deform + buffer transfer +
   foreach_get/set) is **already fast enough** for the foreseeable
   roadmap. Further micro-optimization there is wasted effort.
2. The dominant cost is **the existing rig** (Surface Deform on
   `カーブ.001`, Armature on the body meshes, etc.). This is **not**
   the extension's cost; it is the scene's cost.
3. Surface Deform **cannot be removed** in this scene. It is the
   mechanism that attaches hair curves to the body. Any path that
   bypasses it implies consuming a *baked* dataset instead of the live
   rig output.
4. Surface Deform / Geometry Nodes integration, modifier reordering,
   custom evaluators, and rig replacement are **explicitly out of
   scope** for the current line of work. Do not propose or implement
   them without an explicit go-ahead.
5. When benchmarking future phases, attribute costs to either
   "extension code" or "scene rig" and do not optimize the latter.

---

## Canonical data round-trip (after Phase 4D2)

The official boundary path for all subsequent work is:

```
obj.data.attributes["position"]              ← ORIGINAL space
        │                          (foreach_get into array.array('f'))
        ▼
   Python buffer (input)
        │
        ▼
native.deform_position_buffer(...)            ← C++ reads buffer,
        │                                       writes new result
        ▼
   Python buffer (result via py::bytes)
        │              (array.array('f').frombytes)
        ▼
obj.data.attributes["position"]              ← ORIGINAL space
        │                          (foreach_set)
        ▼
obj.data.update_tag()
        │
        ▼
evaluated_depsgraph_get() / viewport         ← Surface Deform applies
                                                exactly once here
```

**Forbidden anti-pattern (Phase 4D):**
- Read **evaluated** + write **original** → double Surface Deform →
  hair flies off head.

Whenever the round-trip is touched in a future phase, this diagram
applies. If a phase needs to deviate (e.g., the future "consume baked
data" path), it must be designed and acknowledged explicitly.

---

## Critical landmines (Curves / depsgraph work)

These are non-negotiable. They are also saved as a separate memory
entry (`feedback_curves_landmines.md`); read both.

1. **Write to original, observe via evaluated.** Never write to
   evaluated data; treat evaluated objects as read-only snapshots.
2. **Original-space offset ≠ evaluated-space offset.** Surface Deform /
   Geometry Nodes transform the result. Only require "some evaluated
   change occurs," not a specific value.
3. **Don't persist evaluated / depsgraph references.** Acquire, read,
   discard. They are session-temporary.
4. **Attribute domains have different lengths.** POINT-domain `position`
   has 35,792 entries on `カーブ.001`; CURVE-domain
   `surface_uv_coordinate` has 4474. Never flatten under one length.
5. **`bpy.data.is_dirty` is unreliable for Curves writes.** Phases 3C/3D/3E
   all modified Curves memory while `is_dirty` stayed `False`. Falsy
   `is_dirty` is not evidence the scene is unchanged. **Never use it
   to gate save decisions.**
6. **After any destructive Curves test, never `Ctrl+S`.** Recover via
   `File > Revert`, reload, or close without saving.
7. **Don't wire writeback into `frame_change_post` permanently yet.**
   Phase 3E proved the path works as a one-off; production wiring is a
   separate risk class (timing, viewport, threading) and needs its own
   phase.
8. **PhysX / CUDA / GPU / numpy / SolverInterface wiring stay
   deferred.** C++ transfer was promoted in Phase 4 (it is now the
   canonical round-trip), but the rest of this list must remain
   deferred until explicitly unblocked.
9. **Don't over-optimize foreach_get/set or the C++ deformation
   itself.** They are sub-ms. Dominant cost is `frame_set` +
   depsgraph + Surface Deform + rig (~95–110 ms/frame). This cost
   belongs to the existing scene rig, not to the extension, and is
   explicitly out of scope (see "Performance stance" above).
10. **No single giant contiguous allocation.** Work in chunked
    contiguous buffers (per-frame / N-frame chunk / strand-group).
    Working tentative direction: "chunked contiguous + float32."

---

## Placeholders not yet finalized

These names are intentional placeholders. Each is confined to **one
location** so a future phase can rename in a single edit. Do not spread
them.

| Placeholder | Location | Finalize in |
|---|---|---|
| Native module name `phase2b_probe` | `native/probe.cpp` (PYBIND11_MODULE), `_native_loader.py` (`_MODULE_NAME`), `blender_manifest.toml` (`[build].paths`) | When solver shape is known |
| `_native_loader.py` / `get_native()` | `_native_loader.py`, `__init__.py` operator import | When the boundary API stabilizes |
| `HAIR_SIM_NATIVE_DIR` env var | `_native_loader.py` (`_ENV_VAR`) | When dev/prod split is real |
| Bundled subdir `native` | `_native_loader.py` (`_BUNDLED_SUBDIR`) | Same |

---

## Current operational state

* Latest user-installed extension version is whatever was last built into
  `dist/`. Manifest in repo is `0.0.4`. **Always bump `version` in
  `blender_manifest.toml` before producing a new zip the user will
  install** (`feedback_version_bump.md`); otherwise Blender's
  install-from-disk refuses without manual uninstall.
* Uninstall via CLI when needed (full path required):
  `"C:/Program Files/Blender Foundation/Blender 5.1/blender.exe" --command extension remove hair_sim_physx`
  Blender must be **fully closed** first (DLL is locked while loaded).
* Manual UI install: `Edit > Preferences > Get Extensions > Install from Disk`
  with the zip in `dist/`. Then **restart Blender** for native module
  isolation.
* Verification pattern: MCP-driven in a freshly restarted Blender.
  Always check Phase 1 invariants at the end (handler count = 1,
  `hair_sim_running == False`, object count unchanged, `git status`
  clean).

### Phase 1 invariants (must remain true)

* `bpy.app.handlers.frame_change_post` contains exactly **one** handler
  with `__module__` starting with `bl_ext.user_default.hair_sim_physx`.
* `bpy.context.window_manager.hair_sim_running` exists, defaults
  `False`, is `SKIP_SAVE`.
* Operators `hair_sim.start`, `hair_sim.stop`, `hair_sim.reset` are
  idempotent no-ops on re-entry, do not depend on native availability,
  and never appear in the operator search (`HAIR_SIM_OT_probe_native`
  is `INTERNAL`).
* `ui.py` and `blender_manifest.toml` semantics unchanged across
  Phase 2 sub-phases; only Phase 2D added `version`, `platforms`, and
  one `[build].paths` entry.

---

## Development workflow

* Python: system Python 3.13.13 (`py -3.13`) → `.venv/` (already
  created). pybind11 3.0.4, setuptools, ninja, scikit-build-core are
  installed (the latter two are unused in the current setup but
  available).
* MSVC: Visual Studio 2022 BuildTools, MSVC 14.44.35207 at
  `C:\Program Files\Microsoft Visual Studio\2022\BuildTools\`.
* Build native .pyd: `native/build.cmd` (initializes vcvars64, calls
  setup.py via `.venv` python).
* Build extension zip:
  `"C:/Program Files/Blender Foundation/Blender 5.1/blender.exe" --command extension build --source-dir . --output-dir dist`
* The user runs Blender. Many tests need the user to manually restart
  Blender between iterations because Windows holds .pyd DLL handles
  for the lifetime of the process. Plan tests around restart points.
* MCP is the primary test harness. Prefer one-shot MCP scripts over
  adding throwaway operators to the extension.

---

## Branches

* `main` — current line of work, HEAD `9f0b8e5` (Phase 5A: PhysX
  5.6.1 open/close probe). Run `git log --oneline -10` for the real
  current state — this comment can lag.
* `phase2-cpp` — quarantined early scaffolding (full C++/PhysX/CMake/
  scikit-build-core/scripts/extern submodule) that was stripped from
  main when Phase 1 was reset. Reference only — do not cherry-pick
  blindly. Re-derive cleanly per phase instead.

---

## Memory (`.claude/projects/.../memory/`)

The harness loads these on startup. Cross-reference them, don't
duplicate. Update them rather than the inline list when feedback
arrives.

* `feedback_version_bump.md` — bump manifest version every install
  iteration.
* `feedback_curves_landmines.md` — the 10 Curves rules above (longer
  version with reasons).
* `feedback_performance_stance.md` — Phase 4E conclusion: extension
  code path is sub-ms; Surface Deform / rig cost (~100 ms/frame) is
  the scene's, not the extension's, and is out of scope.

---

## Pending / next phase candidates (not yet designed)

These are *candidates*. None are committed to. Each needs its own
design pass + user GO before implementation:

* **Phase 5B (?)** — first PhysX simulation step. Inside the C++
  side already opened in 5A: add a placeholder rigid body or two,
  call `PxScene::simulate(dt)` + `fetchResults()`, read back a
  position, release. Still no Curves, still CPU only, still no GPU,
  no Blender-side wiring. Confirms the simulator runs without
  destabilizing the lifecycle established in 5A.
* **Phase 5C (?)** — SolverInterface wiring: replace the Python
  stub body of `start / stop / reset / step` so that pressing
  Start/Stop drives the PhysX context open/close, and `step` runs
  a single PhysX `simulate(dt)`. Still no Curves data exchange.
  Mind landmine #7 (permanent `frame_change_post` wiring is a
  separate risk class — gate behind `hair_sim_running` exactly like
  Phase 1's stub already does).
* **Phase 6 (?)** — first contact between Phase 4D2's Curves
  round-trip and Phase 5C's PhysX scene: spawn one rigid body per
  strand point (or one per strand), simulate, write transformed
  positions back through the canonical original→C++→original path.
  Mind landmine #2 (original-space != evaluated-space).
* **Phase 7 (?)** — Curves bake path: investigate consuming a baked
  dataset so Surface Deform can be bypassed when desired. Out of
  scope for normal operation.
* **Phase 8+ (?)** — PhysX GPU / CUDA. Far away. Requires re-enabling
  the GPU build options in the PhysX preset, redistributing CUDA
  runtime DLLs, and accepting all the risks the current sibling-dir
  CPU-only build deliberately avoided.

When a new phase begins, do not skip steps:
1. Wait for a design request from the user.
2. Produce a design doc (options / risks / minimum completion
   criteria / Desktop alignment points) in the chat — no
   implementation.
3. Iterate on the design until the user issues an explicit GO with
   modifications.
4. Implement minimally; verify via MCP; report results.
5. Commit only what was approved; never add docs / operators / files
   the user did not ask for.

---

## Things the user has been explicit about

* Tests pass/fail criteria belong to the user, not the implementer.
* "**実装は禁止です**" / "実施禁止です" means hard stop — produce a
  design only.
* When asked to push or commit, check `git status` first. If nothing
  is staged or modified, say so rather than synthesizing artifacts.
* Do not create README/docs files unless asked.
* Do not run UI/visual checks by yourself — the user is at the
  keyboard and prefers verifying visually after explicit work.
* When Blender state matters, the user prefers to restart Blender
  themselves; coordinate by asking "終了完了 / 起動完了" markers.
* Default to Japanese in chat unless the user switches.
