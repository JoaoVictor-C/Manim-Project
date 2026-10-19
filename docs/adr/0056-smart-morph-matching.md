# 0056. Smart morph matching: pieces, holes and start points paired by the editor

- **Status:** Accepted
- **Date:** 2026-10-19
- **Deciders:** João Victor
- **Amends:** [0005](0005-morph-clips-are-world-space-hand-offs.md) (how the in-between frames are made),
  [0022](0022-clip-params-and-overlays.md) (a param the editor reads itself)

## Context

The user asked to "improve the transform animation", focused on the look of the in-between
frames. Studio's Transform is Manim's `ReplacementTransform` (ADR 0005), whose alignment pairs
everything **in order**: submobjects by index (extra ones are faded copies of a neighbour),
subpaths by index (an extra subpath grows from the last point of the last one), points by index
from wherever each outline happens to start (more curves are made by splitting curves evenly by
count), and colours are blended in plain sRGB.

A gallery of 19 pairs (`benchmarks/bench_morph_quality.py`, B73: shapes, a rotated copy, a line
into an arrow, filled into outlined, texts of equal and different lengths, two-line texts, glyphs
with holes, a group with marks, thin lines, MathTex with Transform and TransformMatchingTex),
rendered at alpha 0, .25, .5, .75, 1 and measured, showed what that looks like:

- **twisting**: a circle into a square turns 45 degrees on the way, lopsided; the same square
  turned 90 degrees spins through a diamond half its area (point travel 0.62 of its size for no
  visible change);
- **holes**: the hole of an "o" morphing into a square flies out as a separate blob to a corner
  (the area dips to 6 % of what it should be); "oe" into "eo" turns holes into disks;
- **tangles**: letters cross themselves in mid-frames (42 self-crossings for "Hello" into
  "World", 62 for "cat" into "elephant", 78 for two-line text);
- **groups**: the two small lines marking a right angle grow into two whole squares that sweep
  across the target;
- **pops**: the frame at alpha 0 differs from the source drawn just before the morph by up to 10
  levels of 255 (and the morph at alpha 1 from the target by up to 15): the aligned copies are not
  the objects;
- **colour**: blue into red passes through a darker purple (OKLab lightness 0.056 under the mean
  of the ends).

## Decision

- **A morph clip param `match`** for Transform, ClockwiseTransform and CounterclockwiseTransform
  (`schema.MATCH`, a choice `classic` / `smart`, shown as **Matching** in Properties with a
  tooltip). It is registered with `studio=True`: the adapter reads it and never passes it to Manim.
  **Absent means classic**, so every existing file draws exactly as before (a test compares frames
  with Manim's own `ReplacementTransform` / `ClockwiseTransform` on the world-space ends,
  `np.array_equal`). The other morph kinds are unchanged: TransformMatchingShapes/Tex already pair
  pieces by key (ADR 0020) and the fades cross-fade.
- **Smart** (`core/morph.py`, numpy only, pure; `adapter.smart_pair` feeds it the drawn leaves and
  writes the result back) builds both ends as groups with the same pieces and point counts, so
  Manim's own alignment then changes nothing:
  - **pieces** are paired by an optimal assignment (Hungarian method) on their position within
    their object (each object's box mapped onto the other's), size, and a bonus when both have the
    same outline (`shape_key`: the same glyph). A piece without a partner shrinks to (or grows
    from) a point at its place mapped into the other object, and fades out (in). More than 200
    pieces are paired in order (the assignment is cubic);
  - inside a pair, **outer loops pair with outer loops and holes with holes** (a hole: inside an
    odd number of the piece's other loops), by position; an unpaired loop closes to (opens from)
    a point at its place, so a hole closes in the middle of what it becomes;
  - each **loop pair starts where the travel is shortest**: every corner and 64 arc-length offsets
    of the closed outline are tried, in both directions for open paths; a closed piece turns the
    way its partner turns (one decision per piece, so a glyph's holes keep their winding and fill);
  - **both outlines are cut at each other's corners by arc length** (corners closer than half a
    curve's share snap together), so corners land on corners or on the matching place of a side;
  - **colours** blend in OKLab, weighted by each end's opacity (a colour fading out does not tint
    the other), opacity linearly; colours and widths are held within the ends when an ease
    overshoots (the points still overshoot);
  - **alpha 0 and 1 draw each piece's original points and style**, so the morph starts and ends on
    the objects pixel for pixel.
  Pairing and alignment run once, when the morph begins (the evaluator caches the begun animation,
  ADR 0013); a frame is an interpolation of fixed arrays: still a pure function of (project, t).
- **New morph clips get `smart`** (`schema.new_clip_params`): the timeline's Add clip > Turn
  into, and the replacement morphs of Equation steps. B73: of the 17 gallery pairs it applies to,
  smart is visibly better in 14 and about the same in 3 (thin lines, a triangle into a star, a line
  into an arrow); point travel 0.35 -> 0.18 of the object's size on average, self-crossings in
  mid-frames 271 -> 44, no pops (0 levels at both ends, classic up to 15), mid-frame colour lightness on the
  mean of the ends (classic up to 0.056 darker), the rotated square 0.62 -> 0, the "o" into a square
  area dip 6 % -> 100 %, the group's marks no longer sweep. Where pieces grow from points ("cat" into
  "elephant") the drawn area dips lower than classic's faded copies (0.86 -> 0.76) - growing is
  quadratic - which reads as letters appearing rather than as a defect.
