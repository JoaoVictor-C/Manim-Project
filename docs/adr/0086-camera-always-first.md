# 0086. The camera is always the first row of the Layers panel and the Timeline

- **Status:** Accepted
- **Date:** 2026-11-01
- **Deciders:** João Victor
- **Extends:** [ADR 0072](0072-camera-layer.md), [ADR 0083](0083-unity-style-camera.md)

## Context

The camera is a layer (ADR 0072), so it sat in `Project.layers` wherever it was added and every object added
after it went on top of it. The panel and the timeline list the front first, so the camera drifted down the list
and could be dragged, moved up and down or reordered like an object. In Unity the camera is one object among the
scene's, but here it is the *view*: it draws nothing, so its place in the z-order means nothing, and a row that
moves for no reason is only noise. People look for it in one place.

## Decision

**The camera is the last layer of `Project.layers`**, which is the first row of the Layers panel and of the
Timeline (both list the front first). One place enforces it: the `Project` validator (`schema.camera_first`)
puts the camera last whenever it is not, so every way to a project - an edit, a paste, undo and redo, a file
opened, an import - ends with it first. Nothing else orders layers around it:

- a project that already complies is unchanged (the same list, so a saved file is byte-identical; the committed
  `examples/camera.json` is such a file); an older file with the camera elsewhere is normalised when it is opened,
  and the others keep their order;
- `add_layer` (and so every object added, pasted or duplicated) puts the new layer on top *under* the camera;
- `move_layer` refuses the camera (`EditError`, "The camera always stays first"); any other layer moved above it
  lands in front of the objects, just under it, so an index past the last object is not an error;
- `group_layers` refuses the camera with the same reason; the camera is never a parent or a child (ADR 0072);
- drawing is unaffected: the camera draws nothing and the evaluator composes its inverse transform into every
  object whatever its place in the list (a test renders the tour of `examples/camera.json` with the camera at the
  back and in front and compares the frames).

**The Layers panel.** The camera's row is not draggable and its tooltip says "The camera always stays first";
Up and Down are off for it with that tip, Up is off for the object just under it, a drop above it is refused
(the drop indicator shows "not allowed") and a drop on its lower half goes under it. Grouping is refused with the
same reason in the status bar (the panel has no indent). The **Timeline** has no row reordering; its camera row is
the first and its name shows the same tip. It scrolls with the other rows: pinning it while the view scrolls
would mean painting a lane outside the scene, which is not worth the cost for a lane with no bars.

## Consequences

- A script or plugin that adds a layer and then reads `project.layers[-1]` gets the camera when there is one;
  look the new layer up by its id (`edits.new_layer_id`) as the panel does.
- The z-order among objects is as before; only the camera's own place is fixed.
- Opening an old file with the camera in the middle changes its layer order in memory (and so on the next save),
  never what is drawn.
