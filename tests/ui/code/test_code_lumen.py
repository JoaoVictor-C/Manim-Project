"""The Code page in Lumen (P17.4d, ADR 0063): cards, explorer rows, the editor's chrome, the output card,
the chapters list, the dialog frame, both themes, and no key claimed twice."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QShortcut
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialogButtonBox

from manim_studio.core.code.scene_analysis import Analysis, Chapter, Statement
from manim_studio.core.exchange.code_export import ExportEntry
from manim_studio.core.model.schema import Canvas, Layer, Project, Spec
from manim_studio.ui.code.chapters import chapter_rows
from manim_studio.ui.code.code_chrome import CodeTabs, RunButton
from manim_studio.ui.code.code_explorer import ExplorerDelegate, row_chip
from manim_studio.ui.exchange.export_code_dialog import ExportCodeDialog
from manim_studio.ui.main_window import MainWindow
from manim_studio.ui.style import theme
from manim_studio.ui.style.card import Card, Chip

pytestmark = pytest.mark.ui

ORBIT = "class Orbit(Scene):\n    def construct(self):\n        self.add(Dot())\n"
OBJECT = "PARAMS = {}\n\ndef build(p):\n    return Circle()\n"


@pytest.fixture
def window(qt_app, tmp_path):
    project = Project(
        canvas=Canvas(width_px=320, height_px=180, fps=10, duration=2.0),
        layers=[
            Layer(id="orbit", name="Orbit", spec=Spec(type="Code", params={"code": ORBIT})),
            Layer(id="wheel", name="Wheel", spec=Spec(type="Python", params={"code": OBJECT})),
        ],
    )
    path = tmp_path / "scene.json"
    path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.ask_trust = lambda names: "skip"
    win.resize(1440, 900)
    win.show()
    win.load(path)
    win.show_page("code")
    qt_app.processEvents()
    yield win
    win.document.undo_stack.setClean()
    win.close()


def page(window):
    return window.pages.pages["code"]


def test_the_page_is_three_columns_of_cards(window) -> None:
    code = page(window)
    assert code.split.count() == 3
    assert isinstance(code.split.widget(0), Card) and code.split.widget(0).title() == "Explorer"
    for card in (code.editor_card, code.output_card, code.preview_card, code.chapters_card):
        assert isinstance(card, Card) and card.isVisibleTo(code.widget)
    assert code.editor_card.isAncestorOf(code.editor) and code.output_card.isAncestorOf(code.output)
    assert code.preview_card.isAncestorOf(window.viewer)  # the shared viewer sits in the preview card
    assert code.explorer_card.isAncestorOf(code.new_button) and code.new_button.property("role") == "primary"


def test_the_output_card_hides_with_its_toggle(window) -> None:
    code = page(window)
    code.output_toggle.setChecked(False)
    assert not code.output_card.isVisibleTo(code.widget) and not code.output.isVisibleTo(code.widget)
    code.toggle_output()
    assert code.output_card.isVisibleTo(code.widget)
    assert [code.output.tabText(i) for i in range(code.output.count())] == [
        "Output",
        "Values",
        "Parameters",
        "History",
    ]


def test_state_chips_and_the_run_button(window) -> None:
    code = page(window)
    code.show_layer("orbit")
    assert isinstance(code.dirty_label, Chip) and code.dirty_label.property("tone") == "warn"
    assert not code.dirty_label.isVisibleTo(code.widget)
    code.editor.insertPlainText("# more\n")
    assert code.dirty_label.isVisibleTo(code.widget)
    assert "●" in code.tabs.tabText(code.tabs.currentIndex())
    assert isinstance(code.run_button, RunButton) and code.run_button.property("hint") is True
    code.run_button.setText("Running…")
    assert code.run_button.property("hint") is False
    code.run_button.setText("Run")
    code.live_chip.setChecked(True)
    assert code.live_action.isChecked()
    code.live_action.setChecked(False)
    assert not code.live_chip.isChecked()


def test_the_explorer_paints_rows_with_kind_and_state_chips(window) -> None:
    code = page(window)
    assert isinstance(code.explorer.itemDelegate(), ExplorerDelegate)
    assert row_chip("error", True, "built") == ("unapplied", "warn")
    assert row_chip("error", False, "") == ("error", "bad")
    assert row_chip("", False, "built") == ("built", "ok")
    assert row_chip("", False, "built in") == ("built in", "neutral")
    assert row_chip("", False, "") is None
    top = code.explorer.topLevelItem(0)
    expanded = top.isExpanded()
    QTest.mouseClick(
        code.explorer.viewport(), Qt.MouseButton.LeftButton, pos=code.explorer.visualItemRect(top).center()
    )
    assert top.isExpanded() is (not expanded)  # a click on a section's label folds it


def test_tab_text_parts() -> None:
    assert CodeTabs.parts("Orbit") == ("Orbit", False, "")
    assert CodeTabs.parts("Orbit  ●") == ("Orbit", True, "")
    assert CodeTabs.parts("Orbit  ●  ⠋") == ("Orbit", True, "⠋")


def test_chapter_rows_say_lines_times_and_frames() -> None:
    def statement(index: int, first: int, last: int, text: str) -> Statement:
        return Statement(index, first, last, text, frozenset(), frozenset(), frozenset())

    analysis = Analysis(
        class_name="Orbit",
        ok=True,
        statements=[statement(0, 3, 4, "self.play(A())"), statement(1, 5, 7, "self.play(B())")],
        total_frames=100,
        fps=10,
        chapters=[Chapter(0, 1, 0, 60, 0.0), Chapter(1, 2, 60, None, 6.0)],
    )
    assert chapter_rows(analysis) == [
        (1, "self.play(A())", "lines 3 – 4 · 0:00 – 0:06", "60 frames"),
        (2, "self.play(B())", "lines 5 – 7 · 0:06 – 0:10", "40 frames"),
    ]
    assert chapter_rows(None) == [] and chapter_rows(Analysis()) == []


def test_both_themes_build_and_repaint(window, qt_app) -> None:
    code = page(window)
    code.show_layer("orbit")
    keyword = code.editor.highlighter.formats["keyword"].foreground().color().name()
    try:
        theme.set_theme(qt_app, "paper")
        qt_app.processEvents()
        assert not code.widget.grab().isNull()
        assert code.editor.highlighter.formats["keyword"].foreground().color().name() != keyword
    finally:
        theme.set_theme(qt_app, "ink")
    assert code.editor.highlighter.formats["keyword"].foreground().color().name() == keyword
    assert not code.widget.grab().isNull()


def test_dialogs_put_the_primary_action_last(qt_app) -> None:
    entry = ExportEntry("orbit", "Orbit", "scene", ORBIT, "project")
    dialog = ExportCodeDialog([entry], folder="")
    dialog.show()
    qt_app.processEvents()
    ok = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)
    cancel = dialog.buttons.button(QDialogButtonBox.StandardButton.Cancel)
    assert ok.property("role") == "primary" and dialog.property("lumen") is True
    assert ok.mapTo(dialog, ok.rect().topLeft()).x() > cancel.mapTo(dialog, cancel.rect().topLeft()).x()
    dialog.close()


def test_no_key_is_claimed_twice_on_the_code_page(window) -> None:
    """A key with two live shortcuts does nothing (Qt calls it ambiguous): the page's QShortcuts own them."""
    code = page(window)
    seen: dict[str, list[str]] = {}
    live = (
        Qt.ShortcutContext.WindowShortcut,
        Qt.ShortcutContext.ApplicationShortcut,
        Qt.ShortcutContext.WidgetWithChildrenShortcut,
    )
    for shortcut in code.widget.findChildren(QShortcut):
        if shortcut.isEnabled() and shortcut.context() in live:
            seen.setdefault(shortcut.key().toString(), []).append("QShortcut")
    actions = {id(a): a for a in code.widget.findChildren(QAction) + code.editor_menu.actions()}
    for action in actions.values():
        if action.isEnabled() and action.shortcutContext() in live:
            for key in action.shortcuts():
                seen.setdefault(key.toString(), []).append(action.text())
    assert {key: owners for key, owners in seen.items() if key and len(owners) > 1} == {}
