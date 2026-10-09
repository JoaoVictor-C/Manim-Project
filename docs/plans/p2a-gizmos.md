# P2a — Transform gizmos and keyable properties: implementation plan

- **Status:** ✅ Done (2026-10-09) — `tests/ui/test_acceptance_p2a.py`
- **Date:** 2026-10-09
- **Decided in:** [decision session 8](../logs/decision-sessions.md) (Terza, `fast`, confidence 0.90)
- **ADRs:** [0016 stopwatch rule](../adr/0016-canvas-hit-testing-and-stopwatch-rule.md) (reused),
  [0018 auto-key](../adr/0018-keyable-properties-and-auto-key.md)

## Goal

Scale and rotate objects on the canvas, key every transform property, and
animate by posing with auto-key. **Done when** you can scale and rotate an
object on the canvas, undo, redo, and animate a rotation with auto-key
(acceptance test).

### Out of scope (stays on the roadmap)
- **Anchor / pivot gizmo** — the pivot is the layer position (objects are built
  centred). A movable anchor needs a schema field, a change to the evaluator's
  transform and morph baking; a pendulum or a clock hand needs it, so it is the
  next transform item.
- Non-uniform scale (the model's scale is one number), curve editor.

## Handles (`ui/gizmo.py`, pure math; drawn by the canvas)

- On the selected layer's **oriented box**: the outline's points rotated into
  the layer's frame about the pivot, their bounding box, its corners rotated
  back — handles stay on the shape when it is rotated.
- Four 8 px corner squares: **scale** = start × |p − pivot| / |p0 − pivot|,
  clamped to 0.01–100; Shift snaps to 0.1.
- A round knob 24 px beyond the middle of the top edge: **rotate** by the angle
  swept around the pivot, unwrapped; Shift snaps to 15°.
- A readout near the cursor ("125 %", "30°").
- Press priority: handles (6 px) → selected box (move) → hit test → empty.
- One undo step per drag ("Scale layer", "Rotate layer"); the stopwatch rule
  decides base vs key; refused while the layer's morph plays (B23).

## Keyable properties (Properties panel)

- Keyframes toggles for position, scale, rotation and opacity.
- A keyed property's field shows its value at the playhead; editing it sets a
  key at the playhead frame (no longer disabled).
- The panel refreshes when the playhead moves while paused.

## Auto-key (Edit > Auto-key, ADR 0018)

When on, the first edit of an **untracked** transform property at playhead
frame t creates its track with two keys — the old value at the layer's
lifetime start s, the new value at t — or one key when t ≤ s + half a frame.
Later edits add or replace keys at the playhead. Off: untracked edits change
the base (S3).

## Work breakdown

| step | content | acceptance |
|---|---|---|
| P2a.1 | `ui/gizmo.py` + handle drawing | unit tests: oriented box of rotated shapes, scale/angle from points, snapping, unwrap, degenerate (flat) shapes |
| P2a.2 | scale and rotate drags | mouse tests: corners scale, knob rotates, Shift snaps, keyed layers get keys, morph refusal, undo/redo |
| P2a.3 | keyable Properties | toggles for four properties; keyed field edit → key; refresh on seek |
| P2a.4 | auto-key | two keys vs one at the start; off = base |
| P2a.5 | acceptance + docs | scale and rotate, undo, redo; animate a rotation with auto-key |

## Outcome

Done on 2026-10-09. The stopwatch rule and auto-key live in one core function,
`edits.set_property`, used by the canvas tool and the Properties panel alike.
Keyed fields now show their value at the playhead and edit keys (they were
disabled in S3); the Keyframes toggle sits on each transform row.
