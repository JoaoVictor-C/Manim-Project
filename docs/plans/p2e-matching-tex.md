# P2e — TransformMatchingTex between equations: implementation plan

- **Status:** ✅ Done (2026-10-10) — `tests/acceptance/test_acceptance_p2e.py`
- **Date:** 2026-10-10
- **Decided in:** [decision session 12](../logs/decision-sessions.md) (Terza, `fast`, confidence 0.90)
- **Evidence:** benchmark B33 in [../logs/benchmarks.md](../logs/benchmarks.md)
- **ADR:** [0020 — Matching morphs between equations](../adr/0020-matching-morphs.md)

## Goal

Turn one equation into another term by term: matching terms fly to their new
places, the rest fades out and in. **Done when** you can split two equations
into terms, add *Turn into > TransformMatchingTex* between them, and the morph
scrubs exactly as it plays and exports exactly as the editor shows it.

## Matching

A morph clip of kind `TransformMatchingTex`, between two MathTex/Tex roots, with
or without parts. Pieces are keyed in two passes:

1. each resolved part layer's own glyphs form a piece keyed `tex:<part TeX>`,
   kept whole **only if the same key exists on the other side** (equal keys
   move together);
2. every other glyph — unpartitioned, or from a part with no counterpart — is
   its own piece keyed by its **shape** (outline centred and scaled to height
   1, as `TransformMatchingShapes` does); equal shapes are grouped.

Matched keys transform into each other; unmatched pieces fade out (source) and
in (target). Parts make matching precise where it would be ambiguous and never
make it worse. Built on Manim's `TransformMatchingAbstractBase` (B33: random
access exact, also with groups of different sizes; 15 ms to begin, 1.3 ms per
frame).

## Model

- ADR 0012's refusal is relaxed: **any** morph kind may start or end on a root
  with parts. Parts still carry no morphs.
- Clips on a root's descendants may not start at or after the root's morph
  start (they would be clamped away — a silent no-op).
- `TransformMatchingTex` only between TeX roots (allow-list + schema check).

## Evaluator

- While a morph on a tree root is active, the root yields one entry (the
  morph) and its parts none.
- Source: copies of the tree's normal drawing at the clip start (a helper that
  never looks at the morph, so no recursion); target: copies of the target
  tree's drawing at the clip end. Other morph kinds compose the members into
  one group.
- The begun morph is cached under a bake key: per end, the tree's finished-clip
  order and every member's transform (today's key is only the ends'
  transforms; a timing edit could otherwise reuse a stale morph).
- Lifetimes unchanged: the source tree ends at the morph end, the target tree
  and its parts appear there.

## UI

*Turn into > TransformMatchingTex* in the timeline menu for TeX roots, listing
TeX targets; morph targets may now be objects with parts. No key overrides in
v1.

## Work breakdown

| step | content | acceptance |
|---|---|---|
| P2e.1 | clip kind, keyed animation in the adapter, schema relaxation + new rules | unit tests: keys, dissolve fallback, schema |
| P2e.2 | evaluator: tree morphs, bake key | frames vs hand-built Manim; random access; timing-edit cache test |
| P2e.3 | UI menus, acceptance, ADR 0020, docs | split two equations, morph through the UI, scrub = play, export = editor |

## Outcome

Done on 2026-10-10, as planned. The timeline offers *Turn into* on objects
with parts (not on parts) and lists only TeX targets for TransformMatchingTex,
never code layers. The showcase example now ends its equation with
`a^2 + b^2 = c^2` -> `c^2 = a^2 + b^2`.
