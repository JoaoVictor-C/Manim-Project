"""Parameter handles' geometry (P6c.1, ADR 0043): where they sit and what a drag means. No Qt."""

from __future__ import annotations

import math

import numpy as np
import pytest

from manim_studio.core import adapter
from manim_studio.core.schema import Spec
from manim_studio.ui import param_handles as ph

EYE, ZERO = np.eye(2), np.zeros(2)


def turned(degrees: float, scale: float) -> np.ndarray:
    a = math.radians(degrees)
    return scale * np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])


def handles(spec: Spec, a=EYE, b=ZERO) -> dict[str, ph.ParamHandle]:
    points = np.concatenate(
        [sub.points[:, :2] for sub in adapter.build_mobject(spec).family_members_with_points()]
    )
    return {h.param: h for h in ph.object_handles(spec, points, a, b)}


def test_a_rectangle_has_width_and_height_handles_on_its_edge_midpoints() -> None:
    found = handles(Spec(type="Rectangle", params={"width": 3.0, "height": 1.0}))
    assert set(found) == {"width", "height"}
    assert found["width"].local == pytest.approx((1.5, 0.0), abs=1e-6)
    assert found["height"].local == pytest.approx((0.0, 0.5), abs=1e-6)


def test_handles_sit_in_the_layer_frame_turned_scaled_and_moved() -> None:
    a, b = turned(90, 2.0), np.array([1.0, -1.0])
    width = handles(Spec(type="Rectangle", params={"width": 3.0, "height": 1.0}), a, b)["width"]
    assert width.world == pytest.approx((1.0, -1.0 + 3.0), abs=1e-6)  # local +x 1.5 -> world up 3
    assert width.to_local(width.world) == pytest.approx(width.local, abs=1e-9)


def test_a_size_grows_about_the_centre_so_the_edge_follows_the_handle() -> None:
    width = handles(Spec(type="Rectangle", params={"width": 3.0, "height": 1.0}))["width"]
    assert ph.value_at(width, (2.0, 0.3)) == pytest.approx(4.0)  # the edge moved 0.5: both sides grow
    assert ph.value_at(width, (-100.0, 0.0)) == 0.01  # the field's own limits
    assert ph.value_at(width, (100.0, 0.0)) == 50.0
    assert ph.value_at(width, (1.87, 0.0), step=True) == pytest.approx(3.7)  # Shift: the field's step


def test_a_circle_radius_follows_the_handle_exactly() -> None:
    radius = handles(Spec(type="Circle", params={"radius": 1.25}))["radius"]
    assert radius.local == pytest.approx((1.25, 0.0), abs=1e-6)
    assert ph.value_at(radius, (2.0, 0.0)) == pytest.approx(2.0)
    dot = handles(Spec(type="Dot"))["radius"]
    assert ph.value_at(dot, (0.0, 0.0)) == 0.01


@pytest.mark.parametrize(
    ("spec", "param", "edge"),
    [
        (Spec(type="Square", params={"side_length": 2.0}), "side_length", 1.0),
        (Spec(type="Axes"), "x_length", None),
        (Spec(type="Star"), "outer_radius", None),
    ],
)
def test_each_size_handle_is_on_the_drawing_edge(spec, param, edge) -> None:
    points = np.concatenate(
        [sub.points[:, :2] for sub in adapter.build_mobject(spec).family_members_with_points()]
    )
    handle = handles(spec)[param]
    assert handle.local[0] == pytest.approx(points[:, 0].max(), abs=1e-6)
    if edge is not None:
        assert handle.local[0] == pytest.approx(edge, abs=1e-6)


def test_a_star_and_a_text_scale_with_the_handle_distance() -> None:
    star = handles(Spec(type="Star", params={"outer_radius": 1.0}))["outer_radius"]
    assert ph.value_at(star, star.local * 1.5) == pytest.approx(1.5)
    text = handles(Spec(type="Text", params={"text": "Hi", "font_size": 48}))["font_size"]
    assert ph.value_at(text, text.local * 2) == 96.0
    assert ph.value_at(text, text.local * 1.013) == 49.0  # whole points
    assert ph.value_at(text, text.local * 1.05, step=True) == 52.0  # Shift: steps of 4
    assert ph.value_at(text, text.local * 0.001) == 4.0  # the field's minimum
    assert ph.value_at(text, -text.local) == 4.0


