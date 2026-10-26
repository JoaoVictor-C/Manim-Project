"""Arrange geometry (P6c.2, ADR 0043): align and distribute. No Qt."""

from __future__ import annotations

import numpy as np
import pytest

from manim_studio.ui.canvas import arrange


def box(x0, y0, x1, y1):
    return np.array([x0, y0], float), np.array([x1, y1], float)


BOXES = {"a": box(0, 0, 1, 1), "b": box(3, 2, 5, 3), "c": box(-2, -1, -1, 4)}
FRAME = box(-7, -4, 7, 4)


@pytest.mark.parametrize(
    ("how", "expected"),
    [
        ("left", {"a": (-2, 0), "b": (-5, 0)}),
        ("right", {"a": (4, 0), "c": (6, 0)}),
        ("centre", {"a": (1, 0), "b": (-2.5, 0), "c": (3, 0)}),  # common box x -2..5: centre 1.5
        ("bottom", {"a": (0, -1), "b": (0, -3)}),
        ("top", {"a": (0, 3), "b": (0, 1)}),
        ("middle", {"a": (0, 1), "b": (0, -1)}),  # common box y -1..4: middle 1.5; c's is 1.5
    ],
)
def test_align_lines_objects_up_on_their_common_box(how, expected) -> None:
    moves = arrange.align(BOXES, how)
    assert set(moves) == set(expected)
    for key, delta in expected.items():
        assert moves[key] == pytest.approx(delta)


def test_one_object_aligns_to_the_frame() -> None:
    assert arrange.align({"a": box(0, 0, 1, 1)}, "right", FRAME)["a"] == pytest.approx((6, 0))
    assert arrange.align({"a": box(0, 0, 1, 1)}, "middle", FRAME)["a"] == pytest.approx((0, -0.5))
    assert arrange.align({"a": box(0, 0, 1, 1)}, "left") == {}  # no frame given
    assert arrange.align({}, "left", FRAME) == {}


def test_distribute_gives_equal_gaps_keeping_the_outermost() -> None:
    boxes = {"a": box(0, 0, 1, 1), "b": box(1.5, 0, 3.5, 1), "c": box(9, 0, 10, 1), "d": box(5, 0, 6, 1)}
    moves = arrange.distribute(boxes, 0)
    # span 0..10, sizes 1+2+1+1 = 5: gaps of 5/3; order a, b, d, c
    assert set(moves) == {"b", "d"}
    assert moves["b"][0] == pytest.approx(1 + 5 / 3 - 1.5)
    assert moves["d"][0] == pytest.approx(1 + 5 / 3 + 2 + 5 / 3 - 5)
    assert moves["b"][1] == 0.0


def test_distribute_vertically_and_needs_three() -> None:
    boxes = {"a": box(0, 0, 1, 1), "b": box(0, 1.2, 1, 2.2), "c": box(0, 6, 1, 7)}
    moves = arrange.distribute(boxes, 1)
    assert set(moves) == {"b"} and moves["b"] == pytest.approx((0, 3 - 1.2))
    assert arrange.distribute({"a": box(0, 0, 1, 1), "b": box(3, 0, 4, 1)}, 0) == {}


def test_common_box() -> None:
    low, high = arrange.common_box(BOXES.values())
    assert low == pytest.approx((-2, -1)) and high == pytest.approx((5, 4))
