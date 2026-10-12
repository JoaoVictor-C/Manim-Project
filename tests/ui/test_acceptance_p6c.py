"""P6c.1 acceptance (ADR 0043): every parameter handle, dragged on a turned and scaled object,
lands under the cursor and is one undo step; Escape cancels; moves snap with a guide."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import math

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication

from manim_studio.core.schema import Canvas, Layer, Project, Spec, Transform2D
from manim_studio.ui.main_window import MainWindow

pytestmark = pytest.mark.ui

SQUARE_SVG = '<svg xmlns="http://www.w3.org/2000/svg"><rect width="40" height="20" fill="#f97316"/></svg>'
TURN, SCALE, AT = 30.0, 1.5, (0.5, 0.25)

SPECS = {
    "Circle": {"radius": 1.0},
    "Dot": {"radius": 0.4},
    "Square": {"side_length": 2.0},
    "Rectangle": {"width": 3.0, "height": 1.5},
    "Star": {"outer_radius": 1.0},
    "Text": {"text": "Handles", "font_size": 48},
    "MathTex": {"text": r"e^{i\pi}", "font_size": 48},
    "Tex": {"text": r"Hello", "font_size": 48},
    "DecimalNumber": {"number": 3.14, "font_size": 48},
    "Axes": {"x_length": 4.0, "y_length": 2.5},
    "Line": {"start": [-1.0, 0.0], "end": [1.0, 0.5]},
    "Arrow": {"start": [-1.0, 0.0], "end": [1.0, 0.5]},
}
HANDLES = [(kind, None) for kind in SPECS] + [("SVGMobject", None)]


def open_window(qt_app, tmp_path, layers: list[Layer]) -> MainWindow:
    path = tmp_path / "scene.json"
    project = Project(canvas=Canvas(width_px=960, height_px=540, fps=30, duration=4.0), layers=layers)
    path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.resize(1300, 900)
    win.show()
    win.load(path)
    qt_app.processEvents()
    return win


def px(window, point) -> QPointF:
    return window.canvas.units_transform().map(QPointF(float(point[0]), float(point[1])))


def mouse(window, kind, pos: QPointF, modifiers=Qt.KeyboardModifier.NoModifier) -> None:
    canvas = window.canvas
    button = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseMove else Qt.MouseButton.LeftButton
    buttons = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease else Qt.MouseButton.LeftButton
    global_pos = QPointF(canvas.mapToGlobal(pos.toPoint()))
    QApplication.sendEvent(canvas, QMouseEvent(kind, pos, global_pos, button, buttons, modifiers))


def press_and_move(window, start, end, qt_app) -> None:
    mouse(window, QEvent.Type.MouseButtonPress, px(window, start))
    for f in (0.3, 0.7, 1.0):
        mouse(window, QEvent.Type.MouseMove, px(window, np.asarray(start) + (np.asarray(end) - start) * f))
        qt_app.processEvents()


def layer_of(kind: str, tmp_path) -> Layer:
    params = dict(SPECS.get(kind, {}))
    if kind == "SVGMobject":
        drawing = tmp_path / "box.svg"
        drawing.write_text(SQUARE_SVG, encoding="utf-8")
        params = {"path": str(drawing), "height": 1.0}
    return Layer(
        id="it",
        spec=Spec(type=kind, params=params, style={"fill": "#3b82f6", "fill_opacity": 0.6}),
        base=Transform2D(position=AT, rotation=TURN, scale=SCALE),
    )


def outward(handle) -> np.ndarray:
    """A world move of 0.3 away from the centre (sizes), or sideways and up (points)."""
    if handle.mode == "point":
        return np.array([0.3, 0.2])
    direction = handle.a @ handle.axis
    return 0.3 * direction / np.linalg.norm(direction)


@pytest.mark.parametrize(("kind", "_"), HANDLES)
def test_every_handle_lands_under_the_cursor_on_a_turned_scaled_object(kind, _, qt_app, tmp_path) -> None:
    layer = layer_of(kind, tmp_path)
    win = open_window(qt_app, tmp_path, [layer])
    win.move_tool.snapping = False
    try:
        win.selection.set("it")
        qt_app.processEvents()
        found = list(win.canvas.param_handles)
        assert found, f"{kind} shows no handles"
        for handle in found:
            before = win.project
            start = handle.world
            end = start + outward(handle)
            press_and_move(win, start, end, qt_app)
            mouse(win, QEvent.Type.MouseButtonRelease, px(win, end))
            qt_app.processEvents()
            after = win.project.layer("it").spec.params[handle.param]
            assert after != handle.start, (kind, handle.param)
            now = next(h for h in win.canvas.param_handles if h.param == handle.param)
            reach = 0.08 if handle.mode == "ratio" else 0.03  # font sizes round to whole points
            assert now.world == pytest.approx(end, abs=reach), (kind, handle.param)
            if kind not in ("Line", "Arrow"):
                assert win.project.layer("it").base == layer.base  # sizes grow about the centre
            assert win.document.undo_stack.undoText() == f"Change {handle.title}"
            win.document.undo_stack.undo()
            assert win.project == before
    finally:
        win.close()


def test_a_connector_end_handle_moves_its_offset(qt_app, tmp_path) -> None:
    layers = [
        layer_of("Rectangle", tmp_path),
        Layer(id="dot", spec=Spec(type="Dot"), base=Transform2D(position=(-4.0, -2.0))),
        Layer(id="link", spec=Spec(type="Connector", params={"source": "dot", "target": "it"})),
    ]
    win = open_window(qt_app, tmp_path, layers)
    win.move_tool.snapping = False
    try:
        win.selection.set("link")
        qt_app.processEvents()
        target = next(h for h in win.canvas.param_handles if h.param == "target_offset")
        assert target.world == pytest.approx(AT, abs=1e-6)
        press_and_move(win, target.world, target.world + np.array([0.3, 0.3]), qt_app)
        mouse(win, QEvent.Type.MouseButtonRelease, px(win, target.world + np.array([0.3, 0.3])))
        now = next(h for h in win.canvas.param_handles if h.param == "target_offset")
        assert now.world == pytest.approx(target.world + np.array([0.3, 0.3]), abs=0.03)
        offset = np.array(win.project.layer("link").spec.params["target_offset"])
        assert np.linalg.norm(offset) == pytest.approx(math.hypot(0.3, 0.3) / SCALE, abs=0.03)
    finally:
        win.close()


def test_escape_cancels_and_a_move_snaps_with_a_guide(qt_app, tmp_path) -> None:
    layers = [
        layer_of("Rectangle", tmp_path),
        Layer(
            id="box",
            spec=Spec(type="Square", params={"side_length": 1.0}),
            base=Transform2D(position=(-4.0, -2.0)),
        ),
    ]
    win = open_window(qt_app, tmp_path, layers)
    try:
        win.selection.set("it")
        qt_app.processEvents()
        width = next(h for h in win.canvas.param_handles if h.param == "width")
        press_and_move(win, width.world, width.world + np.array([0.5, 0.5]), qt_app)
        QApplication.sendEvent(
            win.canvas, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
        )
        mouse(win, QEvent.Type.MouseButtonRelease, px(win, width.world + np.array([0.5, 0.5])))
        assert win.project.layer("it").spec.params["width"] == 3.0
        assert win.document.undo_stack.count() == 0
        # the box's left edge, 2 px short of the frame centre line, snaps onto it
        win.selection.set("box")
        qt_app.processEvents()
        near = 4.0 + 0.5 - 2.0 / win.canvas.px_per_unit()
        press_and_move(win, (-4.0, -2.0), (-4.0 + near, -2.0), qt_app)
        assert any(g[0][0] == g[1][0] == pytest.approx(0.0) for g in win.canvas.guides)
        mouse(win, QEvent.Type.MouseButtonRelease, px(win, (-4.0 + near, -2.0)))
        assert win.project.layer("box").base.position == pytest.approx((0.5, -2.0), abs=1e-6)
        assert win.canvas.guides == []
    finally:
        win.close()
