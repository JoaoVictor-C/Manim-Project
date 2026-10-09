"""Qt paths must match Manim's Cairo camera (ADR 0006).

The editor draws selection outlines and hit-tests with QPainterPaths built from
Manim geometry; if they drift from the Cairo render, clicks miss and outlines
float. This pins the winding fill rule, the ``width * 0.01`` pen and the
background-stroke -> fill -> stroke order.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

from manim_studio.core.evaluator import Evaluator
from manim_studio.core.schema import Clip, Layer, Project, Spec, Transform2D
from manim_studio.render import qt_paths
from manim_studio.render.cairo_export import make_camera, render_frame
from support import CANVAS, SQUARE, TEXT

SCENES = {
    "filled-square": Layer(id="a", spec=SQUARE, base=Transform2D(rotation=20)),
    "text-with-holes": Layer(
        id="a", spec=Spec(type="Text", params={"text": "Bo8 Ag"}), base=Transform2D(scale=1.5)
    ),
    "thick-stroke-scaled": Layer(
        id="a",
        spec=Spec(type="Circle", params={"radius": 1}, style={"stroke_width": 12}),
        base=Transform2D(scale=2.0),
    ),
    "mid-write": Layer(id="a", spec=TEXT, clips=[Clip(id="w", kind="Write", start=0, duration=1)]),
}


@pytest.mark.ui
@pytest.mark.parametrize("name", SCENES)
def test_qt_paths_match_cairo(qt_app, name: str) -> None:
    project = Project(canvas=CANVAS, layers=[SCENES[name]])
    mobjects = Evaluator(project).frame(0.5)
    cairo = render_frame(make_camera(CANVAS), mobjects)[:, :, :3].astype(int)
    image = qt_paths.render_image(CANVAS, mobjects, CANVAS.width_px, CANVAS.height_px)
    qt = qt_paths.image_to_array(image)[:, :, :3].astype(int)

    diff = np.abs(cairo - qt)
    assert diff.mean() < 0.5, f"mean diff {diff.mean():.3f}"
    # Anti-aliasing differs on edges only; large differences mean a wrong fill or width.
    assert (diff.max(axis=2) > 64).mean() < 0.005
