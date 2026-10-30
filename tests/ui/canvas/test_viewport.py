# ruff: noqa: F811 - "window" is the canvas tests' fixture, imported for these tests
"""The canvas view: zoom and pan (P3a, ADR 0023).

The pure model first (``ui/canvas/viewport.py``), then the canvas with real events.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication

from manim_studio.core.model.schema import Canvas
from manim_studio.ui.canvas import viewport
from manim_studio.ui.canvas.viewport import View
from ui.canvas.test_canvas_tools import drag, mouse, px, window  # noqa: F401 - the window fixture

CANVAS = Canvas()  # 1280x720, frame 14.22 x 8
W, H = 800.0, 600.0


# -- the model -----------------------------------------------------------------------------------


def test_fit_is_the_old_letterbox() -> None:
    geo = viewport.geometry(View(), CANVAS, W, H)
    assert geo.ppu == pytest.approx(min(W / CANVAS.frame_width, H / CANVAS.frame_height))
    assert np.array_equal(geo.centre, [0, 0])
    assert viewport.label(View(), geo) == f"Fit ({geo.scale * 100:.0f} %)"
    wider = viewport.geometry(View(), CANVAS, 2 * W, 2 * H)
    assert wider.ppu == pytest.approx(2 * geo.ppu)  # Fit follows the widget


@pytest.mark.parametrize("factor", [1.2, 3.0, 1 / 1.2, 1e6, 1e-6])  # the last two hit the limits
def test_zoom_keeps_the_point_under_the_cursor(factor: float) -> None:
    start = View(fit=False, scale=0.8, centre=(1.0, -0.5))
    x, y = 610.0, 140.0
    before = viewport.to_world(viewport.geometry(start, CANVAS, W, H), W, H, x, y)
    zoomed = viewport.zoom_about(start, CANVAS, W, H, factor, x, y)
    after = viewport.to_world(viewport.geometry(zoomed, CANVAS, W, H), W, H, x, y)
    assert np.allclose(before, after)
    assert viewport.SCALE_LIMITS[0] <= zoomed.scale <= viewport.SCALE_LIMITS[1]
    assert not zoomed.fit


def test_pan_moves_the_content_with_the_drag() -> None:
    start = View(fit=False, scale=2.0, centre=(0.0, 0.0))
    geo = viewport.geometry(start, CANVAS, W, H)
    point = viewport.to_world(geo, W, H, 300, 300)
    panned = viewport.pan(start, CANVAS, W, H, 40, -20)
    assert np.allclose(viewport.to_world(viewport.geometry(panned, CANVAS, W, H), W, H, 340, 280), point)


def test_actual_size_is_one_export_pixel_per_screen_pixel_and_survives_a_resize() -> None:
    view = viewport.at_scale(View(), CANVAS, W, H, 1.0)
    assert viewport.geometry(view, CANVAS, W, H).ppu == pytest.approx(CANVAS.width_px / CANVAS.frame_width)
    assert viewport.geometry(view, CANVAS, 300, 200).scale == 1.0  # not relative to the widget
    assert viewport.label(view, viewport.geometry(view, CANVAS, W, H)) == "100 %"


# -- the canvas ------------------------------------------------------------------------------------


def wheel(window, pos: QPointF, notches: float, modifiers=Qt.KeyboardModifier.NoModifier) -> None:
    canvas = window.canvas
    event = QWheelEvent(
        pos,
        QPointF(canvas.mapToGlobal(pos.toPoint())),
        QPoint(0, 0),
        QPoint(0, int(120 * notches)),
        Qt.MouseButton.NoButton,
        modifiers,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(canvas, event)


def test_mapping_round_trips_at_any_view(window) -> None:
    canvas = window.canvas
    for view in (View(), View(fit=False, scale=3.0, centre=(2.0, 1.0)), View(fit=False, scale=0.1)):
        canvas.set_view(view)
        for point in ((0.0, 0.0), (1.5, -2.0), (9.0, 6.0)):
            pos = canvas.units_transform().map(QPointF(*point))
            assert canvas.to_units(pos) == pytest.approx(point)


def test_ctrl_wheel_zooms_about_the_cursor_and_shows_the_scale(window, qt_app) -> None:
    canvas = window.canvas
    pos = px(window, 1.0, 0.5)
    wheel(window, pos, 2, Qt.KeyboardModifier.ControlModifier)
    qt_app.processEvents()
    assert not canvas.view.fit
    assert canvas.to_units(pos) == pytest.approx((1.0, 0.5))
    assert canvas.zoom_label().endswith("%") and "Fit" not in canvas.zoom_label()
    assert canvas.zoom_label() in window.time_label.text()


def test_a_drag_when_zoomed_moves_the_object_by_screen_pixels_over_the_scale(window, qt_app) -> None:
    canvas = window.canvas
    canvas.set_view(View(fit=False, scale=2.0, centre=(1.0, 0.0)))
    qt_app.processEvents()
    start = px(window, 1.0, 0.0)  # the dot
    drag(window, start, start + QPointF(100, 0), qt_app)
    ppu = canvas.px_per_unit()
    assert window.project.layer("dot").base.position == pytest.approx((1.0 + 100 / ppu, 0.0), abs=1e-3)


def test_an_object_outside_the_frame_is_drawn_and_can_be_selected(window, qt_app) -> None:
    from manim_studio.core.editing import edits

    window.document.apply(edits.update_layer(window.project, "dot", base={"position": (10.0, 0.0)}), "Move")
    canvas = window.canvas
    canvas.set_view(View(fit=False, scale=0.25))
    qt_app.processEvents()
    pos = px(window, 10.0, 0.0)
    assert not canvas.frame_rect().contains(pos)  # on the pasteboard
    pixel = canvas._image.pixelColor(int(pos.x() * canvas.devicePixelRatioF()), int(pos.y()))
    assert pixel.blue() > 100  # the blue dot, rendered beyond the frame
    mouse(window, QEvent.Type.MouseButtonPress, pos)
    mouse(window, QEvent.Type.MouseButtonRelease, pos)
    assert window.selection.layer_id == "dot"


def test_wheel_and_middle_drag_pan(window, qt_app) -> None:
    canvas = window.canvas
    wheel(window, QPointF(200, 200), -1)  # scroll down: the content moves up
    assert not canvas.view.fit
    before = canvas.to_units(QPointF(300, 300))
    canvas.mousePressEvent(
        _mouse(QEvent.Type.MouseButtonPress, QPointF(300, 300), Qt.MouseButton.MiddleButton)
    )
    canvas.mouseMoveEvent(_mouse(QEvent.Type.MouseMove, QPointF(350, 280), Qt.MouseButton.NoButton))
    canvas.mouseReleaseEvent(
        _mouse(QEvent.Type.MouseButtonRelease, QPointF(350, 280), Qt.MouseButton.MiddleButton)
    )
    assert canvas.to_units(QPointF(350, 280)) == pytest.approx(before)  # the content followed the drag
    assert window.document.undo_stack.count() == 0  # the view is not an edit


def test_hand_tool_pans_with_left_drag_and_respects_the_stage_lock(window, qt_app) -> None:
    canvas = window.canvas
    canvas.set_interaction_mode("hand")
    start, end = QPointF(300, 300), QPointF(350, 280)
    before = canvas.to_units(start)
    drag(window, start, end, qt_app)
    assert canvas.to_units(end) == pytest.approx(before)
    assert window.document.undo_stack.count() == 0

    window._set_stage_view_locked(True)
    before_locked = canvas.view
    drag(window, end, end + QPointF(70, 40), qt_app)
    assert canvas.view == before_locked
    window._set_stage_view_locked(False)  # do not leak a saved editor preference into later UI tests


def test_the_view_waits_while_something_is_dragged(window, qt_app) -> None:
    canvas = window.canvas
    start = px(window, 1.0, 0.0)
    mouse(window, QEvent.Type.MouseButtonPress, start)
    mouse(window, QEvent.Type.MouseMove, start + QPointF(30, 0))
    qt_app.processEvents()
    wheel(window, start, 3, Qt.KeyboardModifier.ControlModifier)
    assert canvas.view.fit  # ignored mid-drag
    mouse(window, QEvent.Type.MouseButtonRelease, start + QPointF(30, 0))


def test_fit_and_actual_size_from_the_view_menu(window, qt_app) -> None:
    from acceptance.test_acceptance_v1 import menu_action

    canvas = window.canvas
    menu_action(window.menuBar(), "View", "Actual Size (100 %)").trigger()
    assert canvas.zoom_label() == "100 %"
    window.resize(900, 700)
    qt_app.processEvents()
    assert canvas.zoom_label() == "100 %"  # survives a resize
    menu_action(window.menuBar(), "View", "Zoom In").trigger()
    assert canvas.zoom_label() == "120 %"
    menu_action(window.menuBar(), "View", "Fit").trigger()
    assert canvas.view.fit and canvas.zoom_label().startswith("Fit")


def test_opening_a_project_returns_to_fit(window, qt_app, tmp_path) -> None:
    window.canvas.set_view(View(fit=False, scale=4.0))
    path = tmp_path / "again.json"
    path.write_text(window.project.model_dump_json(by_alias=True), encoding="utf-8")
    window.load(path)
    assert window.canvas.view.fit


def _mouse(kind, pos: QPointF, button):
    from PySide6.QtGui import QMouseEvent

    buttons = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease else button
    return QMouseEvent(kind, pos, pos, button, buttons, Qt.KeyboardModifier.NoModifier)


@pytest.mark.parametrize("size", [(400, 400), (700, 200)])
def test_the_frame_border_shows_on_every_side_at_fit(window, qt_app, size) -> None:
    """P6d.4: a frame as wide (or tall) as the canvas still shows its border at the edges."""
    from manim_studio.ui.canvas.canvas import FRAME_BORDER

    canvas = window.canvas
    canvas.setFixedSize(*size)
    window.canvas.fit()
    qt_app.processEvents()
    image = canvas.grab().toImage()
    border = FRAME_BORDER.rgb() & 0xFFFFFF
    frame = canvas.frame_rect().toAlignedRect().intersected(canvas.rect())
    middle_x, middle_y = frame.center().x(), frame.center().y()
    edges = {
        "left": (frame.left(), middle_y),
        "right": (frame.right(), middle_y),
        "top": (middle_x, frame.top()),
        "bottom": (middle_x, frame.bottom()),
    }
    for side, (x, y) in edges.items():
        near = [
            image.pixel(x + dx, y + dy) & 0xFFFFFF
            for dx in (-1, 0, 1)
            for dy in (-1, 0, 1)
            if 0 <= x + dx < image.width() and 0 <= y + dy < image.height()
        ]
        assert border in near, side
