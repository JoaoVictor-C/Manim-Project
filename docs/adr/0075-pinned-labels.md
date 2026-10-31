# 0075. Pinned labels: a label follows an object through every move, at a fixed offset

- **Status:** Accepted
- **Date:** 2026-10-31
- **Deciders:** João Victor

## Context

A label on a moving object ("v", "F = ma", a name over a point) had to be keyed by hand at every key of the object,
or made a child - but children (ADR 0024) and groups (ADR 0050) carry their members' rotation and scale too, so a
label on a turning or growing object turned and grew with it, and a group's members cannot keep their own place
next to one member. Connectors (ADR 0036) already read another layer's drawing at every frame; a label needed the
same thing for its place.

## Decision

- `Layer.pin: Pin | None` (left out of the file when None): `target` (a layer id), `anchor` (`"top"`, `"bottom"`,
  `"left"`, `"right"` or `"centre"`), `follow_rotation` and `follow_scale` (both off by default, left out when off).
- Only a whole Text, MathTex or Tex object can be pinned (not a part, not an object on axes, not in a group). Its
  target is any layer a connector could join (not itself, a traced path, a connector or a code layer), not the
  camera, not one of the label's own parts, and pins never go round in a circle. The project refuses anything else
  when it is loaded.
- **The offset is the label's own position.** While pinned, its position (base and keys) is measured from where the
  pin puts it, so the existing machinery works unchanged: a canvas move changes the offset (`layer_frame` maps a
  move through the pin's frame), position keys animate the offset, the motion path is drawn from the pin. Pinning a
  label that was not pinned sets the offset (default 0, 0) and drops its position keys, which placed it in the
  scene; pinning again keeps them. Its rotation, scale and opacity stay its own.
- The Evaluator places it (`_pin_frame`), one path for canvas, preview, serial export and the render farm: at each
  frame it takes the points the target is drawn with (as a connector does; a group's are its objects', the camera
  taken back out), boxes them - in the target's own rotation when the label follows it - and sets the label's rest
  box `PIN_GAP` (0.25) outside the anchor side, centred along it ("centre": centred on it). Following rotation or
  scale adds the target's world rotation and its uniform scale (the square root of its determinant) to the label's
  frame, offset included. A target that draws nothing at a frame (not yet appeared, hidden) is the point at its
  origin. The pin enters a morph's baked ends and a trace's signature, so neither keeps a stale place.
- Edits (`core/editing/edits.py`, one undo step each): `pin_label(project, label_id, target_id, anchor, offset,
  follow_rotation=, follow_scale=)` and `unpin_label(project, label_id, position=None)`. With a `position`
  (`Evaluator.unpinned_position` at the playhead, as the window passes it) the label stays where it is drawn and its
  offset keys go; without, the offset becomes its place in the scene. A pin edit is a `transform` edit: nothing is
  rebuilt.
- What happens to the target: deleting it (or ungrouping a group the label is pinned to) unpins the label, which is
  kept; grouping the target keeps the pin; grouping a pinned label is refused ("unpin it to group it"). Copy and
  duplicate remap the pin to a copied target, keep it on the same target when only the label is copied, and unpin it
  with a note when the target is not in the project pasted into.
- Frame cache: a label is redrawn when its pin or anything its target is drawn from changes (`changed_spans` adds
  the labels pinned to a changed layer, or to the group holding one).
- The readable Python export says it cannot reproduce a pinned label; the exact form, which runs the Evaluator, can.
- **Layers > right-click a text > Pin to...** opens a small chooser (target, side, "Turn with it", "Grow and shrink
  with it"); on a pinned label it edits the pin, and **Unpin** appears.

## Consequences

- While the target is revealed by a clip that grows its drawing (Write, Create), the label moves with the growing
  box; it settles where the drawing ends. Pinning to the object's rest box instead would miss clips that move it.
- The target is evaluated twice in a frame that draws both (once for its box): fine for objects, noticeable only for
  very heavy targets.
- Changing a pinned label's anchor (its pivot) does not move it: the pin places its rest box.
