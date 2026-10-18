"""Python objects in the editor (P10.1, ADR 0051), through the real MainWindow: made on the Code
page from a starter, applied with errors at their line, parameters as Properties fields (one undo
step each), and code from an opened file run only once trusted."""

from __future__ import annotations

import os
import uuid

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import manim as m
import pytest

pytest.importorskip("PySide6")

from manim_studio.core import python_object
from manim_studio.core.schema import Canvas, Layer, Project, Spec
from manim_studio.ui.fields import BoolField, ColorField, FloatField, IntField, TextField
from manim_studio.ui.main_window import MainWindow

pytestmark = pytest.mark.ui

STARTER = python_object.STARTER


def write(tmp_path, layers: list[Layer], name: str = "scene.json"):
    project = Project(canvas=Canvas(width_px=320, height_px=180, fps=10, duration=2.0), layers=layers)
    path = tmp_path / name
    path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
    return path


def open_window(qt_app, path, answer: str = "skip") -> MainWindow:
    win = MainWindow()
    win.ask_trust = lambda names: answer
    win.resize(1500, 850)
    win.show()
    win.load(path)
    qt_app.processEvents()
    return win


@pytest.fixture
def window(qt_app, tmp_path):
    win = open_window(qt_app, write(tmp_path, [Layer(id="dot", spec=Spec(type="Circle"))]))
    yield win
    win.close()


def page(window):
    return window.pages.pages["code"]


def drawn(window, layer_id: str, t: float = 0.5) -> m.Mobject:
    return dict(window.evaluator.frame_layers(t))[layer_id]


def python_layer(window) -> Layer:
    return next(x for x in window.project.layers if x.spec.type == "Python")


def unique(code: str) -> str:
    """Code no test has trusted yet (the trust store is shared by the session)."""
    return f"# {uuid.uuid4().hex}\n{code}"


def test_the_code_page_button_adds_the_starter_selects_it_and_opens_it(window, qt_app) -> None:
    window.show_page("animate")
    page(window).new_python_button.click()
    qt_app.processEvents()
    layer = python_layer(window)
    assert window.page == "code"
    assert window.selection.layer_id == layer.id
    assert page(window).layer_id == layer.id
    assert page(window).editor.text() == STARTER
    assert "Built" in page(window).state_label.text()
    assert layer.id in [page(window).list.item(i).data(256) for i in range(page(window).list.count())]
    assert not isinstance(drawn(window, layer.id), m.DashedVMobject)  # trusted: the editor's own code
    fields = window.properties.fields
    assert isinstance(fields["values.angle"], FloatField) and isinstance(fields["values.side"], FloatField)
    assert fields["values.angle"].widget.minimum() == 5.0 and fields["values.angle"].widget.maximum() == 85.0
    assert {"style.fill", "base.position"} <= set(fields)  # Style and Transform as for any object
    assert window.document.undo_stack.undoText() == "Add Python object"


def test_apply_with_an_error_shows_it_at_its_line(window, qt_app) -> None:
    page(window).new_python_button.click()
    qt_app.processEvents()
    code_page = page(window)
    broken = "PARAMS = {'r': 1.0}\n\n\ndef build(p):\n    return Circle(radius=p['r']) + missing\n"
    code_page.editor.set_text(broken)
    code_page._on_text_changed()
    code_page.run()
    qt_app.processEvents()
    layer = python_layer(window)
    assert layer.spec.params["code"] == broken
    assert code_page.error_label.isVisible() or not code_page.isVisible()
    assert code_page.error_label.line == 5
    assert code_page.editor.error_line == 5
    assert "NameError: name 'missing' is not defined" in code_page.error_label.plain
    assert "(error)" in code_page.list.currentItem().text()
    assert isinstance(drawn(window, layer.id), m.DashedVMobject)
    assert "Error: line 5: NameError" in window.properties.python_label.text()
    fixed = broken.replace(" + missing", "")
    code_page.editor.set_text(fixed)
    code_page.run()
    qt_app.processEvents()
    assert code_page.editor.error_line is None
    assert "Built" in code_page.state_label.text()
    assert list(window.properties.fields).count("values.r") == 1  # the fields follow the new PARAMS
    assert "values.angle" not in window.properties.fields


def test_new_code_keeps_the_values_of_parameters_that_still_exist(window, qt_app) -> None:
    page(window).new_python_button.click()
    qt_app.processEvents()
    layer_id = python_layer(window).id
    window.properties.fields["values.side"].commit(5.0)
    window.properties.fields["values.angle"].commit(40.0)
    new = STARTER.replace('"side": (3.0, 0.5, 8.0)', '"side": (3.0, 0.5, 8.0),\n    "label": "c"').replace(
        '"angle": (30.0, 5.0, 85.0)', '"angle": (30.0, 5.0, 35.0)'
    )
    page(window).editor.set_text(new)
    page(window).run()
    assert window.project.layer(layer_id).spec.params["values"] == {"side": 5.0}  # 40 no longer fits
    assert isinstance(window.properties.fields["values.label"], TextField)