def test_axes_have_width_and_height_handles() -> None:
    found = handles(Spec(type="Axes", params={"x_length": 6.0, "y_length": 4.0}))
    assert ph.value_at(found["x_length"], found["x_length"].local + np.array([0.5, 0.0])) == pytest.approx(
        7.0
    )
    assert ph.value_at(found["y_length"], found["y_length"].local + np.array([0.0, -0.5])) == pytest.approx(
        3.0
    )


def test_a_line_has_a_handle_on_each_end_of_its_centred_drawing() -> None:
    spec = Spec(type="Line", params={"start": [0.0, 0.0], "end": [2.0, 2.0]})
    found = handles(spec)
    assert found["start"].local == pytest.approx((-1.0, -1.0), abs=1e-6)  # drawn centred on its middle
    assert found["end"].local == pytest.approx((1.0, 1.0), abs=1e-6)
    assert ph.value_at(found["end"], (1.5, 1.0)) == pytest.approx((2.5, 2.0))
    assert found["end"].other == (0.0, 0.0)


def test_shift_turns_a_line_end_in_45_degree_steps_about_the_other_end() -> None:
    end = handles(Spec(type="Line", params={"start": [0.0, 0.0], "end": [2.0, 0.0]}))["end"]
    x, y = ph.value_at(end, (3.0 - 1.0, 0.3), step=True)  # (3, 0.3) in params: drawn 1 left
    assert math.hypot(x, y) == pytest.approx(math.hypot(3.0, 0.3), abs=1e-3)
    assert y == pytest.approx(0.0, abs=1e-9)
    x, y = ph.value_at(end, (2.0 - 1.0, 1.8), step=True)  # (2, 1.8): about 42 degrees
    assert x == pytest.approx(y)


def test_an_arrow_origin_accounts_for_its_gap() -> None:
    spec = Spec(type="Arrow", params={"start": [-2.0, 1.0], "end": [2.0, 1.0], "buff": 0.5})
    points = adapter.build_mobject(spec).family_members_with_points()[0].points[:, :2]
    origin = ph.line_origin(spec, points)
    assert points[0] == pytest.approx(np.array([-1.5, 1.0]) - origin, abs=1e-6)  # pulled in by the gap
    found = handles(spec)
    assert found["start"].local == pytest.approx(np.array([-2.0, 1.0]) - origin, abs=1e-6)


def test_objects_without_sizes_have_no_handles() -> None:
    assert handles(Spec(type="Triangle")) == {}
    assert ph.object_handles(Spec(type="Circle"), np.zeros((0, 2)), EYE, ZERO) == []


def test_a_connector_has_a_handle_per_drawn_end_at_its_offset() -> None:
    spec = Spec(type="Connector", params={"source": "a", "target": "b", "target_offset": [0.5, 0.0]})
    frames = [None, (turned(0, 2.0), np.array([3.0, 0.0]))]
    (only,) = ph.connector_handles(spec, frames)
    assert only.param == "target_offset"
    assert only.world == pytest.approx((4.0, 0.0))  # the target's centre + its scale x offset
    assert ph.value_at(only, only.to_local((5.0, 1.0))) == pytest.approx((1.0, 0.5))
    assert ph.value_at(only, (0.61, 0.13), step=True) == pytest.approx((0.5, 0.25))  # Shift: a grid


def test_handle_under_picks_the_nearest_within_reach() -> None:
    found = handles(Spec(type="Rectangle", params={"width": 2.0, "height": 2.0}))
    both = [found["width"], found["height"]]
    assert ph.handle_under(both, (1.05, 0.0), 0.1).param == "width"
    assert ph.handle_under(both, (0.0, 0.95), 0.1).param == "height"
    assert ph.handle_under(both, (0.5, 0.5), 0.1) is None


def test_titles_are_short_words() -> None:
    found = handles(Spec(type="Text", params={"text": "x"}))
    assert found["font_size"].title == "size"
    assert handles(Spec(type="Square"))["side_length"].title == "side"


def test_handle_under_prefers_the_nearer_of_two_in_reach() -> None:
    found = handles(Spec(type="Rectangle", params={"width": 0.2, "height": 0.2}))
    both = [found["width"], found["height"]]  # (0.1, 0) and (0, 0.1)
    assert ph.handle_under(both, (0.09, 0.02), 0.5).param == "width"
    assert ph.handle_under(both, (0.02, 0.09), 0.5).param == "height"
