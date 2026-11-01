# 0083. A 2D camera as in Unity: size, Scene and Game views, a background, a followed layer

- **Status:** Accepted
- **Date:** 2026-10-31
- **Deciders:** João Victor
- **Extends:** [ADR 0072](0072-camera-layer.md)

## Context

The camera layer (ADR 0072) pans, zooms and rolls the view by its keys, but it was edited like any layer: a
"scale" that zooms in as it grows, no picture of where it looks, and every handle switched off while it had
moved the view, so a project with a moving camera could only be edited where the camera rests. People who know
Unity expect its 2D (orthographic) camera: an orthographic **size**, a **Scene view** where the scene is
edited and the camera is drawn as the rectangle it sees, a **Game view** that shows the picture through it, a
background colour, and a camera that can follow an object (the simplest thing a follow camera does).

## Decision

**Size.** The camera's zoom is shown as its *size*: half the height it sees, in scene units
(`size = frame_height / 2 / scale`, so a camera at rest on Manim's 8-unit frame has size 4). The **scale track
stays the stored truth** - files, keys and edits are unchanged - and Properties shows and types the size
(`evaluator.camera_size` / `camera_scale`), on the Transform row and on a scale key ("Size").
**Easing interpolates the size, not the scale** (`evaluator.camera_transform`): between two scale keys the
eased value is `1 / scale`, so a linear zoom from size 4 to size 2 passes size 3 halfway, as an animated
orthographic size does in Unity. A plain layer still eases its scale. At and outside the keys the key's own
value is used exactly, so a camera at rest is byte-identical to before. A camera scale must be above 0.

**Transform.** The camera's Properties are those of Unity's 2D camera: Transform with Position, Size and
Rotation (keyable, the stopwatch rule of ADR 0016/0018), and a Camera section; no style, opacity, anchor or
lifetime. Its own settings are `Spec.params` (all optional, omitted when default, checked by
`schema.camera_params_problem`):

- `background` - a colour that replaces the canvas background for the whole video (static). It is read in one
  place, `Project.view_background` (a hidden camera does nothing), and handed to the camera of the canvas, the
  preview process, the export, the render processes and the exact Python form alike.
- `follow` - a layer id, and `follow_offset` (x, y). The camera's position at `t` is the followed layer's pivot
  (`Evaluator.layer_frame`, the cross of its gizmo, in scene units before the camera) + the offset + the
  camera's own position, keys included: its keys are an offset from the target. The target must exist and be
  a whole object: not the camera, not a part. Deleting the target stops the following. A pinned label as
  target reads drawings, which are evaluated flat for that question (no cycle). The frame cache drops every
  frame when the camera, or what it follows, changes.

**Scene view and Game view.** View > Game View (through the camera) is on by default: the canvas is drawn
through the camera as before, with handles off and a notice that now says to switch to the Scene view. Off,
the canvas is the **Scene view**: the evaluator draws without the camera (`Evaluator.set_through_camera`),
so outlines, handles, clicking and dragging work while the camera moves, and the camera is drawn as a
**gizmo** - the rectangle it sees at the playhead (position, rotation, size, the canvas's aspect;
`ui/canvas/camera_gizmo.py`) with a camera icon and its name. It is drawn over the pasteboard too; zoom the
view out to see it whole. The icon selects the camera (as does the Layers panel); selected, a drag inside the
rectangle moves it, a corner changes the size about its centre and the knob above its top edge rolls it. Each
drag is one undo step and keys where the property is keyed, as any layer's drag. F frames the rectangle. The
preview process draws the same view (`PreviewView.through_camera`), so frames rendered ahead are those of the
view shown. The video is always the Game view.

**Python export.** The readable form still refuses a camera (ADR 0072); the exact form reproduces it,
background included.

## Consequences

- Animating Size feels like Unity; the timeline's value curve of a camera's scale still draws the scale eased
  as a plain number, so between two keys of very different sizes it is an approximation of the motion.
- A following camera's own position keys are offsets: the motion path is not drawn for it.
- The Scene view shows the camera's background colour behind the scene too, so what is not in the camera's
  rectangle is on the colour the video uses.
- The camera follows one layer's point; there is no damping, dead zone or look-ahead.