def test_a_properties_change_redraws_and_is_one_undo_step(window, qt_app) -> None:
    page(window).new_python_button.click()
    qt_app.processEvents()
    layer_id = python_layer(window).id
    before = drawn(window, layer_id).width
    stack = window.document.undo_stack
    count = stack.count()
    window.properties.fields["values.side"].commit(6.0)
    qt_app.processEvents()
    assert window.project.layer(layer_id).spec.params["values"] == {"side": 6.0}
    assert drawn(window, layer_id).width == pytest.approx(before * 2)
    assert stack.count() == count + 1 and stack.undoText() == "Change side"
    stack.undo()
    assert "values" not in window.project.layer(layer_id).spec.params
    assert drawn(window, layer_id).width == pytest.approx(before)


def test_every_parameter_type_gets_its_field(qt_app, tmp_path) -> None:
    code = unique(
        'PARAMS = {"r": 1.0, "n": (3, 1, 9), "show": True, "label": "x", "colour": "#ff0000"}\n'
        "def build(p):\n    return Circle(radius=p['r'])\n"
    )
    win = open_window(
        qt_app, write(tmp_path, [Layer(id="obj", spec=Spec(type="Python", params={"code": code}))])
    )
    try:
        win.selection.select_layer("obj")
        qt_app.processEvents()
        fields = win.properties.fields
        assert isinstance(fields["values.r"], FloatField)
        assert isinstance(fields["values.n"], IntField) and fields["values.n"].widget.maximum() == 9
        assert isinstance(fields["values.show"], BoolField)
        assert isinstance(fields["values.label"], TextField)
        assert isinstance(fields["values.colour"], ColorField)
        fields["values.show"].commit(False)
        fields["values.colour"].commit("#00ff00")
        assert win.project.layer("obj").spec.params["values"] == {"show": False, "colour": "#00ff00"}
    finally:
        win.close()


def test_an_untrusted_project_shows_the_placeholder_until_trusted(qt_app, tmp_path) -> None:
    code = unique(STARTER)
    path = write(
        tmp_path, [Layer(id="tri", name="Triangle", spec=Spec(type="Python", params={"code": code}))]
    )
    asked = []
    win = MainWindow()
    win.ask_trust = lambda names: asked.append(names) or "skip"
    win.show()
    win.load(path)
    qt_app.processEvents()
    try:
        assert asked == [["Triangle"]]  # the open prompt names it, as it names code layers
        assert isinstance(drawn(win, "tri"), m.DashedVMobject)
        assert win.evaluator.build_errors() == {"tri": python_object.NOT_TRUSTED}
        win.selection.select_layer("tri")
        qt_app.processEvents()
        assert "not trusted" in win.properties.python_label.text()
        assert "values.angle" in win.properties.fields  # PARAMS are read without running the code
        win.show_page("code")
        assert "not trusted" in page(win).state_label.text()
        page(win).run()  # unchanged text: Run trusts it, and it is built
        qt_app.processEvents()
        assert not isinstance(drawn(win, "tri"), m.DashedVMobject)
        assert win.evaluator.build_errors() == {}
        assert "Built" in page(win).state_label.text()
    finally:
        win.close()


def test_trusting_on_open_builds_it(qt_app, tmp_path) -> None:
    code = unique(STARTER)
    path = write(tmp_path, [Layer(id="tri", spec=Spec(type="Python", params={"code": code}))])
    win = MainWindow()
    win.ask_trust = lambda names: "run"
    win.load(path)  # checked at once: no event (an application activation reloads media too)
    try:
        assert not isinstance(drawn(win, "tri"), m.DashedVMobject)
        assert win.evaluator.build_errors() == {}
    finally:
        win.close()


def test_python_objects_are_renamed_and_deleted_on_the_code_page(window, qt_app) -> None:
    page(window).new_python_button.click()
    qt_app.processEvents()
    code_page = page(window)
    layer_id = python_layer(window).id
    code_page.ask_name = lambda current: "Triangle"
    code_page.rename_layer()
    assert window.project.layer(layer_id).name == "Triangle"
    assert code_page.list.currentItem().text() == "Triangle"
    code_page.delete_layer()
    assert all(x.spec.type != "Python" for x in window.project.layers)
    window.document.undo_stack.undo()
    assert window.project.layer(layer_id).name == "Triangle"
