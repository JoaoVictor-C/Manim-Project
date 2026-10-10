# 0022. Clip parameters and overlay clips

- **Status:** Accepted
- **Date:** 2026-10-10
- **Deciders:** João Victor
- **Amends:** [0007](0007-allow-list-and-adapter-patches.md) (parameters in the allow-list)

## Context

ADR 0007 keys the allow-list by clip kind, object type and the parameters the
UI exposes — but the UI exposed none, and `params` was a free dict of Manim
keyword arguments. Useful animations need a few (where a fade comes from, the
colour of an indication). Several emphasis animations (Circumscribe, Flash,
FocusOn) draw something next to the object instead of changing it; the
evaluator drew only the animation's own mobject.

## Decision

- **Clip parameters** are registered per kind in the schema (`CLIP_PARAMS`:
  name, kind, default, limits/choices). The UI shows exactly those. Registered
  names are validated on load; a direction is a name (`"UP"`) or a vector.
  Unregistered keys still pass through to Manim, unverified, as documented.
  Changing a clip's kind drops the params the new kind does not register.
- **Overlay clips** (`ClipKindInfo.overlay`): the frame shows the object and
  the animation's mobject together, in the layer's local space, under the layer
  transform; their checkpoint is the object. In part trees the overlay joins
  the clip owner's group.
- **Type restrictions** (`ClipKindInfo.only_types`) are validated on load like
  `vector_only`.
- Forward-only animations (`Succession`) are made random-access by an adapter
  patch that snapshots before each part and restores per frame.

## Consequences

- Overlays scale and turn with their layer, unlike a script that transforms
  the object first; the editor and the export agree.
- A param the harness never sampled cannot be exposed: adding one means adding
  it to the registry, and the harness samples it.

## Evidence

- Measurements: B35 in [../logs/benchmarks.md](../logs/benchmarks.md).
- Design: [../logs/decision-sessions.md](../logs/decision-sessions.md), session 14.
- Plan: [../plans/p2g-clip-kinds.md](../plans/p2g-clip-kinds.md).
