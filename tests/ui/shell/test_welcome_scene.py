"""The picture on the welcome page: circles drawing curves over a flow of particles."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import math

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QImage, QPainter

from manim_studio.ui.shell import welcome_scene as scene
from manim_studio.ui.style import theme

pytestmark = pytest.mark.ui


@pytest.fixture(autouse=True)
def back_to_ink(qt_app):
    theme.set_theme(qt_app, "ink")
    yield
    theme.set_theme(qt_app, "ink")


def frame(machine: scene.MathScene, progress: float = 1.0, cursor: QPointF | None = None) -> QImage:
    image = QImage(640, 520, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = QPainter(image)
    machine.paint(painter, QRectF(0, 0, 640, 520), progress, cursor)
    painter.end()
    return image


def painted(image: QImage) -> int:
    return sum(1 for x in range(0, 640, 6) for y in range(0, 520, 6) if image.pixelColor(x, y).alpha() > 8)


def test_the_circles_hold_a_figure_then_blend_into_the_next_one() -> None:
    cycle = scene.HOLD + scene.BLEND
    assert np.allclose(scene.figure_radii(1.0), scene.FIGURES[0])  # held
    assert np.allclose(scene.figure_radii(scene.HOLD - 0.01), scene.FIGURES[0], atol=1e-6)
    halfway = scene.figure_radii(scene.HOLD + scene.BLEND / 2)
    assert np.allclose(halfway, (np.array(scene.FIGURES[0]) + np.array(scene.FIGURES[1])) / 2)
    assert np.allclose(scene.figure_radii(cycle + 1.0), scene.FIGURES[1])
    assert np.allclose(
        scene.figure_radii(cycle * len(scene.FIGURES) + 1.0), scene.FIGURES[0]
    )  # and round again


def test_the_machine_adds_one_circle_to_the_last_and_the_pen_is_the_sum() -> None:
    radii = np.array(scene.FIGURES[3])
    joints = scene.machine(radii, 0.7, 0.0)
    assert len(joints) == len(scene.FREQS) + 1 and joints[0] == 0j
    assert abs(joints[1] - radii[0] * complex(math.cos(0.7), math.sin(0.7))) < 1e-12
    end = scene.trail(radii, 0.7, 0.0, 0.5, 5)[-1]
    assert abs(end - joints[-1]) < 1e-9  # the trail ends where the pen is
    turned = scene.machine(radii, 0.7, 0.5)
    assert abs(turned[-1] - joints[-1] * complex(math.cos(0.5), math.sin(0.5))) < 1e-12


def test_a_closed_figure_comes_back_to_where_it_began() -> None:
    radii = np.array(scene.FIGURES[1])
    whole = scene.trail(radii, 2.0, 0.0, 1.0, 50)  # one full turn of the pen
    assert abs(whole[0] - whole[-1]) < 1e-9


@pytest.mark.parametrize("name", ["ink", "paper"])
@pytest.mark.parametrize("progress", [0.0, 0.3, 0.6, 1.0])
def test_every_step_of_the_entrance_paints_in_both_themes(qt_app, name, progress) -> None:
    theme.set_theme(qt_app, name)
    machine = scene.MathScene()
    image = frame(machine, progress)
    assert painted(image) > 0 or progress == 0.0
    if progress == 1.0:
        assert painted(image) > 400  # the whole picture is there


def test_the_particles_stay_inside_the_picture_and_leave_trails(qt_app) -> None:
    machine = scene.MathScene()
    frame(machine)
    width, height = machine.size
    for _ in range(120):
        machine.step(1 / 30, None)
    inside = ((machine.x - width / 2) / (width / 2)) ** 2 + ((machine.y - height / 2) / (height / 2)) ** 2
    assert (inside <= 1.0 + 1e-9).all()
    assert machine.buffer is not None and any(
        machine.buffer.pixelColor(x, y).alpha() > 0 for x in range(0, 640, 7) for y in range(0, 520, 7)
    )


def test_the_clock_the_parallax_and_the_cursor_move_with_steps(qt_app) -> None:
    machine = scene.MathScene()
    frame(machine)
    before = machine.t
    machine.step(0.03, QPointF(600, 100))
    assert machine.t == pytest.approx(before + 0.03)
    for _ in range(40):
        machine.step(0.03, QPointF(600, 100))  # the cursor at the top right
    assert machine.parallax[0] > 0.3 and machine.parallax[1] < -0.3
    for _ in range(80):
        machine.step(0.03, None)
    assert abs(machine.parallax).max() < 0.05  # and eases back when it leaves
    resumed = machine.t
    machine.step(5.0, None)  # a stalled timer must not throw the clock forward
    assert machine.t - resumed <= 0.06


def test_a_cursor_stirs_the_particles_near_it(qt_app) -> None:
    quiet, stirred = scene.MathScene(seed=3), scene.MathScene(seed=3)
    frame(quiet)
    frame(stirred)
    np.testing.assert_allclose(quiet.x, stirred.x)
    for _ in range(10):
        quiet.step(1 / 30, None)
        stirred.step(1 / 30, QPointF(320, 260))
    assert not np.allclose(quiet.x, stirred.x)


def test_without_steps_the_picture_is_one_still_finished_frame(qt_app) -> None:
    machine = scene.MathScene()
    first, second = frame(machine), frame(machine)
    assert machine.t == scene.STILL_TIME and first == second
    assert painted(first) > 400
