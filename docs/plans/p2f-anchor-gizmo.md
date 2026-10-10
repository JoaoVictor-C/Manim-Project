# P2f — Anchor (pivot) gizmo: implementation plan

- **Status:** In progress
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

- **Drag the pivot cross** to move the anchor; the object stays put (live
  preview, one undo step *Move anchor*, Escape cancels). The cross is grabbed
  within 6 px, after the rotate knob and corner handles and before the body.
- The cross can only be grabbed when the selected box's **longer side is at
  least 36 px**; smaller objects drag as bodies (set their anchor in
  Properties). A line's box is thin but long, so lines keep their cross.
- **Ctrl** snaps the pivot to the box's corners, edge midpoints and centre.
- **Double-click** the cross: the anchor goes to the centre of the drawing's
  box (for a code layer, of its picture, not the canvas origin).
- Properties: an **Anchor point** field in Transform (no Keys toggle), applied
  at the playhead through `set_anchor`; type 0, 0 for the default.

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
