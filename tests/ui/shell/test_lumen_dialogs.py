"""The welcome and the dialogs in Lumen (ADR 0063, P17.4d): the hero, the cards, the shared dialog frame, in
both themes."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QPushButton

from manim_studio.ui.deliver.export_dialog import ExportDialog
from manim_studio.ui.shell import plugins_dialog, shortcuts_help, welcome
from manim_studio.ui.shell.new_project_dialog import CLASSIC, SMART, NewProjectDialog
from manim_studio.ui.style import theme
from manim_studio.ui.style.dialog_chrome import DialogFrame
from manim_studio.ui.style.icon_tile import IconTile

pytestmark = pytest.mark.ui


@pytest.fixture(autouse=True)
def back_to_ink(qt_app):
    yield
    theme.set_theme(qt_app, "ink")


def distinct_colours(widget, step: int = 6) -> int:
    image = widget.grab().toImage()
    return len(
        {
            image.pixelColor(x, y).name()
            for x in range(0, image.width(), step)
            for y in range(0, image.height(), step)
        }
    )


# -- the welcome --------------------------------------------------------------------------------


def test_the_welcome_has_a_hero_two_big_buttons_and_starting_points(qt_app) -> None:
    panel = welcome.WelcomePanel()
    panel.resize(1440, 860)
    panel.show()
    qt_app.processEvents()
    assert panel.title.accessibleName() == "Make mathematics move."
    assert panel.new_button.property("role") == "primary" and panel.new_button.hint.text() == "Ctrl N"
    assert panel.open_button.hint.text() == "Ctrl O" and panel.new_button.height() >= 44
    assert "Manim" in panel.subtitle.text()
    assert [card.text() for card in (panel._blank, panel._example)] == ["Blank scene", "Showcase"]


def test_the_welcome_signals_still_fire(qt_app) -> None:
    panel = welcome.WelcomePanel()
    seen: list[str] = []
    panel.newRequested.connect(lambda: seen.append("new"))
    panel.openRequested.connect(lambda: seen.append("open"))
    panel.exampleRequested.connect(lambda: seen.append("example"))
    panel.templateRequested.connect(lambda key: seen.append(f"template:{key}"))
    panel.new_button.click()
    panel.open_button.click()
    panel.example_button.click()
    panel._blank.click()
    panel._example.click()
    panel.set_templates([("graph", "Graph", "Axes and a curve")])
    panel.template_cards[0].click()
    assert seen == ["new", "open", "example", "new", "example", "template:graph"]


def test_recent_projects_are_cards_with_their_name_and_path(qt_app, tmp_path) -> None:
    files = []
    for name in ("one.json", "two.json", "three.json"):
        path = tmp_path / name
        path.write_text("{}", encoding="utf-8")
        files.append(path)
    panel = welcome.WelcomePanel()
    panel.resize(1200, 800)
    panel.show()
    opened: list[Path] = []
    panel.recentRequested.connect(opened.append)
    assert not panel.recent_heading.isVisible() and not panel.browse_card.isVisible()
    panel.set_recent(files)
    qt_app.processEvents()
    assert [card.text() for card in panel.recent_links] == ["one.json", "two.json", "three.json"]
    assert panel.recent_links[1].toolTip() == str(files[1]) and panel.recent_heading.isVisible()
    assert panel.browse_card.isVisible() and "today" in panel.recent_links[0].detail
    panel.recent_links[2].click()
    assert opened == [files[2]]
    panel.set_recent([])
    assert panel.recent_links == [] and not panel.recent_heading.isVisible()


def test_a_thumbnail_is_chosen_by_name_and_edited_text_says_when(qt_app, tmp_path) -> None:
    path = tmp_path / "x.json"
    path.write_text("{}", encoding="utf-8")
    mtime = path.stat().st_mtime
    assert welcome.edited_text(path, mtime + 100) == "Edited today"
    assert welcome.edited_text(path, mtime + 86400 * 1.5) == "Edited yesterday"
    assert welcome.edited_text(path, mtime + 86400 * 4) == "Edited 4 days ago"
    assert welcome.edited_text(path, mtime + 86400 * 9) == "Edited last week"
    assert welcome.edited_text(tmp_path / "gone.json") == ""


@pytest.mark.parametrize("name", ["ink", "paper"])
@pytest.mark.parametrize("size", [(1440, 860), (900, 560), (520, 560)])
def test_the_welcome_paints_in_both_themes_at_any_size(qt_app, name, size, tmp_path) -> None:
    theme.set_theme(qt_app, name)
    panel = welcome.WelcomePanel()
    panel.set_recent([tmp_path / f"p{i}.json" for i in range(7)])
    panel.resize(*size)
    panel.show()
    qt_app.processEvents()
    assert distinct_colours(panel) > 30
    assert panel.scroll.horizontalScrollBar().maximum() == 0  # it scrolls down, never sideways
    panel.close()


# -- dialogs ------------------------------------------------------------------------------------------


def test_the_new_project_dialog_has_a_header_option_cards_and_the_actions_at_the_right(qt_app) -> None:
    dialog = NewProjectDialog(remembered=CLASSIC)
    dialog.show()
    qt_app.processEvents()
    assert dialog.frame.title_label.text() == "New project" and dialog.windowTitle() == "New project"
    assert dialog.choice() == CLASSIC and dialog.classic_card.property("chosen") is True
    dialog.smart_card.radio.click()
    assert dialog.choice() == SMART and dialog.smart_card.property("chosen") is True
    assert dialog.classic_card.property("chosen") is False
    footer = dialog.frame.footer
    buttons = [footer.itemAt(i).widget() for i in range(footer.count()) if footer.itemAt(i).widget()]
    assert [b.text() for b in buttons] == ["Cancel", "Create project"]  # secondary first, primary last
    assert buttons[-1].property("role") == "primary" and buttons[-1].isDefault()
    dialog.classic_card.radio.setChecked(False)
    dialog.close()


def test_every_dialog_uses_the_shared_frame(qt_app, tmp_path) -> None:
    dialogs = [
        NewProjectDialog(),
        plugins_dialog.PluginsDialog(),
        shortcuts_help.ShortcutsDialog([shortcuts_help.Row("File", "Save", "Ctrl+S")]),
        ExportDialog(lambda: None, tmp_path / "out" / "x.mp4", tmp_path),
    ]
    for dialog in dialogs:
        assert isinstance(dialog.frame, DialogFrame) and dialog.property("lumen") is True
        assert isinstance(dialog.frame.tile, IconTile) and dialog.frame.title_label.text()
        assert dialog.frame.header.objectName() == "dialogHeader"
    export = dialogs[3]
    assert [export.export_button.property("role")] == ["primary"]
    assert export.open_button.parentWidget() is export.frame.footer_frame  # left of the actions
    assert dialogs[1].open_folder.text() == "Open Plugin Folder"
    assert dialogs[1].frame.description_label.text()


@pytest.mark.parametrize("name", ["ink", "paper"])
def test_the_dialogs_paint_in_both_themes(qt_app, name, tmp_path) -> None:
    theme.set_theme(qt_app, name)
    dialogs = [
        NewProjectDialog(),
        plugins_dialog.PluginsDialog(),
        shortcuts_help.ShortcutsDialog([shortcuts_help.Row("File", "Save", "Ctrl+S, Ctrl+Shift+S")] * 4),
        ExportDialog(lambda: None, tmp_path / "x.mp4", tmp_path),
    ]
    for dialog in dialogs:
        dialog.show()
        qt_app.processEvents()
        assert distinct_colours(dialog, 4) > 6, dialog.windowTitle()
        dialog.close()


def test_the_shortcuts_dialog_draws_keys_as_caps_and_mouse_gestures_as_text(qt_app) -> None:
    assert shortcuts_help.key_caps("Ctrl+S") == ["Ctrl+S"]
    assert shortcuts_help.key_caps("Ctrl+1, Shift+1") == ["Ctrl+1", "Shift+1"]
    assert shortcuts_help.key_caps("Drag on empty canvas (Shift: add)") == []
    assert shortcuts_help.key_caps("") == []
    dialog = shortcuts_help.ShortcutsDialog([shortcuts_help.Row("File", "Save", "Ctrl+S")])
    assert dialog.count.text() == "1 of 1" and isinstance(
        dialog.frame.footer.itemAt(0).widget(), type(dialog.count)
    )
    assert any(isinstance(b, QPushButton) and b.text() == "Close" for b in dialog.findChildren(QPushButton))
