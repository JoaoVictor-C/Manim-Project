# 0046. Readable Python export of keyframed layers

- **Status:** Accepted
- **Date:** 2026-10-17
- **Deciders:** João Victor
- **Amends:** [0031](0031-python-export.md)

## Context

ADR 0031 wrote a project with any keyframed layer in the exact form (a scene that needs Manim
Studio). Seven of the 32 built-in presets write keys (Pop in, Pulse, Drift up, Bounce, Spin,
Grow, Shrink), so one of them - Pop in is on the golden path - made a whole project exact, and
`examples/euler.json` was exact only because of its keys. In the editor a layer is drawn as its
clips leave the object, then moved, scaled, turned and faded by its keys: frame = transform(t)
applied to clip_state(t). Translating keys into `.animate` calls cannot reproduce that: Manim
interpolates points linearly (a keyed turn would cut a chord), simultaneous position, scale and
rotation keys would not compose like the editor's affine, and `.animate` cannot overlap a clip on
the same object.

## Decision

- **Keys as data, drawn by a helper.** A readable file with keyed layers defines a small `Keyed`
  helper (a `Group`, written once like the other helpers). `circle_keyed = Keyed(self, circle,
  scale=[(1.0, 0.6, smooth), ...])` keeps each keyed property as `(time, value, ease)` keys (a
  curved position path adds the keys' tangents and a `curve_point` helper), the unkeyed ones as
  constants. Its dt updater redraws, at every frame, a copy of `circle` through the transform
  sampled with the editor's rules (`layer_transform`: hold, ease, arc-length curved segments,
  anchor) at the frame's own time - `self.renderer.time` rounded to the frame grid, so a key whose
  ease jumps (`there_and_back`) is sampled as the editor samples it.
- **The object stays out of the scene.** Manim adds whatever an animation plays on to the scene,
  so a keyed layer's clips are written `self.play(circle_keyed.clip(FadeIn(circle)))`: `KeyedClip`
  drives the animation on the object, plays on a stand-in, adds the drawing for an introducer and
  removes it for a remover, draws an overlay (Flash, Circumscribe, FocusOn) through the layer's
  transform while it plays, and never runs the animation's own updaters (the editor never does).
- **Manim's update order** (B64): in a frame, every animation interpolates, then mobject updaters
  run, then the frame is drawn - so the drawing's updater sees the clip's state of that frame.
  Manim flattens what it draws when a play begins, so the previous drawing is emptied, not
  dropped.
- **Morphs** from a keyed layer start from its drawing at the clip's start (`circle_keyed.still(t)`
  takes its place in the scene), as the editor's world-space hand-off does. A keyed layer as the
  path of a move is placed where its keys put it as the move starts.
- **Still exact, with the reason said:** a keyframed connector, a connector to a keyframed object
  (its drawing is redrawn after the connector reads it), a keyframed object moving along a path (its
  path would be in moving units), a morph into a keyframed object, and a keyframed object morphing
  during other animations (the drawing is taken when its play starts).
- A layer with a spotlight (FocusOn) is drawn through `Keyed` too when nothing above stops it: the
  editor closes the spotlight on the object's own origin, Manim's moves it from the frame centre.
- Keyed layers may have clips on a turned or scaled base: the helper applies the transform after
  them.
- **Waits are counted in frames**, for every readable file: Manim draws `ceil(run_time * fps)`
  frames for a play, so after a clip ending between frames the next wait covers exactly the frames
  left; a wait's time is the timeline's interval when Manim draws it as that many frames both held
  and frame by frame, else the nearest time that is (`# 14 frames at 10 fps`).
- Files with keyed layers set `config.disable_caching = True`: the drawing depends on the scene
  clock, which Manim's play cache does not see.

## Consequences

- Every built-in preset on a square and on a text, and the committed euler example, export
  readable; rendered by Manim their frames match the editor's (worst mean 1.2 levels, h264 noise).
- Readable files with keys carry about 120 lines of helpers; they still need only Manim.
- The same helper could draw unkeyed layers whose clips act on a turned or scaled object (G3b);
  that stays exact for now.

## Evidence

- B64 in [../logs/benchmarks.md](../logs/benchmarks.md); `tests/core/test_python_export_keyed.py`.
- Plan: [../plans/golden-path.md](../plans/golden-path.md) (G3a); design:
  [../logs/decision-sessions.md](../logs/decision-sessions.md), session 42.
