# Tokoya Development Notes

Status: public release.

Tokoya is the hair-generation and grooming half of the Tokoya + Yurameki
workflow. Tokoya creates, settles, cuts, and resets long straight hair. Yurameki
simulates the groomed Curves object.

## Current Release

- Version: 0.7.0.
- Tested workflow target: Blender 5.2 beta.
- Platform target: Windows x64 and macOS arm64.
- License: MIT.
- Release package: `dist/tokoya-0.7.0.zip`.

## Current Direction

- Keep Tokoya focused on mask planting, initial long-hair grooming, cutting, and
  reset.
- Keep simulation playback and final dynamic hair motion in Yurameki.
- Avoid destabilizing the existing settle and cutting workflow while preparing
  the public release.

## Important Behavior

- `Create Head Mask` creates a paint mesh outside the Body surface.
- `Plant Hair` reads grayscale mask pixels:
  - white means 0 cm hair,
  - black means maximum length,
  - gray means interpolated length.
- `Max Length` determines the shared point count for all strands.
- Natural Root Spacing keeps the first two root-side segments aligned to the
  maximum-length strand when possible.
- `Settle Hair Back` and `Settle With Guide` are initial grooming tools, not
  final dynamic simulation tools.
- Body collision during settle uses a filled Body Collider Proxy.
- Hair-hair collision is not implemented.

## Collision And Solver Pitfalls

- Do not add hair-hair collision without a measured design. It is expensive and
  can destabilize long straight hair.
- Collision work must use evaluated world-space coordinates when Surface Deform
  or armature deformation is involved.
- Cutting and settling must write back through the evaluated/original offset so
  modifier-driven display positions remain consistent.
- Collider proxy changes must be validated on eye, ear, and scalp boundary
  regions.
- Avoid speculative optimization. Measure before changing collision or grooming
  behavior.

## Release Notes

### 0.6.9

- Public README and manifest text are English.
- UI labels are held in English even when Blender's UI language is Japanese.
- Release documentation now describes the Tokoya + Yurameki workflow.

### 0.6.8

- `Settle With Guide` switched from temporary mesh collision to a numeric Back
  Flow Guide.

### 0.6.7

- Back Flow Guide was extended behind and below the shoulders.
- Settle button layout was cleaned up.

### 0.6.6

- `Settle With Guide` used a temporary Back Flow Guide instead of a sphere.

### 0.6.5

- Temporary bang cutters and settle Collider Proxy objects were removed after
  processing.

### 0.6.4

- `Trim Bangs` added automatic cutter creation near the eye region.

### 0.6.3

- `Settle Hair Back` was moved to evaluated display coordinates for Surface
  Deform compatibility.

### 0.6.2

- The old `Simulate` button was replaced by `Settle Hair Back`.

### 0.6.0

- Long-hair point count became length-dependent.
- Natural Root Spacing was introduced.
- Hair recording features were removed from Tokoya and left to the separate
  simulation path.

## Testing

Minimum checks before release:

```powershell
python -m py_compile .\__init__.py .\ui.py .\_world_passthrough.py .\_collision_warp.py .\_sim_warp.py .\_sim_taichi.py .\_mask_plant.py .\_mesh_ops.py .\_initial_groom.py .\_collider_proxy.py
```

Manual Blender validation should cover:

- mask creation,
- hair planting,
- `Settle Hair Back`,
- `Settle With Guide`,
- `Mesh Shrink`,
- `Trim Bangs`,
- `Urchin Reset`,
- handoff to Yurameki.
