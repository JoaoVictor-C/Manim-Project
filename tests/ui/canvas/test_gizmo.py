"""Transform handle geometry (P2a.1) — pure math, no Qt."""

from __future__ import annotations

import itertools
import math

import numpy as np
import pytest

from manim_studio.ui.canvas.gizmo import (
    SCALE_LIMITS,
    angle_delta,
    handle_at,
    nearest,
    oriented_box,
    scale_from,
    snap_angle,
)


def square(side: float, center=(0.0, 0.0), rotation: float = 0.0) -> np.ndarray:
    h = side / 2
    pts = np.array([[-h, -h], [h, -h], [h, h], [-h, h]])
    a = math.radians(rotation)
    r = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
    return pts @ r.T + np.asarray(center)


def test_box_of_an_unrotated_square_is_its_corners() -> None:
    box = oriented_box(square(2, (1, 1)), (1, 1), 0)
    assert box.corners.tolist() == [[0, 0], [2, 0], [2, 2], [0, 2]]


def test_box_follows_the_rotation_instead_of_growing() -> None:
    """The axis-aligned box of a 45-degree square is 41 % wider; the oriented one hugs it."""
    pts = square(2, (0, 0), 45)
    box = oriented_box(pts, (0, 0), 45)
    assert sorted(map(tuple, np.round(box.corners, 6))) == sorted(map(tuple, np.round(pts, 6)))


def test_knob_points_along_the_box_up_direction() -> None:
    box = oriented_box(square(2), (0, 0), 90)  # rotated a quarter turn: 'up' is -x
    assert box.knob(0.5) == pytest.approx((-1.5, 0.0))


def test_flat_shapes_get_a_minimum_thickness() -> None:
    line = np.array([[-2.0, 0.0], [2.0, 0.0]])
    box = oriented_box(line, (0, 0), 0, min_size=0.2)
    assert box.corners[:, 1].min() == pytest.approx(-0.1) and box.corners[:, 1].max() == pytest.approx(0.1)


def test_contains_uses_the_oriented_box() -> None:
    box = oriented_box(square(2, (0, 0), 45), (0, 0), 45)
    assert box.contains((0, 1.3))  # inside the diamond's top
    assert not box.contains((0.95, 0.95))  # inside its axis-aligned box only


def test_handle_at_prefers_the_knob_then_corners() -> None:
    box = oriented_box(square(2), (0, 0), 0)
    assert handle_at(box, (0, 1.5), grab=0.1, knob_offset=0.5) == "rotate"
    assert handle_at(box, (1.05, 1.0), grab=0.1, knob_offset=0.5) == "scale"
    assert handle_at(box, (0, 0), grab=0.1, knob_offset=0.5) is None


def test_scale_is_the_ratio_of_distances_to_the_pivot() -> None:
    assert scale_from((0, 0), (1, 1), (2, 2), 1.5) == pytest.approx(3.0)
    assert scale_from((0, 0), (1, 1), (-2, -2), 1.0) == pytest.approx(2.0)  # any corner
    assert scale_from((0, 0), (1, 0), (1.26, 0), 1.0, snap=True) == pytest.approx(1.3)
    assert scale_from((0, 0), (1, 0), (0, 0), 1.0) == SCALE_LIMITS[0]
    assert scale_from((0, 0), (0, 0), (5, 5), 2.0) == 2.0  # degenerate start


def test_angle_delta_is_signed_and_sums_through_full_turns() -> None:
    assert angle_delta((0, 0), (1, 0), (0, 1)) == pytest.approx(90)
    assert angle_delta((0, 0), (0, 1), (1, 0)) == pytest.approx(-90)
    path = [(math.cos(math.radians(a)), math.sin(math.radians(a))) for a in range(0, 721, 30)]
    total = sum(angle_delta((0, 0), p, q) for p, q in itertools.pairwise(path))
    assert total == pytest.approx(720)


def test_snap_angle() -> None:
    assert snap_angle(22.0, True) == 15 and snap_angle(23.0, True) == 30
    assert snap_angle(23.0, False) == 23


def test_snap_points_are_corners_edge_midpoints_and_centre() -> None:
    box = oriented_box(square(2, (1, 1), 30), (1, 1), 30)
    snaps = box.snap_points()
    assert snaps.shape == (9, 2)
    assert np.allclose(snaps[:4], box.corners)
    assert np.allclose(snaps[4], (box.corners[0] + box.corners[1]) / 2)
    assert np.allclose(snaps[8], (1, 1))
    assert np.allclose(nearest(snaps, box.corners[2] + 0.1), box.corners[2])
