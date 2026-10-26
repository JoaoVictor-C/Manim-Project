"""Errors with a hint and a syntax mark on the Code page (P13.1)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from manim_studio.core.model.schema import Canvas, Layer, Project, Spec
from manim_studio.ui.main_window import MainWindow

pytestmark = pytest.mark.ui


def make(qt_app, tmp_path, code: str) -> MainWindow:
    project = Project(
        canvas=Canvas(width_px=320, height_px=180, fps=10, duration=2.0),
        layers=[Layer(id="obj", name="Obj", spec=Spec(type="Python", params={"code": code}))],
    )
    path = tmp_path / "scene.json"
    path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.ask_trust = lambda names: "run"
    win.resize(1500, 850)
    win.show()
    win.load(path)
    win.show_page("code")
    win.selection.select_layer("obj")
    qt_app.processEvents()
    return win


@pytest.fixture
def broken(qt_app, tmp_path):
    win = make(qt_app, tmp_path, f"# {tmp_path.name}\ndef build(p):\n    return Circl()\n")
    yield win
    win.document.undo_stack.setClean()
    win.close()


def page(window):
    return window.pages.pages["code"]


def test_a_name_error_offers_the_name_it_probably_meant(broken) -> None:
    code = page(broken)
    assert code.error_label.isVisibleTo(code.output)
    assert not code.hint_label.isHidden() and "Circle" in code.hint_label.text()


def test_a_hint_goes_away_with_the_error(broken, qt_app) -> None:
    code = page(broken)
    fixed = code.editor.text().replace("Circl()", "Circle()")
    code.editor.setPlainText(fixed)
    code.run()
    for _ in range(20):
        qt_app.processEvents()
    assert code.hint_label.isHidden()


def test_a_syntax_error_is_marked_after_the_pause_but_not_on_the_line_being_typed(broken, qt_app) -> None:
    code = page(broken)
    code.editor.setPlainText("def build(p):\n    return Circle()\n\nx = = 1\n")
    code.editor.go_to_line(1)
    code.check_syntax()
    assert code.editor.syntax_problem is not None and not code.syntax_label.isHidden()
    code.editor.go_to_line(code.editor.syntax_problem[0])
    code.check_syntax()
    assert code.editor.syntax_problem is None  # the user is on that line


def test_an_open_triple_quote_is_not_marked_while_it_is_typed(broken) -> None:
    code = page(broken)
    code.editor.setPlainText('def build(p):\n    """still writing\n')
    code.editor.go_to_line(1)
    code.check_syntax()
    assert code.editor.syntax_problem is None


def test_the_fix_button_inserts_the_manim_import(broken) -> None:
    code = page(broken)
    code.editor.setPlainText("def build(p):\n    return Circle()\n")
    code._show_hint("NameError", "name 'Circle' is not defined", "")
    assert not code.fix_button.isHidden()
    code.fix_button.click()
    assert code.editor.text().startswith("from manim import *")
