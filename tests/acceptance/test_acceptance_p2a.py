"""P2a acceptance: scale and rotate an object on the canvas, undo, redo; animate a rotation with auto-key.

Through the editor's own widgets and real mouse events (ADR 0016, ADR 0018).
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from manim_studio.core.engine.evaluator import layer_transform
from manim_studio.ui.canvas.gizmo import KNOB_OFFSET_PX
from manim_studio.ui.main_window import MainWindow

pytestmark = [pytest.mark.ui]


def menu_action(menu, *path: str):
    for title in path:
        found = next(a for a in menu.actions() if a.text().replace("&", "") == title)
        menu = found.menu() or found
    return found


def drag(window, qt_app, a: QPointF, b: QPointF) -> None:
    canvas = window.canvas
    for kind, pos in (
        (QEvent.Type.MouseButtonPress, a),
        (QEvent.Type.MouseMove, (a + b) / 2),
        (QEvent.Type.MouseMove, b),
        (QEvent.Type.MouseButtonRelease, b),
    ):
        buttons = (
            Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease else Qt.MouseButton.LeftButton
        )
        button = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseMove else Qt.MouseButton.LeftButton
        global_pos = QPointF(canvas.mapToGlobal(pos.toPoint()))
        QApplication.sendEvent(
            canvas, QMouseEvent(kind, pos, global_pos, button, buttons, Qt.KeyboardModifier.NoModifier)
        )
        qt_app.processEvents()


def handles(window):
    box = window.canvas.outline.box
    to_px = window.canvas.units_transform()
    corners = [to_px.map(QPointF(*c)) for c in box.corners]
    knob = to_px.map(QPointF(*box.knob(KNOB_OFFSET_PX / window.canvas.px_per_unit())))
    return corners, knob, to_px.map(QPointF(*box.pivot))


@pytest.fixture
def window(qt_app):
    win = MainWindow()
    win.resize(1280, 820)
    win.show()
    menu_action(win.menuBar(), "File", "New").trigger()
    menu_action(win.layers.library_menu, "Square").trigger()
    win.properties.fields["style.fill_opacity"].commit(0.8)
    qt_app.processEvents()
    yield win
    win.close()


def test_scale_and_rotate_on_the_canvas_undo_redo(window, qt_app) -> None:
    layer_id = window.project.layers[0].id
    corners, knob, pivot = handles(window)
    drag(window, qt_app, corners[2], pivot + (corners[2] - pivot) * 1.5)
    corners, knob, pivot = handles(window)
    radius = (knob - pivot).manhattanLength()
    drag(window, qt_app, knob, QPointF(pivot.x() + radius, pivot.y()))  # a quarter turn clockwise
    base = window.project.layer(layer_id).base
    assert (base.scale, base.rotation) == (pytest.approx(1.5, abs=0.02), pytest.approx(-90, abs=1))
    stack = window.document.undo_stack
    assert [stack.text(i) for i in range(stack.count())][-2:] == ["Scale layer", "Rotate layer"]
    stack.undo()
    stack.undo()
    assert (window.project.layer(layer_id).base.scale, window.project.layer(layer_id).base.rotation) == (
        1.0,
        0.0,
    )
    stack.redo()
    stack.redo()
    assert window.project.layer(layer_id).base.rotation == pytest.approx(-90, abs=1)


def test_animate_a_rotation_with_auto_key(window, qt_app) -> None:
    layer_id = window.project.layers[0].id
    window.auto_key_action.setChecked(True)
    window.properties.fields["lifetime.in"].commit(0.0)  # it has an entrance: auto-key animates
    window.seek(2.0)
    _, knob, pivot = handles(window)
    radius = (knob - pivot).manhattanLength()
    drag(window, qt_app, knob, QPointF(pivot.x() - radius, pivot.y()))  # a quarter turn counter-clockwise
    layer = window.project.layer(layer_id)
    assert [k.t for k in layer.tracks["rotation"]] == [0.0, 2.0]
    assert layer_transform(layer, 0.0).rotation == 0.0
    assert layer_transform(layer, 2.0).rotation == pytest.approx(90, abs=1)
    assert 0 < layer_transform(layer, 1.0).rotation < 90  # it turns over time
