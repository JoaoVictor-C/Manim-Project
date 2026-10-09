# 0016. Canvas editing: hit-testing and the stopwatch rule

- **Status:** Accepted (implemented in S3, 2026-10-09)
- **Date:** 2026-10-09
- **Deciders:** João Victor

## Context

S3 makes the canvas editable: click to select, drag to move. Two things need
fixed rules that other code (and users) can rely on:

- *what counts as clicking an object* — Manim objects are outlines, filled
  shapes, glyph sets and images; some are drawn invisible by clips (a FadeIn at
  its first frame has full geometry and alpha 0, B23);
- *what a move edits* — a layer may have a keyframed position (ADR 0004).

Measured on the stress scene (B21–B23): a bounding-box prefilter plus Qt path
containment plus numpy stroke distance costs at most 1.1 ms per click; Qt's
path stroker would cost 70 ms. Moving a layer costs 15 ms per drag step whether
it edits the base or a key. Dragging a layer while its morph plays moves the
drawn object only 7–93 % of the cursor distance (the morph interpolates from
its baked start) at 94 ms per step.

## Decision

- **Hit-testing** returns all layers under the point, front-most first, after a
  visibility gate (alpha > 0.02). Text-like objects hit on their bounding box,
  images on their quad, other vector objects on visible fill (nonzero
  winding) or within max(4 px, half the stroke width) of a visible stroke,
  both computed in numpy on the curves flattened into short segments.
  Alt+click cycles to the next hit behind.
- **The evaluator exposes layer identity** through `frame_layers(t)`; results
  are shared buffers, read at click/paint time and never stored.
- **One `Selection`** (layer, clip) is shared by every view.
- **Stopwatch rule** for moves: a layer with a track for the property gets a key
  at the playhead (the playhead first snaps to the nearest frame; a key within
  half a frame is replaced; a new key inherits the previous key's ease unless
  it does not end at 1); a layer without a track gets its base value changed.
- **No move during a morph** of the dragged layer (as source or target).
- **Undo**: a drag is one step; holding an arrow key is one step (auto-repeat
  events merge into the previous nudge of the same layer).

Implementation note (S3.2): the plan used Qt's `QPainterPath.contains` for
fills, but it reports some interior points as outside — every point on the
horizontal line through the centre of a Manim `Square` (`(0, 0)`, `(1, 0)`) —
so fills use a numpy winding count instead (tests:
`tests/render/test_hit_test.py`). Cost as shipped: 0.78 ms median per click (B21).

## Consequences

- Clicking selects what the user sees: invisible-at-this-moment objects and
  holes inside shapes are not hits, letters of a word are one target.
- Keys never land between frames, and the dropped object stays under the cursor.
- Users must move the playhead out of a morph to drag its partners (the panels
  still edit them).
- Scale, rotation and opacity follow the same rule when their gizmos arrive
  (Phase 2); `set_key` and `clear_track` already take the property name.

## Alternatives considered

- **Bounding boxes only** — 0.7 ms, but large boxes steal clicks and diagonal
  lines are selectable from empty space.
- **ID-buffer render** — pixel-exact, but an extra full render and awkward tolerances.
- **Pure-numpy winding** — would duplicate what Qt paths already do; unmeasured.
- **Keys at the unquantized playhead** — off-grid keys; banker's rounding makes
  "which frame" ambiguous; the drop drifts from the cursor.
- **Allow dragging during a morph** — the object cannot follow the cursor.

## Evidence

- Benchmarks B21–B23 in [../logs/benchmarks.md](../logs/benchmarks.md);
  `benchmarks/bench_canvas_interaction.py`.
- [Decision session 6](../logs/decision-sessions.md).
