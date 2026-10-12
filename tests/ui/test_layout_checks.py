"""Layout checks (P6d.2, ADR 0044): over every page and the dialogs at a small window -
menu items explain themselves, nothing is squeezed below its minimum size, and labels
that neither wrap nor elide show all of their text.

New pages and dialogs are checked by themselves: the pages come from the window's page
host, the menus from its menu bar.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHeaderView, QLabel, QMenu, QWidget

from manim_studio.ui.main_window import MainWindow

pytestmark = pytest.mark.ui

DEMO = Path(__file__).resolve().parents[2] / "examples" / "euler.json"
SMALL = (1024, 640)
# Menu items whose words say everything, or whose text Qt changes (Undo "Move layer").
SELF_EXPLANATORY = {"Undo", "Redo"}
# Menus filled from data: a preset, a theme, a template, a page are named by what they are.
DATA_MENUS = ("Apply Preset", "Themes", "Pages", "Open Recent")
# Widgets whose minimum size hint is not a real need (a header's hint counts its sort arrow).
SQUEEZABLE = (QHeaderView,)


def plain(text: str) -> str:
    return text.replace("&", "").rstrip(".").strip()


def items(menu: QMenu, path: str):
    for action in menu.actions():
        if action.isSeparator():
            continue
        name = plain(action.text())
        if action.menu() is not None:
            if name in DATA_MENUS:
                continue
            yield from items(action.menu(), f"{path} > {name}")
        else:
            yield f"{path} > {name}", action


def unexplained(window) -> list[str]:
    out = []
    for top in window.menuBar().actions():
        for path, action in items(top.menu(), plain(top.text())):
            tip = plain(action.toolTip())
            if plain(action.text()) in SELF_EXPLANATORY:
                continue
            if (not tip or tip == plain(action.text())) and not action.statusTip():
                out.append(path)
    return out


def squeezed(root: QWidget) -> list[str]:
    out = []
    for widget in root.findChildren(QWidget):
        if not widget.isVisible() or widget.isWindow() or isinstance(widget, SQUEEZABLE):
            continue
        hint = widget.minimumSizeHint()
        if hint.width() <= 0 or hint.height() <= 0:
            continue
        if widget.width() + 1 < hint.width() or widget.height() + 1 < hint.height():
            name = f"{type(widget).__name__} {getattr(widget, 'text', lambda: '')()[:30]!r}"
            out.append(f"{name} {widget.size().toTuple()} < {hint.toTuple()}")
    return out


def clipped(root: QWidget) -> list[str]:
    out = []
    for label in root.findChildren(QLabel):
        if not label.isVisible() or label.wordWrap() or not label.text() or getattr(label, "elides", False):
            continue  # wrapping and eliding labels show their text another way
        if label.textFormat() == Qt.TextFormat.RichText or "<" in label.text():
            continue
        need = max(label.fontMetrics().horizontalAdvance(line) for line in label.text().splitlines())
        have = label.contentsRect().width() - 2 * label.margin() - label.indent() * (label.indent() > 0)
        if need > have + 1:
            out.append(f"{label.text()[:40]!r} needs {need} px, has {have}")
    return out


@pytest.fixture
def window(qt_app):
    win = MainWindow()
    win.resize(*SMALL)
    win.show()
    win.load(DEMO)
    qt_app.processEvents()
    yield win
    win.document.undo_stack.setClean()
    win.close()


def test_every_menu_item_explains_itself(window) -> None:
    assert unexplained(window) == []


@pytest.mark.parametrize("page", ["compose", "animate", "code", "audio", "deliver"])
def test_no_page_squeezes_or_clips_at_a_small_window(window, qt_app, page) -> None:
    if page not in window.pages.pages:
        pytest.skip(f"no {page} page yet")
    window.show_page(page)
    qt_app.processEvents()
    assert squeezed(window) == []
    assert clipped(window) == []


def test_dialogs_neither_squeeze_nor_clip(window, qt_app) -> None:
    for dialog in (window.show_shortcuts(), window.show_plugins()):
        qt_app.processEvents()
        assert squeezed(dialog) == [], dialog.windowTitle()
        assert clipped(dialog) == [], dialog.windowTitle()
        dialog.close()


def test_the_checks_catch_what_they_look_for(window, qt_app) -> None:
    """The checks themselves: a cramped label, a squeezed field and a bare menu item fail."""
    from PySide6.QtGui import QAction
    from PySide6.QtWidgets import QLineEdit, QPushButton

    host = window.viewer
    label = QLabel("a label far too long for the room it has been given", host)
    label.setFixedWidth(40)
    label.show()
    button = QPushButton("A rather long button caption", host)
    button.resize(20, 20)
    button.show()
    line = QLineEdit(host)
    line.setFixedSize(4, 4)
    line.show()
    qt_app.processEvents()
    assert any("far too long" in finding for finding in clipped(host))
    assert any(finding.startswith("QPushButton") for finding in squeezed(host))
    bare = QAction("Frobnicate", window)
    window.menuBar().actions()[0].menu().addAction(bare)
    assert any(path.endswith("Frobnicate") for path in unexplained(window))
    bare.setToolTip("Frobnicate the scene")
    assert not any(path.endswith("Frobnicate") for path in unexplained(window))
    for widget in (label, button, line):
        widget.deleteLater()
