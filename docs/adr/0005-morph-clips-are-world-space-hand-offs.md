# 0005. Morph clips are world-space hand-offs

- **Status:** Accepted
- **Date:** 2026-10-09
- **Deciders:** João Victor

## Context

With ADR 0004, keyframes are applied after clips. A naive `Transform(A → B)`
inside layer A would then be pushed off target by A's position keyframes, and
A's colour keyframes would hide the colour change the morph performs.

## Decision

Morph clips (`Transform`, `FadeTransform`, `TransformMatchingShapes`) live on the
source layer's lane with `to_layer` set, and:

- take A in **world space** at the clip start (A's transform baked in) and B in
  world space at the clip end;
- interpolate a temporary mobject between them, with **no keyframes applied**;
- end A's lifetime and start B's at the clip end (ReplacementTransform semantics).

## Consequences

- A morph always lands exactly on B, with B's colours.
- Keyframes on A or B inside the morph range have no effect (the UI should show
  them disabled).
- Editing B's transform must refresh A's morph cache (ADR 0008).
- Nothing may follow a morph on A's lane, and a layer may be the target of only
  one morph; both are rejected when the project loads (added 2026-10-09 after a
  clip placed after a morph crashed the evaluator).

## Evidence

- `tests/core/test_random_access.py::test_morph_random_access`
- `tests/core/test_invalidation.py::test_morph_target_edit_refreshes_source`
- `tests/core/test_schema.py::test_clips_after_a_morph_are_rejected`
