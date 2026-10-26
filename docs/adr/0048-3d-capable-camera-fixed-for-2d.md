# 0048. 3D-capable project, camera fixed for 2D

- **Status:** Accepted
- **Date:** 2026-10-18
- **Deciders:** João Victor
- **Decided in:** [decision session 43](../logs/decision-sessions.md) (P7.5)

## Context

The user asked whether the editor should be "always 3D like Unity, with the camera fixed for 2D".
Every frame today is drawn by Manim's 2D `Camera`, in three places that must agree bit for bit:
the canvas, the render-ahead process (ADR 0028, its frames are shown in place of live ones) and
the video export. B65 measured Manim's `ThreeDCamera` at its default orientation (phi = 0,
theta = -90 degrees) on the showcase project: pixel-identical to the 2D camera (maximum
difference 0 on 12 drawn frames), but 7.8-8.7 ms per frame against 6.2-7.1 ms (about 25 % more).
Tilting it 60 degrees changes the picture (mean difference 5.9). Selection outlines, handles,
hit-testing (ADR 0016, 0043), the motion path and F framing all work in flat scene units.

## Decision

- **The project has a camera**: `Project.camera = Camera(phi, theta, gamma)`, Manim's
  `ThreeDCamera` angles in degrees (phi 0-180, theta and gamma -180-180, unknown fields refused).
  Nothing else (no zoom, no focal distance): Manim's defaults draw the default view, and the
  canvas's own zoom and pan stay editor state (ADR 0023).
- **The default is today's view** (0, -90, 0), `Camera.is_default` compares exactly. A default
  camera is **not saved** (`Project._omit_unused`, the pattern of `Keyframe._omit_absent_tangents`),
  so files without the field load as the default and save byte-identically; examples and golden
  files do not change.
- **One camera function**: `render.preview.scene_camera(view, camera)` serves the canvas
  (`preview_camera`), the render-ahead process and the export (`make_camera(canvas, camera)`).
  For the default camera it builds exactly the 2D `m.Camera` of before - same class, same
  arguments - so default frames are bit-identical and no slower. Otherwise it builds
  `StudioThreeDCamera`, a `ThreeDCamera` whose `frame_center` is a pan of the picture: Manim's own
  subtracts the centre twice (before turning the points and again when mapping them to pixels),
  so a pan moved the picture twice as far and changed the angle. At the centre (0, 0) - the
  export - it is exactly Manim's camera, so a `ThreeDScene` draws the same picture.
- **What is drawn over the scene stays flat**: `render_frame(camera, mobjects, overlay)` takes the
  evaluator's overlay (burned-in subtitles, ADR 0035) apart and makes it Manim's fixed-in-frame
  mobjects under a turned camera. Code layers' frames (ADR 0019) are painted through the
  camera's projection of three corners (an affine map, as Manim draws images); seen edge on,
  nothing is painted.
- **Invalidation**: a camera change changes every frame: `camera` is not in `frame_cache`'s
  not-drawn parts (so `changed_spans` is None), `edits.classify` reports `spec` for every layer,
  `edits.set_camera(project, **angles)` is a pure validated edit (`reset_camera` returns to the
  default); the preview process rebuilds its camera when the project's camera changes.
- **The canvas while the camera is turned** shows the frame from the camera but no selection
  outline, handles, parameter handles or motion path; clicks and drags on the canvas do nothing
  (the tool would hit-test flat units where the picture is not) and F shows the whole frame. A
  notice on the canvas says so; objects are selected in the Layers panel and edited in
  Properties. Reset Camera brings every handle back.
- **UI**: Properties, with nothing selected, has a Camera group (Tilt, Turn, Roll and Reset
  Camera) under the scene settings; each change is one undo step.
- **Python export** (ADR 0031): the readable form writes `class Name(ThreeDScene)` and
  `self.set_camera_orientation(phi=... * DEGREES, theta=..., gamma=...)` (angles applied as the
  editor applies them, `value * DEGREES`); the exact form's `StudioScene` picks
  `StudioThreeDCamera` at the project's angles. A default camera exports byte-identically to
  before.

## Consequences

- 2D is unchanged: same frames, same speed (the 2D camera keeps drawing). A turned camera costs
  what B65/B68 measured (about 25-70 % more per frame, depending on the scene).
- The editor is not yet a 3D editor: everything lies on the z = 0 plane, and while the camera is
  turned the canvas is a viewer, not an editing surface.
- Deliberately not done (P8, with the first 3D content): z coordinates and 3D transforms, 3D
  mobjects and shading, a camera that animates (keys on phi/theta/gamma), zoom/focal distance,
  handles and hit-testing through the projection, Unity's tool modes and a Scene view / Game view
  split.

## Alternatives considered

- **Always draw with `ThreeDCamera`** - identical pixels but ~25 % slower on every frame of every
  2D project for no visible gain.
- **Draw handles through the projection now** - possible for points, but hit-testing, snapping and
  drag deltas in a projected plane are P8's work; wrong handles are worse than none.
- **Camera in `Canvas`** - the canvas is the output format (size, fps, background); the camera is
  what the scene is seen from, and its default must be omitted from files on its own.

## Evidence

- Tests: `tests/core/features/test_camera.py` (default frames equal a copy of the pre-P7.5 camera code bit
  for bit on the showcase, framed by the canvas and the export; a tilted camera matches Manim's
  own `ThreeDCamera`; pans; flat subtitles; code frames; invalidation; the export; Python export),
  `tests/ui/canvas/test_camera_ui.py` (Properties, the canvas, no handles or clicks while turned,
  render-ahead frames equal live ones, the preview process's renderer).
- Benchmarks: B65, B68 in [logs/benchmarks.md](../logs/benchmarks.md).
- Source: Manim 0.22 `camera/three_d_camera.py` (`project_points` subtracts `frame_center`;
  `Camera.points_to_pixel_coords` subtracts it again; `reset_rotation_matrix` runs at capture).
