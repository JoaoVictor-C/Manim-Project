# 0007. Allow-list and adapter patches for unsafe animations

- **Status:** Accepted
- **Date:** 2026-10-09
- **Deciders:** João Victor

## Context

ADR 0002 requires every exposed animation to be random-access-safe: the frame at
alpha must not depend on earlier frames. The test harness found one that is not:
`Wiggle` on multi-part mobjects pivots around the *current* centre of the whole
object, which drifts as submobjects update, so even vanilla Manim's output
depends on frame rate. Options were to hide such animations, replay them
sequentially from a checkpoint, or patch them.

## Decision

- The adapter registry (`CLIP_KINDS`, `allowed_clip_kinds`) is the
  **allow-list**, keyed by (clip kind, mobject type, parameters exposed in the
  UI). A combination is exposed only if it passes the random-access harness.
- Failures are fixed by **adapter patches** that pin the intended semantics
  (Wiggle: pivot at the clip's starting centre). Every patch is listed in
  [../deviations.md](../deviations.md).
- Content and emphasis clips **clamp eased alpha to [0, 1]**; morphs and
  keyframes may overshoot.
- **Replay from checkpoint** is reserved for future "simulated" layers
  (updaters, `TracedPath`), where history dependence is the feature.
- The UI's clip menus and parameter ranges will be generated from the registry,
  so it cannot offer an unverified combination.

## Consequences

- Exported video can differ slightly from a hand-written Manim scene for patched
  animations; this is documented.
- Adding a clip kind = add to the registry + harness passes; no ADR needed.

## Evidence

- `tests/core/test_random_access.py` (parametrised over the registry).
