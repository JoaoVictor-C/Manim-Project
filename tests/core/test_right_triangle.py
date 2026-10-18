"""The right triangle object (the user's Pythagoras project needed one built by hand): a shape with
a base length and an acute angle, its right angle marked, drawn like any other shape."""

from __future__ import annotations

import math

import numpy as np
import pytest

from manim_studio.core import adapter, library
from manim_studio.core.evaluator import Evaluator
from manim_studio.core.python_export import to_python
from manim_studio.core.schema import Canvas, Clip, Layer, Project, Spec, Transform2D


def spec(angle: float = 30.0, side: float = 2.0, **style) -> Spec:
    return Spec(type="RightTriangle", params={"angle": angle, "side_length": side}, style=style)


def points(mob) -> np.ndarray:
    return np.concatenate([sub.points[:, :2] for sub in mob.family_members_with_points()])


@pytest.mark.parametrize(("angle", "side"), [(30.0, 2.0), (45.0, 3.0), (60.0, 1.5)])
def test_the_base_and_the_angle_give_the_size(angle: float, side: float) -> None:
    box = points(adapter.build_mobject(spec(angle, side)))
    assert np.ptp(box[:, 0]) == pytest.approx(side, abs=1e-6)
    assert np.ptp(box[:, 1]) == pytest.approx(side * math.tan(math.radians(angle)), abs=1e-6)


def test_it_is_centred_on_the_origin_like_every_shape() -> None:
    box = points(adapter.build_mobject(spec(30.0, 2.0)))
    assert (box.min(axis=0) + box.max(axis=0)) / 2 == pytest.approx((0.0, 0.0), abs=1e-6)


def test_the_right_angle_is_at_the_bottom_left_and_marked() -> None:
    mob = adapter.build_mobject(spec(45.0, 2.0))
    outline, *marks = mob.submobjects
    corner = outline.get_vertices()[0]
    assert corner[:2] == pytest.approx(points(mob).min(axis=0))  # the lowest-left point
    assert len(marks) == 2  # the little square: two short lines inside the corner
    assert all(np.linalg.norm(p[:2] - corner[:2]) < 1.0 for mark in marks for p in mark.points)


def test_it_can_be_filled_and_coloured() -> None:
    mob = adapter.build_mobject(spec(30.0, 2.0, fill="#ff0000", fill_opacity=0.5))
    outline = mob.submobjects[0]
    assert outline.get_fill_opacity() == pytest.approx(0.5)
    assert outline.get_fill_color().to_hex().lower() == "#ff0000"


def test_it_has_params_and_a_menu_entry() -> None:
    names = {p.name: p for p in adapter.MOBJECT_PARAMS["RightTriangle"]}
    assert names["angle"].default == 45.0 and names["side_length"].default == 3.0
    shapes = dict(adapter.LIBRARY)["Shapes"]
    assert "RightTriangle" in shapes
    assert "RightTriangle" in library._SHAPES  # themes style it like the other shapes


def test_it_is_a_layer_that_animates_and_draws() -> None:
    project = Project(
        canvas=Canvas(width_px=160, height_px=90, fps=10, duration=2.0),
        layers=[
            Layer(
                id="t",
                spec=spec(),
                base=Transform2D(position=(1.0, 0.5), rotation=90.0),
                clips=[Clip(id="c", kind="Create", start=0.0, duration=1.0)],
            )
        ],
    )
    evaluator = Evaluator(project)
    assert len(points(dict(evaluator.frame_layers(0.5))["t"])) > 0
    assert evaluator.build_errors() == {}


def test_the_readable_export_builds_the_same_shape() -> None:
    project = Project(
        canvas=Canvas(width_px=160, height_px=90, fps=10, duration=2.0),
        layers=[
            Layer(
                id="t",
                spec=spec(30.0, 2.0, fill="#00ff00", fill_opacity=0.4),
                clips=[Clip(id="c", kind="Create", start=0.0, duration=1.0)],
            )
        ],
    )
    export = to_python(project, "Tri")
    assert export.readable, export.problems
    assert "RightTriangle(" not in export.code  # not a Manim class: written out as shapes
    assert "Polygon(" in export.code


@pytest.mark.slow
def test_the_readable_export_renders_what_the_editor_shows(tmp_path) -> None:
    from tests.core.test_python_export import assert_matches_editor, rendered

    project = Project(
        canvas=Canvas(width_px=320, height_px=180, fps=10, duration=1.5),
        layers=[
            Layer(
                id="t",
                spec=spec(30.0, 3.0, fill="#00ff00", fill_opacity=0.4),
                base=Transform2D(position=(1.0, 0.5)),
                clips=[Clip(id="c", kind="Create", start=0.0, duration=1.0)],
            )
        ],
    )
    export = to_python(project, "Tri")
    assert export.readable, export.problems
    assert_matches_editor(project, rendered(export.code, "Tri", tmp_path))
