"""P6b.2 acceptance: shape a move in the Animate page's graph editor.

Through the editor's widgets and real mouse events: auto-key a move on the canvas
(Compose), switch to Animate, drag the x key in the graph to an earlier time and a
smaller value, add a key by double-clicking the curve, give a segment an ease from
its menu; the canvas draws every change at the playhead, and undo puts it all back.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QColor, QMouseEvent
from PySide6.QtWidgets import QApplication

from manim_studio.core.evaluator import layer_transform
from manim_studio.core.schema import Easing
from manim_studio.ui import graph_model
from manim_studio.ui.main_window import MainWindow
from ui.test_acceptance_p2b import drag, menu_action

pytestmark = [pytest.mark.ui, pytest.mark.slow]

X = graph_model.BY_NAME["x"]


@pytest.fixture
def window(qt_app):
    win = MainWindow()
    win.resize(1400, 900)
    win.show()
    menu_action(win.menuBar(), "File", "New").trigger()
    menu_action(win.layers.library_menu, "Circle").trigger()
    win.properties.fields["style.fill_opacity"].commit(1.0)
    qt_app.processEvents()
    yield win
    win.close()


def colour_at(window, x_units: float) -> QColor:
    """The canvas pixel at (x_units + 0.4, -0.4) in scene units: inside the unit circle centred
    at (x_units, 0), off the selected object's anchor cross and handles."""
    image = window.canvas.grab().toImage()
    point = window.canvas.units_transform().map(QPointF(x_units + 0.4, -0.4))
    return image.pixelColor(int(point.x()), int(point.y()))


def test_shape_a_move_in_the_graph_editor(window, qt_app) -> None:
    layer_id = window.project.layers[0].id
    to_px = window.canvas.units_transform()
    background = colour_at(window, 3.0)
    fill = colour_at(window, 0.0)
    assert fill != background

    # 1. Compose: auto-key a move of the circle to x = 3 at 2 s
    window.auto_key_action.setChecked(True)
    window.seek(2.0)
    drag(qt_app, window.canvas, to_px.map(QPointF(0, 0)), to_px.map(QPointF(3, 0)))
    keyed = window.project.layer(layer_id).tracks["position"]
    assert [(k.t, k.value) for k in keyed] == [(0.0, (0.0, 0.0)), (2.0, (3.0, 0.0))]
    undo_floor = window.document.undo_stack.count()

    # 2. Animate (Shift+2): the graph shows the selected circle's x curve with both keys
    menu_action(window.menuBar(), "View", "Pages", "Animate").trigger()
    qt_app.processEvents()
    graph = window.pages.pages["animate"].graph
    assert window.page == "animate" and graph.isVisible()
    assert {(p.curve, p.t) for p in graph.points()} >= {("x", 0.0), ("x", 2.0), ("y", 2.0)}

    # 3. drag the x key at 2 s to 1 s and down to x = 1.5, as one undo step
    start = graph.point_pos("x", 2.0)
    drag(qt_app, graph, start, QPointF(graph.x_of(1.0), graph.y_of(X, 1.5)))
    keyed = window.project.layer(layer_id).tracks["position"]
    assert [k.t for k in keyed] == [0.0, 1.0]
    assert keyed[1].value[0] == pytest.approx(1.5, abs=0.03) and keyed[1].value[1] == 0.0
    assert window.document.undo_stack.count() == undo_floor + 1
    assert window.selection.key_time == 1.0 and window.properties.key_time == 1.0

    # the canvas follows: at 2 s the circle now rests at x = 1.5, no longer at 3
    window.seek(2.0)
    qt_app.processEvents()
    assert colour_at(window, keyed[1].value[0]) == fill and colour_at(window, 3.0) == background

    # 4. double-click the curve at 0.5 s: a key that changes no frame
    window.seek(0.5)
    qt_app.processEvents()
    before = colour_at(window, layer_transform(window.project.layer(layer_id), 0.5).position[0])
    QApplication.sendEvent(
        graph,
        QMouseEvent(
            QEvent.Type.MouseButtonDblClick,
            graph.curve_pos("x", 0.5),
            QPointF(graph.mapToGlobal(graph.curve_pos("x", 0.5).toPoint())),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    assert [k.t for k in window.project.layer(layer_id).tracks["position"]] == [0.0, 0.5, 1.0]
    assert colour_at(window, layer_transform(window.project.layer(layer_id), 0.5).position[0]) == before

    # 5. right-click the segment after 0.5 s and make it linear
    menu_action(graph.context_menu(graph.curve_pos("x", 0.75)), "linear").trigger()
    layer = window.project.layer(layer_id)
    assert layer.tracks["position"][1].ease == Easing(name="linear")
    middle = layer_transform(layer, 0.75).position[0]
    assert middle == pytest.approx((layer.tracks["position"][1].value[0] + 1.5) / 2, abs=0.03)
    window.seek(0.75)
    qt_app.processEvents()
    assert colour_at(window, middle) == fill

    # 6. undo goes back to the auto-keyed move, and the canvas with it
    stack = window.document.undo_stack
    assert [stack.text(i) for i in range(undo_floor, stack.count())] == [
        "Move position x key",
        "Add key",
        "Set ease",
    ]
    while stack.count() > undo_floor and stack.canUndo() and stack.index() > undo_floor:
        stack.undo()
    keyed = window.project.layer(layer_id).tracks["position"]
    assert [(k.t, k.value) for k in keyed] == [(0.0, (0.0, 0.0)), (2.0, (3.0, 0.0))]
    window.seek(2.0)
    qt_app.processEvents()
    assert colour_at(window, 3.0) == fill
