# P2f — Anchor (pivot) gizmo: implementation plan

- **Status:** ✅ Done (2026-10-10) — `tests/ui/test_acceptance_p2f.py`
- **Date:** 2026-10-10
- **Decided in:** [decision session 13](../logs/decision-sessions.md) (Terza, `fast`, confidence 0.82)
- **Evidence:** benchmark B34 in [../logs/benchmarks.md](../logs/benchmarks.md)
- **ADR:** [0021 — The anchor point](../adr/0021-anchor-point.md)

## Goal

Rotate and scale an object about any point, not only its centre — pendulums,
clock hands, hinges, doors. **Done when** you can drag the pivot cross of a line
to its top end without the line moving, key its rotation, and it swings about
that end in the editor and in the export.

## Model

- `Transform2D.anchor: Vec2 = (0, 0)` in the layer's own units. **Base only**:
  it has no track, is never keyed and never auto-keyed.
- `world(p) = A (p - P) + P + position`, `A` = rotation × scale; the pivot
  `P` is the anchor for objects and code frames, the rest centre + anchor for
  parts. Anchor (0, 0) is exactly the old transform (B34).
- The world pivot is `anchor + position` (carried by the ancestors for parts)
  and does not move when the layer rotates or scales.
- The format change is additive: old files load with the default, and the
  default is not written, so files without anchors save unchanged.
  `schema_version` stays 1.

## Moving the anchor

`edits.set_anchor(project, layer, anchor, t)` keeps the drawing where it is:
it adds `d = (I - A_t)(old - new)` to the base position and to **every**
position key (a rigid shift of the path). It never creates keys.

- Exact at every time when rotation and scale are not keyed (B34: 1e-14),
  also with keyed positions and any ease (both ends of each segment move by d).
- With keyed rotation or scale the drawing is kept exactly at `t` only; the
  status bar says so. Set the anchor before keying rotation.

## Gizmo

- **Ctrl+drag the pivot cross** (within 6 px) to move the anchor; the object
  stays put (live preview, one undo step *Move anchor*, Escape cancels).
  Without Ctrl a press on the cross moves the object, as before.
- **Shift** snaps the pivot to the box's corners, edge midpoints and centre
  (Shift snaps scale and rotation too).
- **Ctrl+double-click** the cross: the anchor goes to the centre of the
  drawing's box (for a code layer, of its picture, not the canvas origin).
- Properties: an **Anchor point** field in Transform (no Keys toggle), applied
  at the playhead through `set_anchor`; type 0, 0 for the default.
- *Changed during P2f.2:* the session chose a plain drag on the cross, guarded
  to boxes whose longer side is ≥ 36 px. Four acceptance tests (S3, P2b, v1)
  then failed: each adds an object and drags it **by its middle**, which is
  exactly where a new object's cross sits. Moving the anchor is rare, moving
  the object is common, so the anchor needs Ctrl and the size guard is gone.

## Evaluator

- `layer_transform` carries the base anchor into every sampled transform
  (otherwise it would be dropped).
- `_affine` adds the anchor to the pivot, so objects, parts and code frames all
  follow it; morph ends bake through Transform2D equality as before.
- `layer_frame` returns the world pivot, so the scale and rotate handles turn
  about it.

## Work breakdown

| step | content | acceptance |
|---|---|---|
| P2f.1 | schema field, evaluator pivot, `set_anchor` | unit tests: anchor 0 = old, pivot fixed under rotation, compensation (base, keyed position, keyed rotation warning, no keys made), parts under a rotated parent, file unchanged without anchors |
| P2f.2 | canvas: drag/snap/reset the cross; Properties field | tool tests: drag keeps the image, Ctrl snaps, the 36 px guard, double-click centres, one undo step |
| P2f.3 | acceptance, ADR 0021, docs | the pendulum: anchor dragged to the top of a line, rotation keys -30 → 30 → -30, the top stays fixed in every frame, export matches the editor |

## Outcome

Done on 2026-10-10. Two changes from the session's plan, both forced by tests:

- the anchor moves with **Ctrl+drag** on the cross, not a plain drag (see
  *Gizmo*): four acceptance tests drag new objects by their middle;
- the pivot snaps to the **unpadded** box: thin shapes get a 12 px minimum
  box for their handles, and the pendulum test snapped beside the line's end
  instead of onto it.
