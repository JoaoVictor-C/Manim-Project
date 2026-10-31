# 0074. Layout guides: lines on the canvas that moves snap to, never drawn in the video

- **Status:** Accepted
- **Date:** 2026-10-31
- **Deciders:** João Victor

## Context

Moved objects snap to the other objects and to the frame (ADR 0043), but a layout often wants lines that no object
marks: a margin kept clear on every side, the thirds of the frame, a column for a list of steps. Placing objects on
them meant typing positions or adding a throwaway shape to snap to.

## Decision

- `Project.guides` holds `Guide`s: an id (unique among every id in the project), an axis (`"x"` a vertical line
  at x = position, `"y"` a horizontal one) and a position in scene units, with an optional name. A project without
  guides saves as before: the list (and an empty name) is left out of the file.
- Edits (`core/editing/edits.py`, each one undo step): `add_guide`, `move_guide` (and rename), `remove_guide`,
  and the sets `guides_from_margins(project, margin)` (four lines `margin` inside the frame's edges and the two
  through its centre), `guides_for_thirds` and `guides_for_centre`. A guide is never doubled: one on the same axis
  at the same place is kept, and an edit that would add nothing is refused.
- Guides draw nothing. The evaluator, the export and the Python export never read them, and the frame cache
  treats them like markers: a change to the guides alone changes no span, so no frame is rendered again.
- **View > Layout Guides** (remembered like the other view toggles, off by default) draws them as thin lines
  across the video frame, and while it is on, moved objects and dragged handles snap to them exactly as to
  other objects (`snap_guides.targets` takes them as lines); Alt or View > Snap to Objects turns snapping off.
  Hidden guides do not snap.
- **View > Layout Guides...** lists the guides and adds a vertical or horizontal one at a typed position, moves
  or deletes the selected one, and has **Margins...**, **Thirds** and **Centre**. Opening it turns the guides on.

## Consequences

- Guides are placed by number, not by dragging from the canvas edge; the dialog is the one place to edit them.
- Guides belong to the project (they travel with the file and come back with a snapshot), not to the editor.
