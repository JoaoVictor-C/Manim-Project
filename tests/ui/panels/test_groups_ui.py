"""Groups in the window (U6, ADR 0050): Edit > Group / Ungroup, the Layers tree, Properties, and
the canvas moving a group as one object."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication

from manim_studio.core.model.schema import Canvas, Layer, PartKey, Project, Spec, Transform2D
from manim_studio.ui.main_window import MainWindow
from manim_studio.ui.panels.layers_panel import ID_ROLE

pytestmark = pytest.mark.ui

FILLED = {"fill": "#3b82f6", "fill_opacity": 0.8}
NONE = Qt.KeyboardModifier.NoModifier


def square(layer_id: str, x: float, y: float) -> Layer:
    return Layer(
        id=layer_id,
        spec=Spec(type="Square", params={"side_length": 1.0}, style=FILLED),
        base=Transform2D(position=(x, y)),
    )


def scene() -> Project:
    return Project(
        canvas=Canvas(width_px=640, height_px=360, fps=30, duration=4.0),
        layers=[
            square("a", -3.0, 0.0),
            square("b", -1.0, 0.0),
            square("c", 3.0, 0.0),
            Layer(
                id="eq",
                spec=Spec(type="MathTex", params={"text": "a+b"}),
                base=Transform2D(position=(0, 2.5)),
            ),
            Layer(id="p", parent_id="eq", part=PartKey(tex="a")),
        ],
    )


@pytest.fixture
def window(qt_app, tmp_path):
    path = tmp_path / "scene.json"
    path.write_text(scene().model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.resize(1100, 800)
    win.show()
    win.load(path)
    qt_app.processEvents()
    win.move_tool.snapping = False
    yield win
    win.close()


def px(window, x: float, y: float) -> QPointF:
    return window.canvas.units_transform().map(QPointF(float(x), float(y)))


def mouse(window, kind, pos: QPointF) -> None:
    canvas = window.canvas
    button = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseMove else Qt.MouseButton.LeftButton
    buttons = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease else Qt.MouseButton.LeftButton
    QApplication.sendEvent(
        canvas, QMouseEvent(kind, pos, QPointF(canvas.mapToGlobal(pos.toPoint())), button, buttons, NONE)
    )


def click(window, x, y, qt_app) -> None:
    mouse(window, QEvent.Type.MouseButtonPress, px(window, x, y))
    mouse(window, QEvent.Type.MouseButtonRelease, px(window, x, y))
    qt_app.processEvents()


def double_click(window, x, y, qt_app) -> None:
    pos = px(window, x, y)
    for kind in (
        QEvent.Type.MouseButtonPress,
        QEvent.Type.MouseButtonRelease,
        QEvent.Type.MouseButtonDblClick,
        QEvent.Type.MouseButtonRelease,
    ):
        mouse(window, kind, pos)
    qt_app.processEvents()


def drag(window, start, end, qt_app) -> None:
    a, b = px(window, *start), px(window, *end)
    mouse(window, QEvent.Type.MouseButtonPress, a)
    for f in (0.3, 0.7, 1.0):
        mouse(window, QEvent.Type.MouseMove, a + (b - a) * f)
        qt_app.processEvents()
    mouse(window, QEvent.Type.MouseButtonRelease, b)
    qt_app.processEvents()


def grouped(window, qt_app) -> str:
    window.selection.set_layers(["a", "b"])
    window.group_action.trigger()
    qt_app.processEvents()
    return window.selection.layer_id


def test_ctrl_g_groups_the_selection_and_selects_the_group(window, qt_app) -> None:
    assert window.group_action.shortcut().toString() == "Ctrl+G"
    assert window.ungroup_action.shortcut().toString() == "Ctrl+Shift+G"
    group_id = grouped(window, qt_app)
    group = window.project.layer(group_id)
    assert group.is_group and [x.id for x in window.project.children(group_id)] == ["a", "b"]
    assert window.document.undo_stack.count() == 1
    items = {item.data(0, ID_ROLE): item for item in window.layers.items()}
    assert [items[group_id].child(i).data(0, ID_ROLE) for i in range(items[group_id].childCount())] == [
        "a",
        "b",
    ]
    assert "group of 2 objects" in items[group_id].toolTip(0)
    fields = set(window.properties.fields)
    assert {"name", "base.position", "base.scale", "base.rotation", "base.opacity", "lifetime.in"} <= fields
    assert not any(f.startswith(("style.", "params.")) for f in fields)  # no object or style sections
    assert "Group" in window.properties.title.text()


def test_grouping_what_v1_refuses_says_why(window, qt_app) -> None:
    window.selection.set_layers(["a", "eq"])
    window.group_action.trigger()
    assert "has parts or objects on axes" in window.statusBar().currentMessage()
    assert not any(x.is_group for x in window.project.layers)


def test_the_canvas_moves_a_group_as_one_object(window, qt_app) -> None:
    group_id = grouped(window, qt_app)
    window.selection.clear()
    click(window, -3.0, 0.0, qt_app)  # a click on one of its objects picks the whole group
    assert window.selection.layer_id == group_id
    box = window.canvas.outline.box
    assert box.centre[0] == pytest.approx(-2.0, abs=0.05)  # the union of both squares
    drag(window, (-3.0, 0.0), (-2.0, 1.0), qt_app)
    assert window.project.layer(group_id).base.position == pytest.approx((1.0, 1.0), abs=0.02)
    assert window.project.layer("a").base.position == (-3.0, 0.0)  # carried, not moved itself
    drawn = dict(window.evaluator.frame_layers(window.t))
    assert drawn["b"].get_center()[:2] == pytest.approx((0.0, 1.0), abs=0.02)


def test_double_click_enters_the_group_and_escape_deselects(window, qt_app) -> None:
    group_id = grouped(window, qt_app)
    double_click(window, -3.0, 0.0, qt_app)
    assert window.selection.layer_id == "a"
    click(window, -1.0, 0.0, qt_app)  # inside the group: its other object
    assert window.selection.layer_id == "b"
    QApplication.sendEvent(window.canvas, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, NONE, ""))
    assert window.selection.layer_id is None  # Esc deselects everything, even inside a group
    assert group_id


def test_ctrl_shift_g_ungroups_keeping_the_look(window, qt_app) -> None:
    group_id = grouped(window, qt_app)
    window.properties.fields["base.position"].commit((1.0, 0.5))
    qt_app.processEvents()
    window.ungroup_action.trigger()
    qt_app.processEvents()
    assert not any(x.is_group for x in window.project.layers)
    assert window.project.layer("a").base.position == pytest.approx((-2.0, 0.5))
    assert set(window.selection.layer_ids) == {"a", "b"}
    assert group_id not in {item.data(0, ID_ROLE) for item in window.layers.items()}
