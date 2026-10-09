# 0012. Layer tree and part layers

- **Status:** Accepted
- **Date:** 2026-10-09 (proposed); accepted 2026-10-09
- **Deciders:** João Victor

## Context

ADR 0004 makes the layer the unit of animation. Everyday Manim usage animates
*parts* of objects: one term of an equation (`Indicate(eq[0][1:3])`), the axes
of a graph separately from its curve. And a graph built with `axes.plot()` must
move with its axes. Flat, independent layers cannot express either.

## Decision

- Layers form a **tree** stored as a flat list with `parent_id`. Kinds:
  - *object layer* (a root): built from a spec;
  - *part layer*: `part = {tex, occurrence}` — the occurrence-th match of `tex`
    in its parent's text — and no spec. Later keys: named attribute
    (`axes.x_axis`), SVG element id captured at import.
- A tex part resolves to **one exact span** of the root's TeX, which the adapter
  wraps in its own `\special{dvisvgm:raw <g id=...>}` group. Manim's
  `substrings_to_isolate` is not used: it isolates every occurrence, so adding a
  part could retarget another, and a short key would also mark occurrences
  inside scripts and break LaTeX (B28). A one-token span right after `^`/`_` is
  braced (identical output); other spans inside scripts, and spans crossing
  another part, are refused. Unresolvable keys are flagged **orphaned**, never
  silently retargeted.
- The root is built once, with the markers; that build is drawn and animated
  (identical to the plain build at rest and mid-animation, B28).
- Children inherit the parent's layer transform (After Effects parenting); a
  part's own transform pivots on its rest centre.
- The overlap rule (ADR 0004) is scoped to the subtree: a clip may not overlap
  clips on its ancestors or descendants; siblings may animate concurrently.
  Clips that overlap in time therefore act on disjoint glyphs.
- A child's lifetime is clamped to its parent's. A clip on an ancestor animates
  the glyphs of every descendant; a descendant that is not alive is not drawn.
- Morph clips are not allowed on part trees yet (on parts, on roots with parts,
  or targeting them).

## Consequences

- Schema gains `parent_id` and `part`; `spec` becomes optional (roots only).
- The evaluator keys checkpoints of a tree by the set of finished clips in the
  subtree and draws each layer's own glyphs; roots without parts keep the
  per-layer path.
- Adding parts changes the root's build (one warm build per edit).
- Parts are confined to their root's z slot.

## Evidence

- Design: [../logs/decision-sessions.md](../logs/decision-sessions.md), sessions 1 and 10.
- Measurements: B28 in [../logs/benchmarks.md](../logs/benchmarks.md).
- Plan: [../plans/p2c-part-layers.md](../plans/p2c-part-layers.md).
