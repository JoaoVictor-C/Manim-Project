"""Keyframed layer transforms (ADR 0004): the numpy fast path must equal Manim's methods."""

from __future__ import annotations

import math

import manim as m

from manim_studio.core.evaluator import Evaluator
from manim_studio.core.schema import Clip, Keyframe, Layer, Project
from manim_studio.render.cairo_export import make_camera, render_frame
from support import CANVAS, FRAMES, TEXT, TOLERANCE, max_diff


def test_keyframed_transform_matches_manim_methods() -> None:
    layer = Layer(
        id="a",
        spec=TEXT,
        tracks={
            "position": [Keyframe(t=0, value=(-2.0, 1.0)), Keyframe(t=1, value=(2.0, -1.0))],
            "scale": [Keyframe(t=0, value=0.5), Keyframe(t=1, value=1.5)],
            "rotation": [Keyframe(t=0, value=0.0), Keyframe(t=1, value=90.0)],
            "opacity": [Keyframe(t=0, value=1.0), Keyframe(t=1, value=0.2)],
        },
        clips=[Clip(id="c", kind="Write", start=0.2, duration=0.5)],
    )
    project = Project(canvas=CANVAS, layers=[layer])
    untransformed = Project(canvas=CANVAS, layers=[layer.model_copy(update={"tracks": {}})])
    camera = make_camera(CANVAS)
    evaluator = Evaluator(project)

    for t in reversed(FRAMES):
        got = render_frame(camera, evaluator.frame(t))
        # Reference: evaluate the local state, then transform a deep copy with Manim.
        tr = evaluator.transform_at(layer, t)
        reference = [mob.copy() for mob in Evaluator(untransformed).frame(t)]
        for mob in reference:
            mob.scale(tr.scale, about_point=m.ORIGIN)
            mob.rotate(math.radians(tr.rotation), about_point=m.ORIGIN)
            mob.shift([tr.position[0], tr.position[1], 0])
            for sub in mob.get_family():
                for attr in ("fill_rgbas", "stroke_rgbas", "background_stroke_rgbas"):
                    getattr(sub, attr)[:, 3] *= tr.opacity
        diff = max_diff(render_frame(camera, reference), got)
        assert diff <= TOLERANCE, f"t={t}: differs by {diff}"
