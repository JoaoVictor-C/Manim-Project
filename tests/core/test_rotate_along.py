"""MoveAlongPath that turns with the path (P3g.2, ADR 0029).

With ``rotate: along`` the object turns by the path's change of direction since
the clip started: once around a circle is one full turn. Frames depend on alpha
alone, so scrubbing shows what playing shows.
"""

from __future__ import annotations

import math
import random

import manim as m
import numpy as np
import pytest
from tests.support import CANVAS, FRAMES, TOLERANCE, assert_frames_equal, max_diff, render_in_order

from manim_studio.core import adapter
from manim_studio.core.evaluator import Evaluator
from manim_studio.core.schema import Clip, Easing, Layer, Project, Spec, Transform2D
from manim_studio.render.cairo_export import make_camera, render_frame

ARROWHEAD = Spec(type="Triangle", style={"fill": "#f97316", "fill_opacity": 1.0})
RING = Spec(type="Circle", params={"radius": 2.0})


def ride(path: Spec = RING, rotate: str = "along", ease: str = "linear") -> Project:
    run = Clip(
        id="r",
        kind="MoveAlongPath",
        start=0,
        duration=1,
        params={"path": "track", "rotate": rotate},
        ease=Easing(name=ease),
    )
    mover = Layer(id="car", spec=ARROWHEAD, base=Transform2D(scale=0.4), clips=[run])
    return Project(canvas=CANVAS, layers=[Layer(id="track", spec=path), mover])


def by_hand(turn: float, at: np.ndarray) -> m.Mobject:
    car = adapter.build_mobject(ARROWHEAD).scale(0.4, about_point=m.ORIGIN)
    return car.rotate(turn, about_point=car.get_center()).move_to(at)


def car_frame(evaluator: Evaluator, t: float) -> np.ndarray:
    return render_frame(make_camera(CANVAS), [dict(evaluator.frame_layers(t))["car"]])


@pytest.mark.parametrize("alpha", [0.0, 0.25, 0.6])
def test_once_around_a_circle_is_one_turn(alpha: float) -> None:
    evaluator = Evaluator(ride())
    ring = m.Circle(radius=2.0)
    turn = heading(ring, alpha) - heading(ring, 0.0)
    assert turn % (2 * math.pi) == pytest.approx(
        2 * math.pi * alpha, abs=1e-3
    )  # Manim's circle is nearly round
    expected = render_frame(make_camera(CANVAS), [by_hand(turn, ring.point_from_proportion(alpha))])
    assert max_diff(car_frame(evaluator, alpha), expected) <= TOLERANCE


def heading(path: m.VMobject, alpha: float, step: float = 1e-7) -> float:
    """The drawn path's direction at ``alpha`` of its length, measured with Manim's own walk."""
    a, b = path.point_from_proportion(max(alpha - step, 0)), path.point_from_proportion(min(alpha + step, 1))
    return math.atan2(b[1] - a[1], b[0] - a[0])


def test_a_straight_path_does_not_turn() -> None:
    line = Spec(type="Line", params={"start": (-3.0, -1.0), "end": (3.0, 2.0)})
    turning, plain = Evaluator(ride(line)), Evaluator(ride(line, rotate="no"))
    for t in (0.2, 0.7):
        assert max_diff(car_frame(turning, t), car_frame(plain, t)) <= TOLERANCE


def test_an_overshooting_ease_stops_turning_at_the_end() -> None:
    evaluator = Evaluator(ride(ease="ease_out_back"))
    end = car_frame(evaluator, 0.999)
    assert m.rate_functions.ease_out_back(0.8) > 1  # past the end here
    assert max_diff(car_frame(evaluator, 0.8), end) <= TOLERANCE  # clamped: the same pose


def test_turning_rides_scrub_exactly() -> None:
    project = ride(ease="smooth")
    expected = render_in_order(project, list(range(len(FRAMES))))
    order = random.Random(7).sample(range(len(FRAMES)), len(FRAMES))
    reference = [expected[i] for i in range(len(FRAMES))]
    assert_frames_equal(reference, render_in_order(project, order), "scrubbed")
    assert_frames_equal(reference, render_in_order(project, order, fresh_each_frame=True), "fresh")


def test_rotate_takes_no_or_along_only() -> None:
    with pytest.raises(ValueError, match="rotate"):
        ride(rotate="sideways")
