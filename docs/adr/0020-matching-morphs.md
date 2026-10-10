# 0020. Matching morphs between equations

- **Status:** Accepted
- **Date:** 2026-10-10
- **Deciders:** João Victor
- **Amends:** [0012](0012-layer-tree-and-part-layers.md) (morphs on part trees)

## Context

The most common equation animation in Manim is `TransformMatchingTex`: terms
that appear in both equations move to their new places, the rest fades.
Manim matches by the `tex_string` of submobjects, which only exists when the
equation was written with `{{ }}` or isolated substrings. The editor has part
layers (ADR 0012), whose v1 refused every morph on part trees.

## Decision

- A morph kind **TransformMatchingTex** between MathTex/Tex roots, built on
  Manim's `TransformMatchingAbstractBase` with editor-made keys, in two passes:
  a part's glyphs are one piece keyed by the part's TeX if that key exists on
  both sides; every other glyph is keyed by its normalized shape (as
  `TransformMatchingShapes`). Without parts it behaves like shape matching;
  parts disambiguate.
- Any morph kind may now start or end on a root with parts; the tree is drawn
  as one morph while it runs. Parts carry no morphs, and clips on a root's
  descendants may not start at or after its morph start.
- The begun morph is cached under a key that includes each end's
  finished-clip order and member transforms, so the frame stays a pure
  function of (project, t) under timing edits.

## Consequences

- Equations need not be split to morph sensibly; splitting improves matching
  where glyphs repeat.
- Which of two identical unpartitioned glyphs flies where follows glyph order
  — make the term a part to control it.
- Key overrides (Manim's `key_map`) are not offered yet.

## Evidence

- Measurements: B33 in [../logs/benchmarks.md](../logs/benchmarks.md).
- Design: [../logs/decision-sessions.md](../logs/decision-sessions.md), session 12.
- Plan: [../plans/p2e-matching-tex.md](../plans/p2e-matching-tex.md).
