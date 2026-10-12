# 0043. Canvas interaction: parameter handles, snapping guides, several objects

- **Status:** Accepted
- **Date:** 2026-10-12
- **Deciders:** João Victor

## Context

On the canvas an object could be moved, scaled, rotated and have its pivot moved,
but its own size - a rectangle's width, a circle's radius, a line's ends, a text's
size - only changed through Properties. Moves did not line up with other objects,
and only one object could be selected. ("Handlers" in the user's request is read as
on-canvas handles; confirmation pending.)

## Decision

- **Parameter handles** (P6c.1): the selected root object shows round handles at its
  line ends and edge midpoints, placed in its own frame through its world transform at
  the playhead, so turned, scaled and keyed objects work (a drag goes back through the
  inverse). One handle per exposed parameter: Line and Arrow start and end, Connector
  offsets, Circle and Dot radius, Square side, Rectangle width and height, Star radius,
  Text/MathTex/Tex/Number font size (whole points; Shift: steps of 4), Axes width and
  height. A handle edits exactly what its Properties field edits, within the same
  limits: sizes change about the object's centre and no position or key is touched.
  A built line is re-centred, so a line end drag also shifts the layer's position (the
  base and every position key, rigidly: `edits.set_params(shift=)`) to keep the other
  end where it is - exact at all times unless rotation or scale is keyed, as for the
  anchor (ADR 0021). Handles nearer than 14 px to the object's middle or pivot are
  hidden, so a press there still moves a small object (zoom in to resize it).
  Escape cancels; a drag is one undo step. A press picks a parameter handle first, then
  a scale corner, the rotate knob, the pivot, the body.
- **Snapping guides** (P6c.1): when an object is moved or resized, its box edges and
  centre snap to the box edges and centres of the other visible objects and of the
  video frame, within 6 px; the guide is drawn; Alt (held while dragging) or View >
  Snap to Objects (Ctrl+;) turns snapping off. A handle's point snaps the same way,
  except with Shift (which steps the value). What follows the moved object (its
  connectors and traces) and the object itself are never targets.
- **Several objects** (P6c.2, after the workspace pages): the selection holds an
  ordered set of objects with a primary one; Shift+click on the canvas and Ctrl/Shift+
  click in Layers add or remove, a drag from empty canvas draws a marquee. Moving,
  Delete, the clipboard, presets and themes act on all of them (the stopwatch rule
  per layer; one undo step). Properties shows the primary object. **Arrange** aligns
  the objects to their common box (or one object to the frame) and distributes three
  or more with equal gaps.
  As built: a Shift+press on an unselected object adds it and a drag then moves all
  (Shift still locks the axis); a Shift+click without moving on a selected one takes
  it out; a plain click without moving on one of several selects only it, a plain
  drag moves them all. The marquee selects every object whose box it touches.
  Several selected hide every handle (parameter, corner, knob, pivot, motion path);
  each other object shows its outline and box. A part selected with its object (or
  a locked graph with its axes) moves once. Arrange measures the drawn boxes at the
  playhead and moves through the same rule as a drag (`MoveTool.move_by`).

## Consequences

- No resizing from the opposite edge; parameters are not keyable, so a size handle
  changes the object for its whole life.
- Editing several objects' values at once and selecting several clips come later.

## Evidence

- B60 in [../logs/benchmarks.md](../logs/benchmarks.md): 3-7 ms per handle move,
  0.6 ms for snap points, 2.3 ms to move 20 objects.
- Design: [../logs/decision-sessions.md](../logs/decision-sessions.md), session 39.
- Plan: [../plans/p6c-canvas.md](../plans/p6c-canvas.md).
