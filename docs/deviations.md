# Deviations from vanilla Manim

Places where Manim Studio deliberately renders differently from a hand-written
Manim scene, so that every frame can be computed in any order (scrubbing).
Each entry is enforced in `src/manim_studio/core/engine/adapter.py` and covered by
`tests/test_random_access.py`.

## Wiggle pivots around the starting centre

**Manim:** `Wiggle.interpolate_submobject` scales and rotates each submobject
around `self.mobject.get_center()` — the *current* centre of the whole object.
On multi-part objects (Text, MathTex) earlier submobjects have already moved in
the same frame, so the centre drifts and every frame depends on the previous
one. Manim's own output therefore varies slightly with the frame rate.

**Manim Studio:** `scale_about_point` and `rotate_about_point` default to the
object's centre at the start of the clip. Single-part objects are unaffected.

## Content and emphasis clips clamp alpha to [0, 1]

An easing curve that overshoots (e.g. `cubic-bezier(0.34, 1.56, 0.64, 1)`)
would make `Create`/`Write` draw past their end. Content and emphasis clips
clamp the eased alpha; morph clips and keyframes may overshoot.

## Circumscribe plays its parts from snapshots

**Manim:** `Circumscribe` is a `Succession` (draw the frame, then remove it).
A Succession needs a scene and only moves forward: it finishes each part as
time passes it, so it cannot go back to an earlier alpha.

**Manim Studio:** the adapter begins and finishes every part once, keeping a
snapshot of the drawn frame before each; a frame restores the snapshot of the
part holding its time and interpolates that part. The frames equal Manim's
sequential output (B35); scrubbing back now works.

## Overlays turn and scale with their layer

Circumscribe, Flash and FocusOn draw something next to the object. Like every
clip (ADR 0004) they play in the layer's own space, so a layer scaled 3x gets
3x longer flash lines and a rotated layer gets a turned frame — a script that
scales or rotates the object first draws them at their usual size, axis-aligned.
The editor and the export agree.

## Smart morphs pair pieces themselves (opt-in per clip)

**Manim:** `Transform` aligns its two ends in order: submobjects, subpaths and points by index,
from wherever each outline starts, and blends colours in sRGB.

**Manim Studio:** a Transform, ClockwiseTransform or CounterclockwiseTransform clip with
`match: "smart"` (what the editor gives new morphs, ADR 0056) is fed ends aligned by
`core/engine/morph.py` - pieces paired by place, size and outline, holes with holes, loops started where
they travel least and cut at each other's corners - and blends colours in OKLab, with each end
drawn exactly. Clips without the param (older files, imported scenes) are Manim's own Transform,
bit for bit. A project with a smart morph exports as the exact scene.

## Robustness patches (output unchanged)

- **MoveAlongPath measures its path once.** Manim's `point_from_proportion`
  measures every curve of the path on every frame (23.6 ms on a 399-curve
  graph); the adapter's `TabledMoveAlongPath` builds an arc-length table when
  the clip begins and gives the same points (B38, `tests/core/features/test_paths.py`).

- **Half-written LaTeX renders are compiled again.** Manim reuses
  `<hash>.svg` whenever it exists; a process killed while writing it (a build
  worker past its timeout) left a truncated file that failed that formula for
  good. The adapter wraps `tex_to_svg_file`: an SVG that does not end with
  `</svg>` is deleted and compiled again (`tests/core/engine/test_adapter.py`).
- **Traced paths have no corner at the end of a play.** Manim's `TracedPath`
  adds its point on every frame and once more after each `play()` ends (the end
  state, which is never shown as a frame). The editor has no `play()` calls: a
  trace is the polyline through its target's point on every frame (ADR 0033),
  identical to Manim's within one play (B46). `dissipate` keeps the last
  D x fps frames; Manim removes one curve per update, so its trail can be a few
  corners shorter across plays.
- **Manim's own renders play sound 21 ms late; the editor's export does not.**
  Videos written by `manim render` (including exported Python scenes) start
  their AAC track 1024 samples late: the encoder's priming is not trimmed. The
  editor's export aligns the sound to the sample (B47, ADR 0034).
- **A turned camera pans the picture, not the point it turns about.** Manim's
  `ThreeDCamera` subtracts `frame_center` before turning the points and again
  when it maps them to pixels, so moving its centre moves the picture twice as
  far and changes the angle. The canvas's pan (ADR 0023) under a turned camera
  (ADR 0048) uses `StudioThreeDCamera`, which turns the scene about its origin
  and only shifts the picture; at the centre (0, 0) - every export - it is
  Manim's camera exactly.
