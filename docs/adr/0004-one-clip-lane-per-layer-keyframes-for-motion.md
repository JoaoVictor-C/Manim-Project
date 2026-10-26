# 0004. One clip lane per layer; motion and style as keyframes

- **Status:** Accepted
- **Date:** 2026-10-09
- **Deciders:** João Victor

## Context

In Premiere/After Effects users stack effects freely. In Manim, every
`Animation.interpolate(alpha)` rewrites the mobject's point and colour arrays
from its own starting copy, so two concurrent animations on one mobject are two
writers to the same arrays: the last one wins. Manim defines no composition.

## Decision

- Each **layer** holds one object, a lifetime, keyframe tracks and **one lane of
  clips that may not overlap** (`Layer` validator in `core/model/schema.py`).
- **Motion and style** — position, scale, rotation, opacity (more later) — are
  **keyframe tracks**, applied after the clip as a layer transform. They
  compose with any clip.
- Parallelism across layers is unrestricted (equivalent to `play(a, b)`).
- Layer order is z-order (first = back).
- Opacity keyframes multiply, so they compose with FadeIn/FadeOut.

## Consequences

- No animation compositing to invent or maintain.
- Manim's motion animations (Rotate, Shift, `.animate`) are offered as keyframe
  presets, not clips.
- Animating parts of an object (one term of an equation) needs child layers —
  see ADR 0012.

## Alternatives considered

- **Allow overlap with a composition rule** — would mean re-implementing
  animation semantics; results depend on evaluation order.
- **Premiere-style shared tracks** — forces a separate z-order system and forbids
  legitimate parallel animations on one track.

## Evidence

- `tests/core/engine/test_transforms.py`: the numpy transform path equals Manim's
  `scale`/`rotate`/`shift` with an active Write clip underneath.
