"""Framing (P7.4, from Unity): F frames the selection in the canvas, or the whole frame when
nothing is selected (Shift+F stays Fit Timeline)."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from manim_studio.core.schema import Canvas, Layer, Project, Spec, Transform2D
from manim_studio.ui import viewport
from manim_studio.ui.main_window import MainWindow

pytestmark = pytest.mark.ui

CANVAS = Canvas(width_px=640, height_px=360, fps=10, duration=3.0)


def test_frame_box_centres_the_box_and_fits_it_with_a_margin() -> None:
    view = viewport.frame_box(CANVAS, 800, 450, (1.0, 1.0), (3.0, 2.0))
    assert not view.fit
    assert view.centre == pytest.approx((2.0, 1.5))
    geo = viewport.geometry(view, CANVAS, 800, 450)
    # the 2 x 1 unit box takes most of the width, never more than the widget
    margin = 1 + 2 * viewport.FRAME_MARGIN
    assert 2.0 * geo.ppu * margin == pytest.approx(800)  # the width is the limit, with the margin
    assert 1.0 * geo.ppu * margin < 450


def test_frame_box_of_a_tiny_or_flat_box_is_not_an_extreme_zoom() -> None:
    dot = viewport.frame_box(CANVAS, 800, 450, (0.0, 0.0), (0.0, 0.0))
    flat = viewport.frame_box(CANVAS, 800, 450, (0.0, 0.0), (4.0, 0.0))
    assert viewport.SCALE_LIMITS[0] <= dot.scale <= viewport.SCALE_LIMITS[1]
    assert flat.scale < dot.scale
    ppu = min(800, 450) / (viewport.MIN_FRAMED_UNITS * (1 + 2 * viewport.FRAME_MARGIN))
    assert dot.scale == pytest.approx(ppu / viewport.export_ppu(CANVAS))  # framed as a half-unit box
    assert viewport.MIN_FRAMED_UNITS == 0.5
    assert np.isfinite(flat.scale)


def test_frame_box_stays_within_the_scale_limits() -> None:
    huge = viewport.frame_box(CANVAS, 800, 450, (-1e4, -1e4), (1e4, 1e4))
    assert huge.scale == viewport.SCALE_LIMITS[0]


def a_window(qt_app, tmp_path) -> MainWindow:
    project = Project(
        canvas=CANVAS,
        layers=[
            Layer(id="big", spec=Spec(type="Circle"), base=Transform2D(position=(-4.0, 2.0))),
            Layer(
                id="small",
                spec=Spec(type="Square", params={"side_length": 0.5}),
                base=Transform2D(position=(3.0, -1.0)),
            ),
        ],
    )
    path = Path(tmp_path) / "frame.json"
    path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
    window = MainWindow()
    window.resize(1000, 700)
    window.show()
    window.load(path)
    qt_app.processEvents()
    return window


def test_f_frames_the_selection_and_f_with_nothing_selected_fits(qt_app, tmp_path) -> None:
    window = a_window(qt_app, tmp_path)
    window.selection.set("small")
    qt_app.processEvents()
    window.canvas.setFocus()
    QTest.keyClick(window.canvas, Qt.Key.Key_F)
    view = window.canvas.view
    assert not view.fit
    assert view.centre == pytest.approx((3.0, -1.0), abs=0.05)
    assert (
        view.scale
        > viewport.geometry(viewport.View(), CANVAS, window.canvas.width(), window.canvas.height()).scale
    )
    window.selection.clear()
    qt_app.processEvents()
    QTest.keyClick(window.canvas, Qt.Key.Key_F)
    assert window.canvas.view.fit
    window.close()


def test_f_frames_every_selected_object(qt_app, tmp_path) -> None:
    window = a_window(qt_app, tmp_path)
    window.selection.set_layers(["big", "small"])
    qt_app.processEvents()
    window.canvas.frame_selection()
    centre = np.array(window.canvas.view.centre)
    assert centre == pytest.approx((-0.5, 0.5), abs=0.7)  # between the two, not on either
    geo = viewport.geometry(window.canvas.view, CANVAS, window.canvas.width(), window.canvas.height())
    for x, y in ((-4.0, 2.0), (3.0, -1.0)):  # both centres are inside the widget
        px = (x - geo.centre[0]) * geo.ppu + window.canvas.width() / 2
        py = -(y - geo.centre[1]) * geo.ppu + window.canvas.height() / 2
        assert 0 < px < window.canvas.width() and 0 < py < window.canvas.height()
    window.close()


def test_view_menu_has_frame_selection(qt_app, tmp_path) -> None:
    window = a_window(qt_app, tmp_path)
    view_menu = next(a for a in window.menuBar().actions() if a.text() == "&View").menu()
    action = next(a for a in view_menu.actions() if a.text() == "Frame &Selection")
    window.selection.set("small")
    action.trigger()
    assert not window.canvas.view.fit
    assert action.toolTip()
    window.close()
