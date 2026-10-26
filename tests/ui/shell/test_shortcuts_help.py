"""Help > Keyboard Shortcuts (P6d.2, ADR 0044): read from the window's own actions."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QMenuBar

from manim_studio.ui.main_window import MainWindow
from manim_studio.ui.shell import shortcuts_help as sh

pytestmark = pytest.mark.ui


@pytest.fixture
def window(qt_app):
    win = MainWindow()
    win.resize(1100, 800)
    yield win
    win.close()


def test_rows_come_from_the_menus_with_their_paths(qt_app) -> None:
    bar = QMenuBar()
    file_menu = bar.addMenu("&File")
    save = file_menu.addAction("&Save...")
    save.setShortcut(QKeySequence("Ctrl+S"))
    file_menu.addAction("No keys")
    sub = file_menu.addMenu("&Recent")
    deep = sub.addAction("Fish && Chips")
    deep.setShortcuts([QKeySequence("Ctrl+1"), QKeySequence("Ctrl+2")])
    rows = sh.keyboard_rows(bar)
    assert rows == [
        sh.Row("File", "Save", "Ctrl+S"),
        sh.Row("File > Recent", "Fish & Chips", "Ctrl+1, Ctrl+2"),
    ]


def test_other_actions_of_the_window_join_once(qt_app) -> None:
    bar = QMenuBar()
    menu = bar.addMenu("Edit")
    shared = menu.addAction("Delete")
    shared.setShortcut(QKeySequence("Del"))
    holder = sh.ShortcutsDialog([])  # any widget holding actions
    extra = QAction("Bring forward", holder)
    extra.setShortcut(QKeySequence("Ctrl+]"))
    again = QAction("Delete", holder)
    again.setShortcut(QKeySequence("Del"))
    QAction("No shortcut", holder)
    rows = sh.keyboard_rows(bar, holder)
    assert sh.Row("Panels", "Bring forward", "Ctrl+]") in rows
    assert not any(row.what == "No shortcut" for row in rows)
    assert sum(row.what == "Delete" for row in rows) == 1


def test_search_needs_every_word_in_any_column() -> None:
    row = sh.Row("View > Pages", "Animate", "Shift+2")
    assert sh.matches(row, "")
    assert sh.matches(row, "shift+2")
    assert sh.matches(row, "pages animate")
    assert not sh.matches(row, "pages compose")


def test_f1_opens_the_table_of_every_shortcut_and_gesture(window, qt_app) -> None:
    dialog = window.show_shortcuts()
    qt_app.processEvents()
    assert dialog.isVisible() and dialog.windowTitle() == "Keyboard Shortcuts"
    whats = {row.what for row in dialog.rows}
    assert {"Save", "Undo", "Snap to Objects", "Align Left", "Keyboard Shortcuts", "Animate"} <= whats
    assert any(row.area == "Canvas" for row in dialog.rows)
    assert any(row.area == "Panels" and row.what == "Delete" for row in dialog.rows)
    assert dialog.table.rowCount() == len(dialog.rows)
    assert dialog.count.text() == f"{len(dialog.rows)} of {len(dialog.rows)}"
    dialog.search.setText("align")
    shown = dialog.visible_rows()
    assert shown and all("align" in f"{r.area} {r.what} {r.keys}".lower() for r in shown)
    assert dialog.count.text() == f"{len(shown)} of {len(dialog.rows)}"
    help_menu = next(a.menu() for a in window.menuBar().actions() if a.text() == "&Help")
    action = next(a for a in help_menu.actions() if a.text() == "&Keyboard Shortcuts...")
    assert action.shortcut().toString() == "F1"
    dialog.close()
