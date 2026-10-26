"""Readouts and connectors in the editor (P5b.2, ADR 0036): a connector from the library joins
the object before the selected one to it, its ends are chosen in Properties, it has no clips and
goes with either object; a Number from the library counts with a clip set in Properties."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import manim as m
import pytest

pytest.importorskip("PySide6")

from acceptance.test_acceptance_v1 import menu_action, timeline_menu
from manim_studio.core.model.schema import Canvas, Layer, Project, Spec, Transform2D
from manim_studio.ui.main_window import MainWindow

pytestmark = pytest.mark.ui


@pytest.fixture
def window(qt_app, tmp_path):
    project = Project(
        canvas=Canvas(width_px=320, height_px=180, fps=10, duration=3.0),
        layers=[
            Layer(id="dot", name="Dot", spec=Spec(type="Dot"), base=Transform2D(position=(-3.0, 0.0))),
            Layer(id="sq", name="Square", spec=Spec(type="Square"), base=Transform2D(position=(3.0, 0.0))),
        ],
    )
    path = tmp_path / "scene.json"
    path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.show()
    win.load(path)
    yield win
    win.close()


def test_a_connector_joins_the_object_before_the_selected_one(window) -> None:
    window.selection.clear()
    menu_action(window.layers.library_menu, "Connector").trigger()
    assert len(window.project.layers) == 2
    assert window.statusBar().currentMessage().startswith("Select the object to connect to first")

    window.selection.set("sq")
    menu_action(window.layers.library_menu, "Connector").trigger()
    link = window.project.layers[-1]
    assert link.spec.type == "Connector" and link.spec.params == {"source": "dot", "target": "sq"}
    assert window.selection.layer_id == link.id
    drawn = dict(window.evaluator.frame_layers(0.0))[link.id]
    assert type(drawn) is m.Line and drawn.get_end()[0] == pytest.approx(1.9)  # the square's edge

    fields = window.properties.fields
    box = fields["params.source"].widget
    assert [box.itemText(i) for i in range(box.count())] == ["Dot", "Square"]  # not itself
    fields["params.tips"].commit("end")
    fields["params.ends"].commit("centres")
    params = window.project.layer(link.id).spec.params
    assert params["tips"] == "end" and params["ends"] == "centres"
    assert isinstance(dict(window.evaluator.frame_layers(0.0))[link.id], m.Arrow)

    add = menu_action(timeline_menu(window, link.id, 1.0), "Add clip (none: it is drawn between its layers)")
    assert not add.isEnabled()

    window.selection.set("dot")
    window.layers.delete_selected()
    assert [x.id for x in window.project.layers] == ["sq"]  # the connector went with its object


def test_the_first_object_connects_to_the_next_one(window) -> None:
    window.selection.set("dot")
    menu_action(window.layers.library_menu, "Connector").trigger()
    assert window.project.layers[-1].spec.params == {"source": "sq", "target": "dot"}


@pytest.mark.latex
def test_a_number_counts_with_a_clip(window) -> None:
    menu_action(window.layers.library_menu, "Number").trigger()
    number = window.project.layers[-1]
    assert number.spec.type == "DecimalNumber"
    fields = window.properties.fields
    fields["params.number"].commit(5.0)
    fields["params.unit"].commit(r"\,\text{m}")
    assert window.project.layer(number.id).spec.params == {"number": 5.0, "unit": r"\,\text{m}"}

    menu = timeline_menu(window, number.id, 0.5)
    menu_action(menu, "Add clip", "Emphasis", "ChangeDecimalToValue").trigger()
    clip = window.project.layer(number.id).clips[0]
    window.selection.set(number.id, clip.id)
    window.properties.fields["clip.params.target_number"].commit(42.5)
    clip = window.project.layer(number.id).clips[0]
    assert clip.params == {"target_number": 42.5}
    after = dict(window.evaluator.frame_layers(clip.end + 0.1))[number.id]
    assert after.number == pytest.approx(42.5) and after.unit == r"\,\text{m}"
