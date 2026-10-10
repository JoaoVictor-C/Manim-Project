# P2g — More clip kinds, clip parameters and overlay clips: implementation plan

- **Status:** ✅ Done (2026-10-10) — `tests/ui/test_acceptance_p2g.py`
- **Date:** 2026-10-10
- **Decided in:** [decision session 14](../logs/decision-sessions.md) (Terza, `fast`, confidence 0.84)
- **Evidence:** benchmark B35 in [../logs/benchmarks.md](../logs/benchmarks.md)
- **ADR:** [0022 — Clip parameters and overlay clips](../adr/0022-clip-params-and-overlays.md)

## Goal

More ways to bring things in, point at them and turn them into others — and a
say in how: from which side a fade comes, what colour an indication has.
**Done when** you can split an equation, circle one of its terms with
*Circumscribe* from the timeline, recolour the circle in Properties, fade a
title in from the left, and it scrubs exactly as it plays and exports exactly
as the editor shows it.

## Kinds

| kind | category | notes |
|---|---|---|
| GrowFromEdge | appear | param `edge` |
| SpiralIn | appear | vector only (raises on images) |
| AddTextLetterByLetter | appear | Text only |
| RemoveTextLetterByLetter | disappear | Text only |
| Circumscribe | emphasis, overlay | params `shape` (rectangle/circle), `color`; Succession patch |
| Flash | emphasis, overlay | param `color` |
| FocusOn | emphasis, overlay | param `color` |
| ClockwiseTransform, CounterclockwiseTransform, FadeTransformPieces | morph | |

New params on existing kinds: FadeIn / FadeOut `shift` (none, up, down, left,
right); Indicate `color` and `scale_factor`.

**Rejected** (B35): GrowFromPoint (an absolute point is confusing under layer
transforms; Center and Edge cover it), Broadcast (111–299 ms to begin on text
stalls the first scrub into the clip), ShowPassingFlash (raises on squares, text
and images), Blink (a square does not return to its shape).

## Registry

- `ClipKindInfo.overlay` — the animation draws something besides the object.
- `ClipKindInfo.only_types` — the object types it is allowed on (letter by
  letter: Text). Validated **on load**, like `vector_only` today, so a
  hand-edited file cannot open and then fail to render.
- `CLIP_PARAMS[kind]` — pure data in the schema: name, kind (`direction`,
  `color`, `float`, `choice`), default, limits or choices. Registered names are
  validated on load (a direction is a name or a 2/3-vector, so hand-written
  files keep working); unregistered keys pass through as documented. The
  adapter converts names, hex colours and shape names to Manim values.
- Changing a clip's kind drops the params the new kind does not register
  (otherwise `Write(shift=...)` would stop the project rendering). Param edits
  are `clip` edits.
- Params are constant keyword arguments fixed when the animation begins, so the
  harness samples each registered param once and every direction choice.

## Overlays

- Objects: the evaluator draws `Group(object, overlay)` in local space, then the
  layer transform. A finished overlay clip checkpoints the **object**, not
  `anim.mobject` (otherwise later clips would start from the overlay).
- Part trees: the active overlay is appended to the clip owner's glyph group,
  so *circumscribe b^2* follows the part and its ancestors. A member with an
  active overlay is drawn even when it owns no glyphs.
- Overlays turn and scale with the layer (a Circumscribe hugs a rotated
  object). Documented deviation; export is identical.

## Succession patch

Circumscribe is a `Succession`, which needs a scene and only plays forward. The
adapter wraps it: at begin, every part is begun and finished in order with a
snapshot of the drawn family before each; per frame the snapshot of the part
holding `t` is restored and that part interpolated. B35: exact against Manim's
sequential output in reversed and shuffled order.

## Work breakdown

| step | content | acceptance |
|---|---|---|
| P2g.1 | registry fields, kinds, `CLIP_PARAMS` + validation + conversion, Succession patch | harness over registry × {Square, Text, image} × param samples; load-time validation tests |
| P2g.2 | evaluator overlays for objects and parts | frames vs hand-built Manim; checkpoint after an overlay; overlay on a fully partitioned root |
| P2g.3 | Properties param rows, kind change drops params, menus; acceptance; ADR 0022, deviations, docs | the Goal's scenario through the UI, scrub = play, export = editor |

## Outcome

Done on 2026-10-10, as planned, with one correction found by the acceptance
test: a `Succession`'s own mobject is an empty group (a scene draws the parts'
mobjects, added in `_setup_scene`), so Circumscribe drew nothing and the B35
probe for it had compared two empty frames. The patch now draws the parts'
mobjects; re-measured against Manim's Succession played forward it is exact,
and `test_circumscribe_matches_manim_played_forward` checks that the frame is
really drawn. The library's "Text" section header no longer shadows its Text
item in test menu lookups.
