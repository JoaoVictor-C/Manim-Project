# 0072. Camera layer: the view pans, zooms and rolls by one layer's keys

- **Status:** Accepted; extended by [ADR 0083](0083-unity-style-camera.md) (size, Scene and Game views,
  background, follow) and [ADR 0086](0086-camera-always-first.md) (always the first row)
- **Date:** 2026-10-31
- **Deciders:** João Victor

## Context

The only way to move the view was to move every object the opposite way, or to write a Python scene. A pan to follow
a graph, a slow push-in or a roll could not be keyed, and the 3D camera (ADR 0048) is a different thing: one angle
for the whole project, not a path through time.

## Decision

- A layer of type `Camera` (`Layer.is_camera`). A project has **at most one**; it is a plain root layer with no
  clips, it cannot be a parent or a child, and its scale is uniform. It draws nothing and is not in the frame.
- Its base and tracks (`position`, `scale`, `rotation`) are the view: the Evaluator composes the *inverse* of
  that transform into every object's world transform, including members of groups, children and code layers. A
  camera at rest is `None` - no arithmetic, the frame is byte-identical to a project without one.
- Rendering is the same Cairo path, so canvas, preview and export agree; the farm and the frame cache need nothing
  (editing the camera changes every frame, so `changed_spans` drops them all).
- The canvas treats a moving camera like a turned 3D one: outlines and handles are flat scene units, so they are
  hidden, and a notice says the camera moves the view.
- The readable Python export says it cannot reproduce a camera; the exact form can.
- Layers > Add > Scene > Camera adds it; a second is refused.

## Consequences

- Zoom is about the camera's position (the point it looks at stays put); roll turns the scene the other way.
- Editing objects by hand is off while the camera has moved the view at the playhead; move the playhead to a frame
  where it is at rest.
