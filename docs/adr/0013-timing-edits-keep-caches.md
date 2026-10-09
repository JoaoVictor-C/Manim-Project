# 0013. Edit kinds: timing edits keep caches

- **Status:** Accepted (implemented in S1.1, 2026-10-09)
- **Date:** 2026-10-09
- **Deciders:** João Victor
- **Extends:** [0008](0008-incremental-invalidation-edit-classes.md)

## Context

ADR 0008 has three edit classes: transform-only, clip/layer and spec. Moving or
trimming a clip on the timeline is a clip edit, which drops the layer's
checkpoints and begun animations, and for morph clips both partners'. Measured on
the stress scene: a morph-clip drag costs 94 ms per step, well over the 33 ms
budget, and rendering at half resolution does not help, because the cost is
Manim's `begin()` (B11, B12).

A clip's begun animation and its end checkpoint depend only on the state before
it (the preceding clips on the lane), its kind, params and ease. They do not
depend on *when* the clip plays: the evaluator computes alpha itself. Lifetime
and "which clip is active" are recomputed per frame from the document.

## Decision

Add a fourth edit kind, **timing**: only clip `start`/`duration` values changed
and the order of clip ids on every lane is unchanged.

- `Evaluator.invalidate(..., kind="timing")` adopts the new document and keeps
  all checkpoints, begun animations and proxies.
- Morph entries are keyed by their baked start/end world transforms (ADR 0005)
  and re-begun only when those transforms actually change.
- The kind is decided by `core/edits.py` by comparing old and new layers;
  callers do not choose it. A reorder through start values is a **clip** edit.

## Consequences

- Clip drags cost 15–21 ms per step on the stress scene (B13, B14), including
  morphs with keyframed partners once those partners have settled.
- Dragging a morph while a partner is mid-keyframe-motion still re-begins every
  step (~105 ms); bounded by coalescing, documented as a known slow path.
- Undo/redo of a drag is also a timing edit, so it is as cheap as one drag step.

## Evidence

- Benchmarks B11–B14 in [../logs/benchmarks.md](../logs/benchmarks.md); the
  prototype matched a freshly built evaluator pixel for pixel (max diff 0).
- Benchmark B15 (real implementation): 15–22 ms per drag step.
- `tests/core/test_edits.py`: a spy on `adapter.make_animation` proves timing
  edits never re-begin; reorder ⇒ clip; keyframed morphs rebuild only when their
  baked transforms change; all compared against a fresh evaluator.
- `tests/core/test_properties.py::test_random_edits_match_fresh_evaluator`:
  random edits through the API. Mutation-checked: a classifier that calls every
  edit "timing" makes it fail with stale frames.
