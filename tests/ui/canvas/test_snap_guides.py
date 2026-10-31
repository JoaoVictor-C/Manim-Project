"""Snapping guides' geometry (P6c.1, ADR 0043). No Qt."""

from __future__ import annotations

import numpy as np
import pytest

from manim_studio.ui.canvas import snap_guides as sg

OTHER = (np.array([2.0, -1.0]), np.array([4.0, 1.0]))  # a box: x 2..4 (centre 3), y -1..1
FRAME = (np.array([-7.0, -4.0]), np.array([7.0, 4.0]))


def test_targets_are_every_box_edge_and_centre_and_the_frame() -> None:
    found = sg.targets([OTHER], FRAME)
    assert sorted(t.value for t in found.xs) == [-7.0, 0.0, 2.0, 3.0, 4.0, 7.0]
    assert sorted(t.value for t in found.ys) == [-4.0, -1.0, 0.0, 0.0, 1.0, 4.0]
    assert sg.targets([]).xs == ()


def test_an_edge_within_reach_snaps_onto_the_nearest_line() -> None:
    found = sg.targets([OTHER])
    # a box x 0..1.95: its right edge is 0.05 from the other's left edge (2.0)
    result = sg.snap((0.0, 5.0), (1.95, 6.0), found, radius=0.1)
    assert result.offset == pytest.approx((0.05, 0.0))
    assert result.guides == [((2.0, -1.0), (2.0, 6.0))]  # drawn across both boxes


def test_the_closest_of_several_lines_wins() -> None:
    found = sg.targets([OTHER])
    result = sg.snap((2.96, 5.0), (3.5, 6.0), found, radius=0.1)  # left 0.04 from centre 3
    assert result.offset[0] == pytest.approx(0.04)
    result = sg.snap((1.93, 5.0), (2.97, 6.0), found, radius=0.1)  # left 0.07 from 2, right 0.03 from 3
    assert result.offset[0] == pytest.approx(0.03)


def test_centres_snap_too_on_both_axes() -> None:
    found = sg.targets([], FRAME)
    result = sg.snap((-1.03, -0.48), (0.97, 0.56), found, radius=0.1)  # centre (-0.03, 0.04)
    assert result.offset == pytest.approx((0.03, -0.04))
    assert len(result.guides) == 2


def test_nothing_within_reach_does_not_move() -> None:
    result = sg.snap((0.0, 5.0), (1.5, 6.0), sg.targets([OTHER]), radius=0.1)
    assert result.offset == pytest.approx((0.0, 0.0))
    assert result.guides == []


def test_an_axis_can_be_left_free() -> None:
    found = sg.targets([OTHER])
    result = sg.snap((0.0, 0.97), (1.95, 2.0), found, radius=0.1, axes=(False, True))
    assert result.offset == pytest.approx((0.0, 0.03))
    assert [g[0][1] == g[1][1] for g in result.guides] == [True]  # only the horizontal guide


def test_a_point_snaps_as_a_box_of_no_size() -> None:
    result = sg.snap((3.95, 0.5), (3.95, 0.5), sg.targets([OTHER]), radius=0.1)
    assert result.offset == pytest.approx((0.05, 0.0))


def test_box_of() -> None:
    low, high = sg.box_of(np.array([[1.0, 2.0, 0.0], [-1.0, 5.0, 0.0]]))
    assert low == pytest.approx((-1.0, 2.0)) and high == pytest.approx((1.0, 5.0))
    assert sg.box_of(np.zeros((0, 3))) is None


def test_guides_span_the_snapped_box() -> None:
    # right edge 0.05 short of x = 2, bottom 0.03 above y = 1: both snap
    result = sg.snap((0.0, 1.03), (1.95, 3.0), sg.targets([OTHER]), radius=0.1)
    assert result.offset == pytest.approx((0.05, -0.03))
    vertical = next(g for g in result.guides if g[0][0] == g[1][0])
    assert np.ravel(vertical) == pytest.approx((2.0, -1.0, 2.0, 2.97))


def test_layout_guides_are_targets_across_the_frame() -> None:
    found = sg.targets([], FRAME, [("x", 1.5), ("y", -2.0)])
    assert sg.Target(1.5, (-4.0, 4.0)) in found.xs
    assert sg.Target(-2.0, (-7.0, 7.0)) in found.ys
    result = sg.snap((0.45, 0.5), (1.45, 1.5), found, radius=0.1)  # the right edge, 0.05 short
    assert result.offset == pytest.approx((0.05, 0.0))
