"""Objects on axes in the editor (P3h.2, ADR 0030): Parts > Add to axes, the graph choice."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from manim_studio.core.schema import Canvas, Layer, Project, Spec
from manim_studio.ui.main_window import MainWindow
from ui.test_acceptance_v1 import menu_action

pytestmark = pytest.mark.ui


@pytest.fixture
def window(qt_app, tmp_path):
    project = Project(
        canvas=Canvas(width_px=640, height_px=360, fps=30, duration=3.0),
        layers=[
            Layer(id="axes", spec=Spec(type="Axes")),
            Layer(id="sin", parent_id="axes", spec=Spec(type="Graph", params={"expression": "sin(x)"})),
            Layer(id="par", parent_id="axes", spec=Spec(type="Graph", params={"expression": "x**2/10 - 1"})),
            Layer(id="ring", spec=Spec(type="Circle")),
        ],
    )
    path = tmp_path / "axes.json"
    path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.resize(1100, 800)
    win.show()
    win.load(path)
    qt_app.processEvents()
    yield win
    win.close()


def added(window, type_name: str) -> Layer:
    return next(x for x in window.project.children("axes") if x.spec.type == type_name)


@pytest.mark.parametrize(
    ("label", "type_name", "params"),
    [
        ("Point", "Point", {}),
        ("Area", "Area", {"graph": "sin"}),
        ("Riemann rectangles", "RiemannRectangles", {"graph": "sin"}),
    ],
)
def test_parts_add_to_axes(window, qt_app, label, type_name, params) -> None:
    window.layers.select("par")  # a graph selected: its axes get the object
    window.layers.update_buttons()
    menu_action(window.layers.part_button.menu(), "Add to axes", label).trigger()
    qt_app.processEvents()
    layer = added(window, type_name)
    assert layer.spec.params == params and window.selection.layer_id == layer.id
    assert window.document.undo_stack.undoText() == f"Add {label.lower()}"


def test_add_to_axes_needs_axes_and_a_graph(window, qt_app) -> None:
    window.layers.select("ring")
    window.layers.update_buttons()
    assert not window.layers.axes_menu.isEnabled()
    bare = window.project.model_copy(
        update={"layers": [x for x in window.project.layers if x.spec is None or x.spec.type != "Graph"]}
    )
    window.document.replace(bare)
    window.layers.select("axes")
    window.layers.update_buttons()
    assert window.layers.axes_actions["Point"].isEnabled()
    assert not window.layers.axes_actions["Area"].isEnabled()  # built from a graph: none yet


def test_an_areas_graph_is_chosen_in_properties(window, qt_app) -> None:
    window.layers.select("axes")
    window.layers.update_buttons()
    window.layers.axes_actions["Area"].trigger()
    qt_app.processEvents()
    area = added(window, "Area")
    window.selection.set(area.id)
    qt_app.processEvents()
    graph_field = window.properties.fields["params.graph"]
    assert [graph_field.widget.itemText(i) for i in range(graph_field.widget.count())] == ["sin", "par"]
    bounded = window.properties.fields["params.bounded_graph"]
    assert bounded.widget.itemText(0) == "(the x axis)"
    graph_field.commit("par")
    bounded.commit("sin")
    assert window.project.layer(area.id).spec.params["graph"] == "par"
    assert window.project.layer(area.id).spec.params["bounded_graph"] == "sin"


def test_deleting_the_graph_takes_its_area_in_one_undo_step(window, qt_app) -> None:
    window.layers.select("axes")
    window.layers.update_buttons()
    window.layers.axes_actions["Area"].trigger()
    qt_app.processEvents()
    area = added(window, "Area").id
    window.layers.select("sin")
    window.layers.delete_selected()
    ids = [x.id for x in window.project.layers]
    assert "sin" not in ids and area not in ids
    window.document.undo_stack.undo()
    ids = [x.id for x in window.project.layers]
    assert "sin" in ids and area in ids
