"""S3 acceptance: move an object on the canvas, undo, redo — and animate it by moving it.

Through the editor's own widgets and real mouse events: File > New, add a
circle from the library, drag it, undo, redo; then turn its position
keyframes on, move the playhead, drag again, and check that it now moves over
time and renders where it was dropped.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from manim_studio.core.evaluator import layer_transform
from manim_studio.ui.main_window import MainWindow

pytestmark = [pytest.mark.ui]


def menu_action(menu, *path: str):
    for title in path:
        found = next(a for a in menu.actions() if a.text().replace("&", "") == title)
        menu = found.menu() or found
    return found


def drag(window, qt_app, start: tuple[float, float], end: tuple[float, float]) -> None:
    canvas = window.canvas
    to_px = canvas.units_transform()
    a, b = to_px.map(QPointF(*start)), to_px.map(QPointF(*end))
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


@pytest.fixture
def window(qt_app):
    win = MainWindow()
    win.resize(1280, 820)
    win.show()
    yield win
    win.close()


def test_move_an_object_undo_redo(window, qt_app) -> None:
    menu_action(window.menuBar(), "File", "New").trigger()
    menu_action(window.layers.library_menu, "Square").trigger()  # a Manim square: outline only
    layer_id = window.project.layers[0].id
    window.properties.fields["style.fill_opacity"].commit(0.8)  # filled, so its middle is clickable

    drag(window, qt_app, (0.0, 0.0), (2.0, 1.0))
    assert window.project.layer(layer_id).base.position == pytest.approx((2.0, 1.0), abs=0.02)
    stack = window.document.undo_stack
    assert stack.undoText() == "Move layer"

    stack.undo()
    assert window.project.layer(layer_id).base.position == (0.0, 0.0)
    stack.redo()
    assert window.project.layer(layer_id).base.position == pytest.approx((2.0, 1.0), abs=0.02)
    assert window.canvas.outline.bounds.center().x() == pytest.approx(2.0, abs=0.02)  # drawn there


def test_animate_by_moving_with_the_stopwatch(window, qt_app) -> None:
    menu_action(window.menuBar(), "File", "New").trigger()
    menu_action(window.layers.library_menu, "Circle").trigger()
    layer_id = window.project.layers[0].id
    window.properties.fields["style.fill_opacity"].commit(1.0)

    window.seek(0.0)
    window.properties.fields["keys.position"].widget.setChecked(True)  # key at 0 s: (0, 0)
    window.seek(2.0)
    drag(window, qt_app, (0.0, 0.0), (3.0, 0.0))  # key at 2 s: (3, 0)

    layer = window.project.layer(layer_id)
    assert [k.t for k in layer.tracks["position"]] == [0.0, 2.0]
    assert layer.base.position == (0.0, 0.0)
    assert layer_transform(layer, 0.0).position == (0.0, 0.0)
    assert layer_transform(layer, 2.0).position == pytest.approx((3.0, 0.0), abs=0.02)
    assert 0.0 < layer_transform(layer, 1.0).position[0] < 3.0  # it moves in between
    stack = window.document.undo_stack
    assert [stack.text(i) for i in range(stack.count())][-2:] == ["Animate position", "Move layer"]