- **Scene import keeps classic** (it replays Manim's own Transform), as does every clip without the
  param; a preset or pasted clip keeps the params it was saved with.
- **Export:** the readable Python export of a smart morph falls back to the exact form with the
  reason "smart morph matching is computed by the editor" (writing the matching into the script
  would be a few hundred lines, not a helper); the exact form replays the project through the
  evaluator, so it draws the same frames. A classic morph exports as before.

## Consequences

- A morph no longer needs the right start point or piece order to look right; text into text
  morphs letter into nearby letter, with holes kept, and new letters appear where they belong.
- Cost (B73): beginning a smart morph takes 2-7 ms for shapes (classic 1-5 ms) and 55-85 ms for
  words and equations (classic 42-60 ms; most of it is building the world-space ends, shared by
  both); a frame costs 0.06-0.18 ms instead of 0.02-0.14 ms (one OKLab blend for all pieces).
- Limits, said in the guide: matching is geometric, not semantic - two different glyphs still
  morph through in-between blobs; a far identical glyph is not flown across a word (that is
  TransformMatchingShapes' job); one-to-one only - a piece never splits into two; no path arc.
- Projects with a smart morph export in the exact form.

## Alternatives considered

- **Changing Transform itself** (no param) - every saved project would draw differently.
- **Smart as an opt-in only** - the gallery shows it better in the large majority of pairs and
  never clearly worse, so new clips get it; old files keep classic.
- **Matching identical glyphs first, at any distance** - "Hello" into "World" then flies the "o"
  across the word through the other letters; a bonus that pairs same glyphs when near reads better,
  and TransformMatchingShapes already flies them.
- **Splitting surplus pieces off a neighbour** (Manim's faded copies) - the copies sweep across the
  target (the right-angle marks became squares); growing in place is calmer.
- **Equalising point counts by repeating points or splitting evenly by count** - corners drift
  along the sides (Manim's lopsided circle into square); cutting at the other outline's corners by
  arc length keeps them.
- **A readable export helper** - the matching would have to be written into every script.
- **A gentle path arc by default** - not justified by the gallery (thin lines rotate the same with
  either matching); left out.

## Evidence

- Measurements: B73 in [../logs/benchmarks.md](../logs/benchmarks.md);
  `benchmarks/bench_morph_quality.py` writes the contact sheets to `.cache/morph/`.
- Tests: `tests/core/test_morph.py` (alignment of a turned, shifted, scaled, reversed square to
  itself, corners kept, snapping, assignment against brute force, pieces by place, unpaired pieces,
  holes, determinism, OKLab blends), `tests/core/test_morph_frames.py` (classic equals Manim's
  Transform bit for bit, exact ends and scrubbing for smart, the B73 measures, a TeX pair, image
  fallback, export), `tests/core/test_random_access.py::test_morph_random_access` (both choices),
  `tests/ui/test_properties_panel.py::test_a_morph_shows_its_matching_with_a_tooltip`,
  `tests/ui/test_timeline_view.py::test_morph_clips_offer_free_targets_only`,
  `tests/core/test_equation_steps_layers.py`, `tests/core/test_scene_import.py`.
