# Deviations from vanilla Manim

Places where Manim Studio deliberately renders differently from a hand-written
Manim scene, so that every frame can be computed in any order (scrubbing).
Each entry is enforced in `src/manim_studio/core/adapter.py` and covered by
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
