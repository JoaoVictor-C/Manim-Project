# 0052. Shape objects and freezing: an object kept as the vector data it draws

- **Status:** Accepted
- **Date:** 2026-10-18
- **Deciders:** João Victor

## Context

Python objects (ADR 0051) run the user's code: a project that holds them asks for trust on
every computer and needs the code to keep working. Equations need LaTeX, and the user's second
PC has none, so they show placeholders there. A finished project should run anywhere. P10.2
([plan](../plans/p10-code-to-objects.md)): turn an object built by code - or any plain object -
into data that needs nothing but Manim.

What the Cairo renderer reads to draw a `VMobject` (Manim 0.22 `Camera.display_vectorized`,
`set_cairo_context_color`, `apply_stroke`): its points (subpaths split where anchors differ),
`fill_rgbas`, `stroke_rgbas` and `background_stroke_rgbas` (one row is a solid colour; several
are a linear gradient along `get_gradient_start_and_end_points`, from the sheen direction and the
piece's own bounds), `stroke_width` and `background_stroke_width`, `joint_type`, `cap_style`;
`shade_in_3d` (3D camera), `background_image` (a separate path), `z_index` (draw order). The
animations read the same: Create, Write and the rest split their time over
`family_members_with_points()`, and `interpolate_color` interpolates exactly the rgbas, widths
and sheen.

## Decision

- **Spec:** `Spec(type="Shape", params={"version": 1, "shapes": [...]})`, a root object type
  (not in the library: made by freezing). One entry per leaf of `family_members_with_points()`,
  in that order: `points` (the bezier control points; `[x, y]` when every z is 0, else
  `[x, y, z]`), `fill`, `stroke` (rgbas as they were: one `[r, g, b, a]` or a gradient's list of
  stops - a multi-row array is kept as it is, since a morph aligns stop counts), `stroke_width`;
  and only when not Manim's default `background`, `background_width`, `sheen_direction`,
  `sheen_factor`, `joint`, `cap`, `z_index`, `shade_in_3d`. A frozen equation is the plain shape
  of its glyph paths. Points are stored centred, as built. Floats keep full precision (`tolist`,
  then JSON's repr): sizes are small (below), so no rounding.
- **Building** (`adapter.shape_from_data`): a `VGroup` of `VMobject`s with the points set and the
  attributes assigned as stored - no `set_fill`/`set_stroke` that would recompute them - then
  `Spec.style` on top (only what the user set, as every object; themes colour it like a shape),
  then centred. The same function's source is written into the readable export.
- **Freezing:** `adapter.freeze_data(spec)` is `shape_data` of the object as built **with its
  style** (so the look is baked in and the shape's own style is empty); it refuses a placeholder
  (a missing file, code not trusted, a failing build, no LaTeX: "only what is drawn can be
  frozen"), a simulation, anything that is not vector paths (an image leaf, a background image)
  and more than **300 000 points or 4 MB of JSON**. `edits.freeze_layer(project, id, data)` is
  pure: it swaps the spec, keeping id, name, transform, keys, lifetime, clips and group (kind
  `spec`, one undo step "Freeze to shape"). The window also refuses an object the editor itself
  draws as a placeholder (its evaluator's view, which may be older than the trust store).
- **What can be frozen:** shapes, Text, MathTex/Tex (without parts), Number (without counting
  clips), SVG, Axes without objects on them, Python objects, plugin objects; group members. **Refused,
  with the reason:** groups, code layers, connectors, traced paths, simulations, images (pixels),
  objects on axes (built with them), parts, layers with parts or child objects, an existing
  shape, and clips that need the old type (letter by letter, counting, TransformMatchingTex at
  either end - the message names the clip).
- **UI:** "Freeze to shape" under the Object section in Properties for objects of a kind that can
  be frozen (other refusals are said in the status bar on click); "Freeze to Shape" in the
  Layers context menu and the Edit menu. A shape shows "Frozen: plain vector data" and no
  parameters; Style, Transform and clips stay. There is no unfreeze: undo is the way back.
- **Export:** the readable export writes each shape's data as a literal list (one piece per
  line) and `shape_from_data` once, then the usual style and transform calls; a shape never
  makes the export exact. The exact export carries the spec like any other.

## Consequences

- A project of frozen objects opens and renders with no trust prompt and no LaTeX; a Python
  object's code is gone from the file once frozen.
- Parameters are gone: changing the equation means undoing the freeze (or building a new one).
- Files grow: tens of KB per equation (below). Each edit compares the frozen spec (equal lists
  are compared element by element), measured below a millisecond for an equation.

## Alternatives considered

- **Store the source spec beside the data (unfreeze)** - the file would still hold the code and
  invite running it; undo covers the moment of regret.
- **Per-point colours** - the Cairo renderer has no per-point colours: rgbas are gradient stops.
- **Round floats to 1e-7** - not needed: the largest object measured (a 3x3 matrix) is 54 KB.
- **Compress equal gradient stops into one colour** - a static frame draws the same pixels, but a
  morph aligns stop counts, so the mid-frames of a Transform into a gradient would differ.

## Evidence

- Tests: `tests/core/model/test_shapes.py` (identical pixels with `np.array_equal` for a filled and
  stroked circle, a square, a Text, a MathTex, the right-triangle and Matrix templates, an SVG
  a gradient with differing stroke widths, a background stroke and round joints, and Axes, under a
  transform, keys and Create/Write and other clips; save/load exact; no LaTeX: the frozen
  equation draws while an unfrozen one is the placeholder; untrusted code: the frozen object
  draws and the file has no code; the refusals; the readable export runs and the slow test
  renders what the editor shows), `tests/ui/panels/test_shapes_ui.py`.
- Benchmark B71 ([logs/benchmarks.md](../logs/benchmarks.md), `benchmarks/bench_shapes.py`):
  Text "Hi ok" 4 pieces, 376 points, spec 52 B -> 24.9 KB; MathTex `e^{i\pi}+1=0` 7 pieces,
  488 points, 63 B -> 31.9 KB; the Matrix template (3x3) 13 pieces, 816 points, 1.4 KB -> 53.9 KB;
  builds with Manim's disk cache warm 7.5-17 ms (MathTex), 49-87 ms (Matrix, built twice on first
  use) -> 0.9-2.2 ms and 2-3.9 ms from the data.
