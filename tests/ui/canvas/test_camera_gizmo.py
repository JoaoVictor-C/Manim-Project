"""The camera gizmo's geometry (ADR 0083): the rectangle the camera sees, what a press hits, a corner drag."""

from __future__ import annotations

import numpy as np
import pytest

from manim_studio.core.engine.evaluator import camera_size
from manim_studio.core.model.schema import Canvas, Transform2D
from manim_studio.ui.canvas.camera_gizmo import camera_box, icon_point, part_at, size_from

CANVAS = Canvas(width_px=1600, height_px=900)  # 8 units high, 14.22 wide


def test_at_rest_it_is_the_video_frame() -> None:
    box = camera_box(Transform2D(), CANVAS)
    half_w, half_h = CANVAS.frame_width / 2, CANVAS.frame_height / 2
    assert np.allclose(
        box.corners, [[-half_w, -half_h], [half_w, -half_h], [half_w, half_h], [-half_w, half_h]]
    )
    assert np.allclose(box.centre, 0.0)


def test_position_scale_and_rotation_place_it() -> None:
    box = camera_box(Transform2D(position=(2.0, -1.0), scale=2.0, rotation=90.0), CANVAS)
    assert np.allclose(box.centre, (2.0, -1.0))
    height = np.linalg.norm(box.corners[3] - box.corners[0])
    width = np.linalg.norm(box.corners[1] - box.corners[0])
    assert height == pytest.approx(2 * camera_size(2.0, CANVAS.frame_height))  # twice the size
    assert width / height == pytest.approx(16 / 9)  # the canvas's aspect
    assert np.allclose(box.up, (-1.0, 0.0))  # turned a quarter: its top faces left
    assert box.rotation == 90.0


def test_what_a_press_hits() -> None:
    box = camera_box(Transform2D(), CANVAS)
    knob = box.knob(0.5)
    assert part_at(box, knob, 0.1, 0.5, 0.3, selected=True) == "rotate"
    assert part_at(box, box.corners[1], 0.1, 0.5, 0.3, selected=True) == "size"
    assert part_at(box, (1.0, 1.0), 0.1, 0.5, 0.3, selected=True) == "move"
    assert part_at(box, (1.0, 1.0), 0.1, 0.5, 0.3, selected=False) is None  # the scene: objects get clicks
    assert part_at(box, icon_point(box, 0.3), 0.1, 0.5, 0.3, selected=False) == "icon"
    assert part_at(box, (50.0, 50.0), 0.1, 0.5, 0.3, selected=True) is None


def test_a_corner_drag_grows_the_size_with_the_distance_from_the_centre() -> None:
    assert size_from((0, 0), (2, 0), (4, 0), 4.0) == pytest.approx(8.0)
    assert size_from((1, 1), (2, 1), (1.5, 1), 4.0) == pytest.approx(2.0)
    assert size_from((0, 0), (0, 0), (1, 0), 4.0) == 4.0  # no distance at press: unchanged
