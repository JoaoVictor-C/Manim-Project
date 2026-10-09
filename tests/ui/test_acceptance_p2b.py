"""P2b acceptance: animate a move, retime its key on the timeline, give it a custom curve.

Through the editor's widgets and real mouse events: auto-key a drag on the
canvas, drag the resulting key diamond on the timeline, select the first key
and pick a custom curve for it; the motion follows the new timing and curve.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from manim_studio.core import adapter
from manim_studio.core.evaluator import layer_transform
from manim_studio.core.schema import Easing
from manim_studio.ui.main_window import MainWindow
from manim_studio.ui.timeline.view import KEY_OFFSET, ROW_HEIGHT, RULER_HEIGHT

pytestmark = pytest.mark.ui


def menu_action(menu, *path: str):
    for title in path:
        found = next(a for a in menu.actions() if a.text().replace("&", "") == title)
        menu = found.menu() or found
    return found


def drag(qt_app, widget, a: QPointF, b: QPointF) -> None:
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
        global_pos = QPointF(widget.mapToGlobal(pos.toPoint()))
        QApplication.sendEvent(
            widget, QMouseEvent(kind, pos, global_pos, button, buttons, Qt.KeyboardModifier.NoModifier)
        )
        qt_app.processEvents()


def diamond(window, layer_id: str, t: float) -> QPointF:
    view = window.timeline
    y = RULER_HEIGHT + view.row_of(layer_id) * ROW_HEIGHT + KEY_OFFSET
    return QPointF(view.mapFromScene(QPointF(view.scale.x(t), y)))


@pytest.fixture
def window(qt_app):
    win = MainWindow()
    win.resize(1280, 820)
    win.show()
    menu_action(win.menuBar(), "File", "New").trigger()
    menu_action(win.layers.library_menu, "Circle").trigger()
    win.properties.fields["style.fill_opacity"].commit(1.0)
    qt_app.processEvents()
    yield win
    win.close()


def test_animate_retime_and_shape_a_move(window, qt_app) -> None:
    layer_id = window.project.layers[0].id
    to_px = window.canvas.units_transform()

    # 1. auto-key a move: at 2 s the circle is dragged from the centre to x = 3
    window.auto_key_action.setChecked(True)
    window.seek(2.0)
    drag(qt_app, window.canvas, to_px.map(QPointF(0, 0)), to_px.map(QPointF(3, 0)))
    keys = window.project.layer(layer_id).tracks["position"]
    assert [k.t for k in keys] == [0.0, 2.0]

    # 2. on the timeline, drag the key at 2 s to 1 s
    start = diamond(window, layer_id, 2.0)
    end = QPointF(start.x() - window.timeline.scale.px_per_second, start.y())
    drag(qt_app, window.timeline.viewport(), start, end)
    keys = window.project.layer(layer_id).tracks["position"]
    assert [k.t for k in keys] == [0.0, pytest.approx(1.0)]
    assert window.selection.key_time == pytest.approx(1.0)

    # 3. select the first key and give its segment a custom curve
    drag(qt_app, window.timeline.viewport(), diamond(window, layer_id, 0.0), diamond(window, layer_id, 0.0))
    assert window.properties.key_time == 0.0
    curve = Easing(name=None, bezier=(0.9, 0.0, 1.0, 0.1))  # holds still, then rushes at the end
    window.properties.curve_dialog = lambda ease: curve
    window.properties.fields["keys.position.ease"].commit("custom-curve")

    layer = window.project.layer(layer_id)
    assert layer.tracks["position"][0].ease == curve
    expected = 3.0 * adapter.rate_func(curve)(0.5)
    assert layer_transform(layer, 0.5).position[0] == pytest.approx(expected, abs=1e-6)
    assert layer_transform(layer, 0.5).position[0] < 0.3  # the curve, not the default smooth (1.5)
    stack = window.document.undo_stack
    assert [stack.text(i) for i in range(stack.count())][-3:] == ["Move layer", "Move keys", "Change easing"]
