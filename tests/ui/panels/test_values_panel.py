"""The Values tab of the Code page (P13.7): parameters of a Python object, a second view of the same state."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from manim_studio.core.model.schema import Canvas, Layer, Project, Spec
from manim_studio.ui.main_window import MainWindow
from manim_studio.ui.panels.values_panel import NO_PARAMS, NOT_PYTHON

pytestmark = pytest.mark.ui

WHEEL = (
    "PARAMS = {'radius': (1.0, 0.5, 3.0), 'sides': (5, 3, 12), 'label': 'a', 'filled': True,"
    " 'colour': '#ff0000'}\n\ndef build(p):\n    return Circle(radius=p['radius'])\n"
)
BARE = "def build(p):\n    return Square()\n"
SCENE = "class Orbit(Scene):\n    def construct(self):\n        self.add(Dot())\n"


@pytest.fixture
def window(qt_app, tmp_path):
    project = Project(
        canvas=Canvas(width_px=320, height_px=180, fps=10, duration=2.0),
        layers=[
            Layer(id="orbit", name="Orbit", spec=Spec(type="Code", params={"code": SCENE})),
            Layer(id="wheel", name="Wheel", spec=Spec(type="Python", params={"code": WHEEL})),
            Layer(id="bare", name="Bare", spec=Spec(type="Python", params={"code": BARE})),
        ],
    )
    path = tmp_path / "scene.json"
    path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.ask_trust = lambda names: "run"
    win.resize(1500, 850)
    win.show()
    win.load(path)
    win.show_page("code")
    qt_app.processEvents()
    yield win
    win.document.undo_stack.setClean()
    win.close()


def page(window):
    return window.pages.pages["code"]


def drain(qt_app) -> None:
    for _ in range(20):
        qt_app.processEvents()


def test_the_tab_has_a_field_per_parameter(window) -> None:
    window.selection.select_layer("wheel")
    values = page(window).values
    assert list(values.fields) == ["radius", "sides", "label", "filled", "colour"]
    assert values.fields["radius"]._shown == pytest.approx(1.0) and values.fields["sides"]._shown == 5


def test_a_scene_and_a_parameterless_object_say_why_there_is_nothing(window) -> None:
    window.selection.select_layer("orbit")
    values = page(window).values
    assert not values.has_params() and values.note.text() == NOT_PYTHON and not values.note.isHidden()
    assert not page(window).output.isTabEnabled(1)
    window.selection.select_layer("bare")
    assert values.note.text() == NO_PARAMS
    window.selection.select_layer("wheel")
    assert values.note.isHidden() and page(window).output.isTabEnabled(1)


def test_changing_a_value_changes_the_document_once_and_properties_follows(window, qt_app) -> None:
    window.selection.select_layer("wheel")
    before = window.document.undo_stack.count()
    page(window).values.fields["radius"].commit(2.0)
    drain(qt_app)
    assert window.project.layer("wheel").spec.params["values"]["radius"] == 2.0
    assert window.document.undo_stack.count() == before + 1
    assert window.properties.fields["values.radius"]._shown == pytest.approx(2.0)


def test_a_change_in_properties_shows_in_the_tab_and_undo_restores_both(window, qt_app) -> None:
    window.selection.select_layer("wheel")
    window.properties.fields["values.sides"].commit(8)
    drain(qt_app)
    assert page(window).values.fields["sides"]._shown == 8
    window.document.undo_stack.undo()
    drain(qt_app)
    assert page(window).values.fields["sides"]._shown == 5


def test_changing_the_code_rebuilds_the_fields(window, qt_app) -> None:
    window.selection.select_layer("wheel")
    code = page(window)
    code.editor.setPlainText(WHEEL.replace("'sides': (5, 3, 12), ", ""))
    code.run()
    drain(qt_app)
    assert list(code.values.fields) == ["radius", "label", "filled", "colour"]


def test_the_values_of_another_layer_are_not_changed_by_a_late_commit(window, qt_app) -> None:
    window.selection.select_layer("wheel")
    late = page(window).values.fields["radius"]
    window.selection.select_layer("bare")
    late.commit(2.5)
    drain(qt_app)
    assert "values" not in window.project.layer("wheel").spec.params
