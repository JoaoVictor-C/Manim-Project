# S3 — Canvas interaction: implementation plan

- **Status:** ✅ Done (2026-10-09) — `tests/acceptance/test_acceptance_s3.py`; B24: 18.5 ms per drag step
- **Date:** 2026-10-09
- **Decided in:** [decision session 6](../logs/decision-sessions.md) (Terza, `balanced`, confidence 0.90)
- **Evidence:** benchmarks B21–B23 in [../logs/benchmarks.md](../logs/benchmarks.md)
- **ADR:** [0016 canvas editing: hit-testing and the stopwatch rule](../adr/0016-canvas-hit-testing-and-stopwatch-rule.md)

## Goal

Click an object on the canvas to select it, see it outlined, drag it to move
it. **Done when** you can move an object, undo and redo (acceptance test).

### In scope
- Hit-testing, a shared selection, the outline overlay
- Move by dragging (Shift = one axis), arrow-key nudges
- The stopwatch rule for position, and a stopwatch toggle in Properties

### Out of scope
- Scale/rotate/anchor gizmos, auto-key, curve editor (Phase 2)
- Multi-selection, marquee selection

## Hit-testing (`render/hit_test.py`)

`hit_layers(layers_at_t, point, px_per_unit)` returns **every** layer under the
point, front-most first (the caller takes the first; Alt+click takes the one
after the current selection).

1. Bounding-box prefilter, expanded by 4 px.
2. Visibility gate: alpha must exceed `VISIBLE_ALPHA = 0.02` — an object faded
   out by a clip is not clickable even though its geometry exists (B23).
3. By class:
   - Text, Tex, MathTex: the bounding box (holes of letters count);
   - images: the image quad;
   - other vector objects: inside a visibly filled subpath (nonzero winding),
     or within `max(4 px, stroke width / 2)` of a visibly stroked curve — both in
     numpy on the cubics flattened into 8 segments each (Qt's
     `QPainterPath.contains` was planned but misreports points on some lines
     through a shape; see ADR 0016).

Cost as shipped: median 0.78 ms, at most 1.9 ms per click on the stress scene (B21).
The objects come from `Evaluator.frame_layers(t)` called at click/paint time and
never kept — they are shared render buffers (ADR 0002).

## Selection (`ui/session/selection.py`)

One `Selection` object holds `(layer_id, clip_id | None)` and emits `changed`.
The canvas, Layers panel, timeline and Properties all read and set it; it
clears when its layer or clip disappears and on New/Open. The canvas overlay
draws the selected layer's outline, a dashed bounding box and a centre cross at
the playhead (0.7 ms per frame, B22); nothing when the layer is invisible there.

## Moving (`ui/canvas/canvas.py`)

| gesture | result |
|---|---|
| press on an object | selects it (front-most hit); a press inside the selected layer's box keeps it |
| drag | coalesced like timeline drags; release = one undo step "Move layer"; Escape cancels |
| Shift while dragging | locks to the dominant axis of the whole drag |
| arrow keys | nudge 1 px (Shift: 10 px); holding a key = one undo step (auto-repeat merges) |
| Alt+click | selects the next object behind the current one |

**Stopwatch rule** (position only in S3):
- the layer has a position track → the gesture first snaps the playhead to the
  nearest frame; `set_key` writes the sampled position there plus the offset.
  A key within half a frame is replaced (keeping its ease); a new key inherits
  the previous key's ease unless that ease does not end at 1 (`there_and_back`),
  then the default;
- no track → `base.position` plus the offset; the playhead stays where it is.

A drag is **refused** on a layer whose morph (as source or target) is active at
the playhead: the morphing object would move only 7–93 % of the cursor's
distance and each step would cost 94 ms (B23). The status bar says why.
Layers invisible at the playhead can still be nudged from the keyboard.

The Properties **Position** row gets a stopwatch toggle: on = a track with one
key at the playhead holding the current value (nothing moves); off =
`clear_track`, which bakes the value at the playhead into the base position.

## Edits

| function | does | kind |
|---|---|---|
| `set_key(project, layer_id, prop, t, value)` | insert/replace a key (rules above) | transform |
| `clear_track(project, layer_id, prop, at)` | base ← value at `at`; track removed | transform |
| `Document.apply(edit, text, merge_key=None, merge=False)` | merge into the previous command with the same key | — |

## Work breakdown

| step | content | acceptance |
|---|---|---|
| S3.1 | `Evaluator.frame_layers`, `set_key`, `clear_track`, mergeable commands | parity frame/frame_layers; key insert/replace/ease rules; merge tests |
| S3.2 | `render/hit_test.py` | text bbox, image quad, rotated shape, stroke-only line, faint fill, FadeIn start not hittable, order front-to-back |
| S3.3 | `Selection` shared by all views | S2 UI tests pass with wiring changes only; every view follows a change made in any other |
| S3.4 | outline overlay | outline drawn for the selected, visible layer only |
| S3.5 | move drag, Shift, nudges, morph refusal | mouse/key tests incl. snap-to-frame and auto-repeat merge |
| S3.6 | stopwatch toggle | on/off keeps the object in place; one undo step each |
| S3.7 | acceptance + benchmark + docs | "move an object, undo, redo" through the canvas; drag step in the window ≤ 33 ms |

## Outcome

Done on 2026-10-09; 457 tests (about 40 s). Differences from the plan:

- Fills are hit-tested with a numpy winding count: Qt's `QPainterPath.contains`
  reports every point on the line through the centre of a Manim square as
  outside (S3.2). Cost as shipped: 0.8 ms per click.
- The S2 views kept their own APIs; the main window bridges them through the
  `Selection`, so the S2 widget tests did not change (S3.3).
- The canvas claims the arrow keys only while something is selected, so
  Left/Right still step frames otherwise (S3.5).
- Manim's shapes have no fill by default, so an unfilled square is selected by
  its outline (as in vector editors); once selected, a press anywhere in its
  box drags it.
