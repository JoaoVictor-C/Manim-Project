"""The Parameters tab of the Code page (P13.4): define PARAMS with a form; edits go to the editor only."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from manim_studio.core.model.schema import Canvas, Layer, Project, Spec
from manim_studio.ui.code.params_definition import (
    DEFAULT,
    MAXIMUM,
    MINIMUM,
    NAME,
    NO_PARAMS,
    NOT_PYTHON,
    ParamsEditError,
    parse_default,
    parse_limit,
)
from manim_studio.ui.main_window import MainWindow

pytestmark = pytest.mark.ui

BASE = (
    "PARAMS = {\n"
    "    'r': (1.0, 0.5, 3.0),  # the radius\n"
    "    'label': 'a',\n"
    "    'filled': True,\n"
    "}\n\n"
    "def build(p):\n"
    "    return Circle(radius=p['r'])\n"
)
SCENE = "class Orbit(Scene):\n    def construct(self):\n        self.add(Dot())\n"


@pytest.fixture
def code_text(tmp_path) -> str:
    return BASE + f"# {tmp_path.name}\n"  # unique: trust is by exact text and outlives a test


@pytest.fixture
def window(qt_app, tmp_path, code_text):
    project = Project(
        canvas=Canvas(width_px=320, height_px=180, fps=10, duration=2.0),
        layers=[
            Layer(id="wheel", name="Wheel", spec=Spec(type="Python", params={"code": code_text})),
            Layer(id="orbit", name="Orbit", spec=Spec(type="Code", params={"code": SCENE})),
        ],
    )
    path = tmp_path / "scene.json"
    path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.ask_trust = lambda names: "skip"
    win.resize(1500, 850)
    win.show()
    win.load(path)
    win.show_page("code")
    win.selection.select_layer("wheel")
    qt_app.processEvents()
    yield win
    win.document.undo_stack.setClean()
    win.close()


def page(window):
    return window.pages.pages["code"]


def panel(window):
    return page(window).params_panel


def code_of(window) -> str:
    return window.project.layer("wheel").spec.params["code"]


def cells(window) -> list[list[str]]:
    table = panel(window).table
    return [[table.item(r, c).text() for c in range(4)] for r in range(table.rowCount())]


def test_the_tab_lists_each_parameter_and_follows_the_layer_kind(window) -> None:
    code = page(window)
    assert code.output.tabText(2) == "Parameters" and code.output.isTabEnabled(2)
    assert cells(window) == [
        ["r", "1.0", "0.5", "3.0"],
        ["label", '"a"', "", ""],
        ["filled", "True", "", ""],
    ]
    assert panel(window).table.item(0, NAME).toolTip() == "the radius"
    code.output.setCurrentIndex(2)
    window.selection.select_layer("orbit")
    assert not code.output.isTabEnabled(2) and code.output.currentIndex() == 0
    assert panel(window).note.text() == NOT_PYTHON and not panel(window).editable()


def test_add_changes_the_editor_text_only_as_one_undo_step(window, code_text) -> None:
    code, params = page(window), panel(window)
    assert params.add_param()
    assert "'new_param': 1.0" in code.editor.text() or '"new_param": 1.0' in code.editor.text()
    assert code_of(window) == code_text  # never applied
    assert [row.name for row in params.rows][-1] == "new_param" and params.chosen() == "new_param"
    assert code.is_dirty()
    code.editor.undo()
    assert code.editor.text() == code_text
    params.refresh()
    assert [row.name for row in params.rows] == ["r", "label", "filled"]


def test_inline_editing_renames_changes_and_sets_limits(window, code_text) -> None:
    code, params = page(window), panel(window)
    assert params.set_cell(0, NAME, "radius")
    assert "'radius': (1.0, 0.5, 3.0),  # the radius" in code.editor.text()
    assert 'still reads p["r"]' in params.status.text()
    assert params.set_cell(0, DEFAULT, "2")  # a whole number for a decimal parameter stays decimal
    assert "'radius': (2.0, 0.5, 3.0)" in code.editor.text()
    assert params.set_cell(0, MAXIMUM, "5")
    assert "'radius': (2.0, 0.5, 5.0)" in code.editor.text()
    assert params.set_cell(0, MINIMUM, "")  # an empty limit drops both
    assert "'radius': 2.0," in code.editor.text()
    assert params.set_cell(1, DEFAULT, "blue")  # a bare word is text
    assert "'label': \"blue\"" in code.editor.text()
    assert code_of(window) == code_text


def test_typing_in_a_cell_goes_through_the_same_edit(window, qt_app, code_text) -> None:
    code, params = page(window), panel(window)
    params.table.item(2, NAME).setText("solid")  # what the cell editor does on Enter
    for _ in range(5):
        qt_app.processEvents()
    assert "'solid': True," in code.editor.text() and code_of(window) == code_text
    assert params.table.item(2, NAME).text() == "solid"


def test_a_limit_alone_takes_the_default_as_the_other_end(window) -> None:
    code, params = page(window), panel(window)
    params.set_cell(0, MINIMUM, "")
    assert params.set_cell(0, MINIMUM, "0")
    assert "'r': (1.0, 0.0, 1.0)" in code.editor.text()


def test_remove_and_change_dialog(window) -> None:
    code, params = page(window), panel(window)
    params.choose("label")
    params.remove_chosen()
    assert "'label'" not in code.editor.text() and [r.name for r in params.rows] == ["r", "filled"]
    params.choose("r")
    params.ask_change = lambda row: ("2", "1", "4")
    params.change_chosen()
    assert "'r': (2.0, 1.0, 4.0)" in code.editor.text()
    params.ask_change = lambda row: None  # cancelled: nothing changes
    before = code.editor.text()
    params.change_chosen()
    assert code.editor.text() == before


def test_a_refused_edit_shows_the_reason_and_changes_nothing(window, code_text) -> None:
    code, params = page(window), panel(window)
    assert not params.set_cell(0, NAME, "label")
    assert "already has a parameter 'label'" in params.status.text()
    assert code.editor.text() == code_text and params.table.item(0, NAME).text() == "r"
    assert not params.set_cell(0, DEFAULT, "9")  # outside 0.5..3.0
    assert "is not from" in params.status.text()
    assert not params.set_cell(0, MAXIMUM, "x")
    assert "not a number" in params.status.text()
    assert code.editor.text() == code_text


def test_a_syntax_error_or_no_params_or_odd_params_keeps_it_disabled_with_a_note(window) -> None:
    code, params = page(window), panel(window)
    code.editor.setPlainText("PARAMS = {'a': 1}\ndef build(p:\n    return Dot()\n")
    params.refresh()
    assert not params.editable() and "syntax error on line 2" in params.note.text()
    code.editor.setPlainText("def build(p):\n    return Dot()\n")
    params.refresh()
    assert not params.editable() and params.note.text() == NO_PARAMS
    code.editor.setPlainText("PARAMS = dict(a=1)\ndef build(p):\n    return Dot()\n")
    params.refresh()
    assert not params.editable() and "not a plain" in params.note.text()
    code.editor.setPlainText("PARAMS = {'a': 1}\ndef build(p):\n    return Dot()\n")
    params.refresh()
    assert params.editable() and [r.name for r in params.rows] == ["a"]


def test_typing_refreshes_the_table_after_a_pause(window, qt_app) -> None:
    code, params = page(window), panel(window)
    code.editor.setPlainText(BASE.replace("'filled': True,\n", "'filled': True,\n    'n': (3, 1, 9),\n"))
    assert params._timer.isActive()
    params._timer.timeout.emit()
    assert cells(window)[-1] == ["n", "3", "1", "9"]


def test_parsing_typed_values() -> None:
    assert parse_default("2", 1.5) == 2.0 and isinstance(parse_default("2", 1.5), float)
    assert parse_default("2", 1) == 2 and parse_default("True") is True
    assert parse_default('"#ff0000"') == "#ff0000" and parse_default("#ff0000") == "#ff0000"
    with pytest.raises(ParamsEditError):
        parse_default("")
    with pytest.raises(ParamsEditError):
        parse_default("[1, 2]")
    assert parse_limit("") is None and parse_limit("2.5") == 2.5
    with pytest.raises(ParamsEditError):
        parse_limit("True")
