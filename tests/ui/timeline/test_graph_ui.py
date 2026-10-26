"""Graphs in the editor (P3b.3, ADR 0024): add, edit, key, select and drag them."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPointF

from acceptance.test_acceptance_v1 import menu_action, timeline_menu
from manim_studio.core.model.schema import Canvas, Layer, Project, Spec
from manim_studio.ui.main_window import MainWindow
from ui.canvas.test_canvas_tools import drag, mouse, px

pytestmark = pytest.mark.ui


@pytest.fixture
def window(qt_app, tmp_path):
    project = Project(
        canvas=Canvas(width_px=640, height_px=360, fps=30, duration=4.0),
        layers=[
            Layer(id="axes", spec=Spec(type="Axes")),
            Layer(id="sin", parent_id="axes", spec=Spec(type="Graph", params={"expression": "sin(x)"})),
        ],
    )
    path = tmp_path / "chart.json"
    path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.resize(1100, 800)
    win.show()
    win.load(path)
    qt_app.processEvents()
    win.messages = []
    win.layers.message.connect(win.messages.append)
    win.properties.message.connect(win.messages.append)
    yield win
    win.close()


def test_add_graph_on_the_selected_axes(window, qt_app) -> None:
    layers = window.layers
    layers.select("axes")
    assert layers.add_graph_action.isEnabled() and not layers.add_part_action.isEnabled()
    layers.ask_expression = lambda: "x**2/10 - 1"
    layers.add_graph_action.trigger()
    qt_app.processEvents()
    new = [layer for layer in window.project.children("axes") if layer.id != "sin"]
    assert len(new) == 1 and new[0].spec.params == {"expression": "x**2/10 - 1", "x_range": [-5.0, 5.0]}
    assert window.selection.layer_id == new[0].id
    assert window.document.undo_stack.undoText() == "Add graph"
    layers.select("axes")
    layers.ask_expression = lambda: "__import__('os')"
    layers.add_graph_action.trigger()
    assert len(window.project.children("axes")) == 2  # refused
    assert window.messages[-1].startswith("Add graph:")
    layers.select("sin")
    assert layers.add_graph_action.isEnabled()  # on the graph's axes (ADR 0030)


def test_a_graph_shows_its_formula_and_only_its_opacity(window, qt_app) -> None:
    window.selection.select_layer("sin")
    qt_app.processEvents()
    fields = window.properties.fields
    assert {"params.expression", "params.x_range", "base.opacity", "keys.opacity"} <= set(fields)
    assert not {"base.position", "base.scale", "base.rotation", "base.anchor"} & set(fields)
    fields["params.expression"].commit("cos(x)")
    qt_app.processEvents()
    assert window.project.layer("sin").spec.params["expression"] == "cos(x)"
    fields["params.expression"].commit("cos(")
    qt_app.processEvents()
    assert window.project.layer("sin").spec.params["expression"] == "cos(x)"  # refused
    assert "graph expression" in window.messages[-1]


def test_the_key_menu_of_a_graph_offers_opacity_only(window) -> None:
    menu = timeline_menu(window, "sin", 1.0)
    keys = menu_action(menu, "Add key at playhead").menu()
    assert [a.text() for a in keys.actions()] == ["Opacity"]
    assert "Create" in [
        a.text() for a in menu_action(menu, "Add clip", "Appear / disappear").menu().actions()
    ]


def test_dragging_a_graph_moves_its_axes(window, qt_app) -> None:
    start = px(window, 0.0, 0.0)  # sin(0) = 0: on the curve
    mouse(window, QEvent.Type.MouseButtonDblClick, start)
    assert window.selection.layer_id == "sin"  # drilled into the axes
    drag(window, start, start + QPointF(60, 0), qt_app)
    assert window.selection.layer_id == "sin"
    assert window.project.layer("axes").base.position[0] > 0.5
    assert window.project.layer("sin").base.position == (0.0, 0.0)  # locked to its axes
