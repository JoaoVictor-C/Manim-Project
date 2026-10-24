"""Snippets, Run to cursor and Tab stops on the Code page (P13.3, P13.7)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from manim_studio.core import snippets
from manim_studio.core.schema import Canvas, Layer, Project, Spec
from manim_studio.ui.code_editor import CodeEditor
from manim_studio.ui.main_window import MainWindow
from manim_studio.ui.snippet_dialog import SnippetDialog

pytestmark = pytest.mark.ui

SCENE = (
    "class Orbit(Scene):\n"
    "    def construct(self):\n"
    "        a = Dot()\n"
    "        self.add(a)\n"
    "        self.wait()\n"
    "        b = Square()\n"
    "        self.add(b)\n"
)


@pytest.fixture
def editor(qt_app):
    widget = CodeEditor()
    widget.resize(500, 300)
    return widget


def test_a_snippet_on_a_blank_line_takes_its_place_with_the_lines_indent(editor) -> None:
    editor.setPlainText("def f():\n    x = 1\n    \n    y = 2\n")
    editor.go_to_line(3)
    editor.insert_snippet("a = ${1:1}\nb = ${2:2}\n$0")
    lines = editor.text().split("\n")
    assert lines[2:4] == ["    a = 1", "    b = 2"]
    assert lines[0] == "def f():" and lines[-2] == "    y = 2"


def test_a_snippet_on_a_code_line_goes_below_it_and_indents_after_a_colon(editor) -> None:
    editor.setPlainText("def construct(self):\n")
    editor.go_to_line(1)
    editor.insert_snippet("c = Circle()")
    assert editor.text().split("\n")[:2] == ["def construct(self):", "    c = Circle()"]


def test_a_module_level_snippet_sits_at_the_left_margin(editor) -> None:
    editor.setPlainText("    x = 1\n")
    editor.go_to_line(1)
    editor.insert_snippet("PARAMS = {}", module_level=True)
    assert editor.text().split("\n")[1] == "PARAMS = {}"


def test_the_first_stop_is_selected_and_tab_visits_the_rest_then_esc_stops(editor) -> None:
    editor.setPlainText("\n")
    editor.go_to_line(1)
    editor.insert_snippet("a = ${1:one}\nb = ${2:two}\n$0")
    assert editor.textCursor().selectedText() == "one"
    QTest.keyClick(editor, Qt.Key.Key_Tab)
    assert editor.textCursor().selectedText() == "two"
    QTest.keyClick(editor, Qt.Key.Key_Tab)  # the $0 stop: the cursor ends there
    assert editor.textCursor().selectedText() == ""
    QTest.keyClick(editor, Qt.Key.Key_Tab)  # no stops left: a normal Tab
    assert "\t" not in editor.text() and "    " in editor.text()


def test_typing_over_a_stop_keeps_the_others_in_place(editor) -> None:
    editor.setPlainText("\n")
    editor.go_to_line(1)
    editor.insert_snippet("a = ${1:one}\nb = ${2:two}")
    QTest.keyClicks(editor, "longer value")
    editor._completer.popup().hide()  # a name popup would take the Tab
    QTest.keyClick(editor, Qt.Key.Key_Tab)
    assert editor.textCursor().selectedText() == "two"


def test_every_snippet_can_be_inserted(editor) -> None:
    for snippet in snippets.SNIPPETS:
        editor.setPlainText("\n")
        editor.go_to_line(1)
        editor.insert_snippet(snippet.code, snippet.module_level)
        assert "${" not in editor.text() and "$0" not in editor.text(), snippet.id


def test_the_dialog_searches_and_chooses(qt_app) -> None:
    dialog = SnippetDialog()
    total = dialog.list.count()
    assert total == len(snippets.SNIPPETS) and dialog.chosen is None
    dialog.search.setText("circle")
    assert 0 < dialog.list.count() < total
    assert "Circle" in dialog.shown[0].title
    assert dialog.preview.toPlainText() and "${" not in dialog.preview.toPlainText()
    dialog.search.setText("zzzzqq")
    assert dialog.list.count() == 0 and not dialog.insert_button.isEnabled()
    dialog.search.setText("circle")
    dialog.accept()
    assert dialog.chosen is dialog.shown[0]


@pytest.fixture
def window(qt_app, tmp_path):
    code = SCENE + f"# {tmp_path.name}\n"
    project = Project(
        canvas=Canvas(width_px=320, height_px=180, fps=10, duration=2.0),
        layers=[Layer(id="orbit", name="Orbit", spec=Spec(type="Code", params={"code": code}))],
    )
    path = tmp_path / "scene.json"
    path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.ask_trust = lambda names: "skip"
    win.resize(1500, 850)
    win.show()
    win.load(path)
    win.show_page("code")
    win.selection.select_layer("orbit")
    qt_app.processEvents()
    yield win
    win.document.undo_stack.setClean()
    win.close()


def page(window):
    return window.pages.pages["code"]


def test_the_page_inserts_the_snippet_it_is_given(window) -> None:
    code = page(window)
    chosen = snippets.SNIPPETS[0]
    code.pick_snippet = lambda: chosen
    code.editor.go_to_line(5)
    code.insert_snippet()
    assert chosen.code.split("\n")[0].split("${")[0] in code.editor.text()


def test_run_to_cursor_shows_part_of_the_scene_and_the_editor_keeps_all_of_it(window, qt_app) -> None:
    code = page(window)
    full = code.editor.text()
    code.editor.go_to_line(4)  # self.add(a)
    code.run_to_cursor()
    for _ in range(20):
        qt_app.processEvents()
    applied = window.project.layer("orbit").spec.params["code"]
    assert "Square" not in applied and "Dot" in applied
    assert applied.count("\n") == full.count("\n")  # line numbers are kept
    assert code.editor.text() == full
    assert "up to line 4" in code.state_label.text()
    window.document.undo_stack.undo()
    for _ in range(20):
        qt_app.processEvents()
    assert "Square" in window.project.layer("orbit").spec.params["code"]


def test_run_to_cursor_outside_a_construct_says_so(window) -> None:
    code = page(window)
    code.editor.go_to_line(1)
    before = window.project.layer("orbit").spec.params["code"]
    code.run_to_cursor()
    assert window.project.layer("orbit").spec.params["code"] == before


def test_go_to_symbol_lists_the_outline_and_moves_the_cursor(window) -> None:
    code = page(window)
    offered: list = []

    def pick(items):
        offered.extend(items)
        return next(i for i in items if i.label == "construct")

    code.quick = pick
    code.go_to_symbol()
    assert {"Orbit", "construct"} <= {i.label for i in offered}
    assert code.editor.textCursor().blockNumber() + 1 == 2
