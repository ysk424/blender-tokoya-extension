# Tokoya 0.7.0

Tokoya is a Blender extension for generating and preparing
VR-character-style long straight hair from a grayscale scalp mask.

Tokoya and Yurameki are designed as one workflow: Tokoya plants, cuts, resets,
and settles the hair; Yurameki then simulates the already-groomed Curves object.

## Installation

- Blender 5.1 or newer. Current workflow testing is on Blender 5.2 beta.
- Windows x64 and macOS (Apple Silicon / arm64).

Install the release ZIP through Blender's extension/add-on installer:

```text
dist/tokoya-0.7.0.zip
```

The same ZIP installs on both platforms.

### Dependencies

Tokoya's simulation uses the `taichi` runtime, which is not bundled. After
enabling the extension, open **Preferences → Add-ons → Tokoya** and press
**Install Dependencies (taichi)** (requires a network connection). It installs
`taichi` into Blender's Python user site.

The compute backend defaults to **CUDA**. On hardware without CUDA (for example
macOS) Tokoya automatically falls back to the **CPU** backend; NVIDIA/Windows
behaviour is unchanged. Vulkan and CPU can also be selected manually in the
N-panel.

## Main Features

- UV scalp-mask based hair planting.
- White mask pixels create 0 cm hair; black pixels create maximum-length hair.
- Area-uniform planting with `4,000` strands by default.
- Automatic strand point count from 9 to 13 points based on `Max Length`.
- Natural Root Spacing: the first two root-side segments share the maximum-hair
  spacing so long and short hair flow consistently near the scalp.
- Explicit Hair, Body, Clothes, and Cutter object selection.
- `Settle Hair Back` for initial long-hair grooming.
- `Settle With Guide` using a numeric Back Flow Guide instead of temporary mesh
  collision.
- Filled Body Collider Proxy for settle-time Body collision.
- Optional Clothes collision during settling.
- `Mesh Shrink` for plane/sphere/mesh-based cutting.
- `Trim Bangs` for automatic bang cutter generation near the eye region.
- `Urchin Reset` for restoring straight hair.

Hair-hair collision is not implemented.

## Basic Workflow

1. Create an empty Hair Curves object and assign it to `Hair`.
2. Assign the animated body mesh to `Body`.
3. Run `Create Head Mask` to create a white paint mesh above the scalp.
4. Use Texture Paint to paint the hair region black or gray.
5. Run `Plant Hair`.
6. Run `Settle Hair Back` for initial back/down long-hair grooming.
7. Use `Settle With Guide` when front-side hair needs stronger back flow.
8. Assign a Cutter mesh when needed and run `Mesh Shrink`.
9. Use `Trim Bangs` with `Side +cm` and `Z +cm` for bang trimming near the eyes.
10. Pass the groomed Hair Curves object to Yurameki for simulation.

## Natural Root Spacing

Tokoya chooses one point count for all strands from `Max Length`.

```text
points = clamp(9 + floor((Max Length cm - 20) / 10), 9, 13)
```

The longest hair defines the root zone. Shorter hair created by gray mask pixels
or `Mesh Shrink` keeps that shared root zone when possible, then distributes the
remaining length evenly. Hair shorter than the root zone is compressed over the
whole strand.

This keeps long and short hair aligned near the scalp and reduces visible root
flow disorder.

## Mask Meaning

```text
hair length = (255 - pixel_value) / 255 * Max Length
```

- White (`255`): 0 cm.
- Gray: partial length.
- Black (`0`): maximum length.

## Settle Hair Back

Tokoya builds a filled Body Collider Proxy when needed. If Clothes is assigned,
Clothes is included in the settle BVH as well. The settle path is a CPU BVH
initial-grooming pass that keeps the crown shape while moving lower long hair
backward and downward.

For Hair Curves with modifiers such as Surface Deform, Tokoya reads evaluated
world-space coordinates, performs grooming and collision checks there, then
writes back to the original Curves data after subtracting the modifier offset.

The Body Collider Proxy is a closed collision shape. It caps Body boundary loops
and removes some ear protrusion geometry, so the proxy may not exactly match the
visible Body around the ears.

The Head Mask is generated 1 mm outside the Body surface.

## 0.6.9 Release

- Public README and manifest text are English.
- UI labels are kept English even when Blender's UI language is Japanese.
- This release is intended as the Tokoya side of the Tokoya + Yurameki public
  long-straight-hair workflow.

## License

[MIT License](LICENSE)
