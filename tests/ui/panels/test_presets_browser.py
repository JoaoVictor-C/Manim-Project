"""The presets browser (P6d.3, ADR 0044): the pure rules (filter, target line, badge), then the
dialog through the real MainWindow - tabs, search, thumbnails, hover playing, applying to the
selection or a timeline row as one undo step, refusals, user presets, entry points."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QKeySequence, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from acceptance.test_acceptance_v1 import menu_action, timeline_menu
from manim_studio.core.editing import library
from manim_studio.core.model.schema import Canvas, Clip, Layer, Project, Spec
from manim_studio.render import preset_thumbs
from manim_studio.ui.main_window import MainWindow
from manim_studio.ui.panels import presets_browser as pb

pytestmark = pytest.mark.ui

BUILTIN = library.load_library([library.BUILTIN_FOLDER]).presets
BY_NAME = {p.name: p for p in BUILTIN}


# -- the pure rules -----------------------------------------------------------------------------------


def make(name: str, category="entrance", description="") -> library.Preset:
    return library.Preset(
        name=name,
        category=category,
        description=description,
        clips=[library.PresetClip(kinds=["FadeIn"], duration=0.5)],
    )


def test_filter_by_category_and_by_every_word_in_the_name_or_description() -> None:
    a = make("Fade in", "entrance", "Appears slowly")
    b = make("Fade out", "exit", "Disappears slowly")
    c = make("Pulse", "emphasis", "Beats like a heart")
    items = [b, c, a]
    assert pb.filter_presets(items, None, "") == [a, c, b]  # grouped by category, library order inside
    assert pb.filter_presets(items, "exit", "") == [b]
    assert pb.filter_presets(items, None, "FADE") == [a, b]  # not case sensitive
    assert pb.filter_presets(items, None, "fade slowly") == [a, b]  # name and description together
    assert pb.filter_presets(items, None, "fade dis") == [b]  # every word
    assert pb.filter_presets(items, "emphasis", "heart") == [c]  # description only
    assert pb.filter_presets(items, "exit", "heart") == []
    assert pb.filter_presets(items, None, "   ") == [a, c, b]  # blank: everything
    assert pb.filter_presets([], None, "") == []


def test_the_filter_keeps_the_order_of_each_category() -> None:
    first, second = make("Zeta"), make("Alpha")
    assert pb.filter_presets([first, make("Mid", "exit"), second], None, "") == [
        first,
        second,
        make("Mid", "exit"),
    ]


def test_the_target_line_says_what_apply_will_do() -> None:
    assert pb.target_text([], None, False) == pb.NO_LAYER
    assert pb.target_text(["Square"], None, False) == "Applies to Square at the playhead"
    assert pb.target_text(["a", "b", "c"], None, False) == "Applies to 3 selected layers at the playhead"
    assert pb.target_text(["Square"], 2.0, True) == "Applies to Square at 2.00 s"
    assert pb.target_text(["Square", "Title"], 1.25, True) == "Applies to Square at 1.25 s"  # one row


def test_a_preset_is_the_users_unless_it_is_the_built_in_of_its_name() -> None:
    assert not any(pb.is_user_preset(p) for p in BUILTIN)
    assert pb.is_user_preset(make("Mine"))
    changed = BY_NAME["Fade in"].model_copy(update={"description": "Changed"})
    assert pb.is_user_preset(changed)  # a user's file of a built-in's name


def test_a_thumbnail_tile_stands_out_from_the_grid_behind_it() -> None:
    assert pb.thumb_background() != pb.theme.THEME.field
    assert pb.theme.contrast(pb.thumb_background(), pb.theme.THEME.field) > 1.1


def test_badge_and_icons_keep_the_thumbnail_size_and_mark_only_the_copy(qt_app) -> None:
    frames = preset_thumbs.render_thumbnail(BY_NAME["Fade in"], "#141417")
    plain = pb.to_pixmap(frames[-1])
    assert (plain.width(), plain.height()) == (160, 90)
    marked = pb.with_badge(plain)
    assert (marked.width(), marked.height()) == (160, 90)
    assert marked.toImage() != plain.toImage() and plain.toImage() == pb.to_pixmap(frames[-1]).toImage()
    assert marked.toImage().pixelColor(0, 89) == plain.toImage().pixelColor(0, 89)  # far from the badge
    assert pb.placeholder().size() == plain.size()


# -- the dialog -----------------------------------------------------------------------------------------


@pytest.fixture
def window(qt_app, tmp_path, monkeypatch):
    monkeypatch.setenv("MANIM_STUDIO_LIBRARY", str(tmp_path / "library"))  # the user's own presets
    project = Project(
        canvas=Canvas(width_px=320, height_px=180, fps=10, duration=6.0),
        layers=[
            Layer(id="sq", name="Square", spec=Spec(type="Square")),
            Layer(id="tx", name="Title", spec=Spec(type="Text", params={"text": "Hi"})),
        ],
    )
    path = tmp_path / "scene.json"
    path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.resize(1100, 800)
    win.show()
    win.load(path)
    yield win
    win.close()


def browse(window, layer_id=None, t=None) -> pb.PresetsBrowser:
    if layer_id is None:
        menu_action(window.menuBar(), "Animate", "Browse Presets...").trigger()
    else:
        menu_action(timeline_menu(window, layer_id, t), "Browse presets...").trigger()
    assert window.presets_browser is not None
    return window.presets_browser


def centre(qt_app, browser, name):
    item = browser.item(name)
    browser.grid.scrollToItem(item)
    qt_app.processEvents()
    return browser.grid.visualItemRect(item).center()


def click(qt_app, browser, name, double=False):
    pos = centre(qt_app, browser, name)
    QTest.mouseClick(browser.grid.viewport(), Qt.MouseButton.LeftButton, pos=pos)
    if double:  # the second press arrives as a double-click event (QTest's own lone one is dropped)
        QTest.mouseDClick(browser.grid.viewport(), Qt.MouseButton.LeftButton, pos=pos)


def hover(qt_app, browser, name):
    pos = QPointF(centre(qt_app, browser, name))
    event = QMouseEvent(
        QEvent.Type.MouseMove,
        pos,
        QPointF(browser.grid.viewport().mapToGlobal(pos.toPoint())),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(browser.grid.viewport(), event)


def leave(browser):
    QApplication.sendEvent(browser.grid.viewport(), QEvent(QEvent.Type.Leave))


def shown(browser, name):
    return browser.item(name).icon().pixmap(160, 90).toImage()


def type_in_search(browser, text):
    browser.search.setText(text)


def test_animate_menu_opens_a_non_modal_browser_with_a_tooltip_and_shortcut(window) -> None:
    action = menu_action(window.menuBar(), "Animate", "Browse Presets...")
    assert action.shortcut() == QKeySequence("Ctrl+Shift+P")
    assert action.toolTip() and "preview" in action.toolTip()
    assert window.presets_browser is None  # nothing is drawn until it is asked for
    browser = browse(window)
    assert browser.isVisible() and not browser.isModal()
    assert browser.windowTitle() == "Presets"
    assert browser.parent() is window
    again = browse(window)
    assert again is browser  # one dialog, kept
    assert not any(w.text() == "Browse Presets..." for w in window.menuBar().actions())


def test_no_other_action_uses_the_browsers_shortcut(window) -> None:
    keys = QKeySequence("Ctrl+Shift+P")
    users = []
    for action in window.findChildren(type(menu_action(window.menuBar(), "Animate", "Browse Presets..."))):
        if keys in action.shortcuts():
            users.append(action.text())
    assert users == ["&Browse Presets..."]


def test_all_tab_lists_every_preset_grouped_by_category(window) -> None:
    browser = browse(window)
    assert browser.category is None and browser.tabs.tabText(0) == "All"
    assert browser.names() == [p.name for p in pb.filter_presets(window.library.presets, None, "")]
    assert len(browser.names()) == len(window.library.presets) >= 32
    assert [browser.tabs.tabText(i) for i in range(browser.tabs.count())] == [
        "All",
        "Entrance",
        "Emphasis",
        "Exit",
        "Motion",
    ]


@pytest.mark.parametrize("index", [1, 2, 3, 4])
def test_a_category_tab_lists_only_its_presets(window, index) -> None:
    browser = browse(window)
    browser.tabs.setCurrentIndex(index)
    category = library.CATEGORIES[index - 1]
    assert browser.category == category
    assert browser.names() == [p.name for p in window.library.presets_in(category)]
    assert browser.names()
    browser.tabs.setCurrentIndex(0)
    assert len(browser.names()) == len(window.library.presets)


def test_search_matches_names_and_descriptions_and_combines_with_the_tab(window) -> None:
    browser = browse(window)
    type_in_search(browser, "fade")
    assert set(browser.names()) >= {"Fade in", "Fade out"}
    assert all("fade" in f"{p.name} {p.description}".lower() for p in (BY_NAME[n] for n in browser.names()))
    browser.tabs.setCurrentIndex(3)  # Exit
    assert "Fade out" in browser.names() and "Fade in" not in browser.names()
    browser.tabs.setCurrentIndex(0)
    type_in_search(browser, "LETTER BY LETTER")  # a description, any case
    assert browser.names() == ["Typewriter"]
    type_in_search(browser, "zzzz")
    assert browser.names() == [] and browser.status.text() == "No presets match"
    assert not browser.apply_button.isEnabled()
    type_in_search(browser, "")
    assert len(browser.names()) == len(window.library.presets)
    assert browser.status.text() != "No presets match"


def test_cards_have_the_description_as_tooltip_a_thumbnail_and_no_mark_for_built_ins(window) -> None:
    browser = browse(window)
    for preset in window.library.presets:
        item = browser.item(preset.name)
        assert item.toolTip() == (preset.description or preset.name)
        assert item.data(pb.PRESET_ROLE) == preset
        assert item.data(pb.USER_ROLE) is False
        assert not item.icon().isNull()
    assert browser.item("Pop in").toolTip().startswith("Fades in while growing")
    still = shown(browser, "Pop in")
    assert still.size().width() == 160 and still.size().height() == 90


def test_the_still_is_a_frame_from_the_middle_of_the_run(window) -> None:
    browser = browse(window)
    frames = preset_thumbs.thumbnails(BY_NAME["Fade in"], pb.thumb_background())
    expected = pb.to_pixmap(frames[preset_thumbs.STILL]).toImage()
    assert shown(browser, "Fade in") == expected
    assert expected != pb.to_pixmap(frames[0]).toImage() != pb.to_pixmap(frames[-1]).toImage()


def test_hovering_a_card_plays_its_frames_and_leaving_puts_the_still_back(window, qt_app) -> None:
    browser = browse(window)
    name = "Slide in from left"
    frames = [
        pb.to_pixmap(f).toImage() for f in preset_thumbs.thumbnails(BY_NAME[name], pb.thumb_background())
    ]
    still = shown(browser, name)
    assert browser.playing is None and not browser.timer.isActive()
    hover(qt_app, browser, name)
    assert browser.playing == name and browser.timer.isActive()
    assert shown(browser, name) == frames[0] != still  # it starts from the start of the run
    seen = [shown(browser, name)]
    for _ in range(preset_thumbs.FRAMES - 1):
        browser.timer.timeout.emit()
        seen.append(shown(browser, name))
    assert seen == frames  # every frame, in order
    browser.timer.timeout.emit()
    assert shown(browser, name) == frames[0]  # and round again
    assert browser.frame == 0
    leave(qt_app and browser)
    assert browser.playing is None and not browser.timer.isActive()
    assert shown(browser, name) == still


def test_moving_to_another_card_stops_the_first_and_plays_the_second(window, qt_app) -> None:
    browser = browse(window)
    first, second = "Fade in", "Pop in"
    still = shown(browser, first)
    hover(qt_app, browser, first)
    browser.timer.timeout.emit()
    hover(qt_app, browser, first)  # moving inside the same card does not restart it
    assert browser.frame == 1
    hover(qt_app, browser, second)
    assert browser.playing == second and shown(browser, first) == still
    assert browser.frame == 0


def test_rebuilding_the_cards_while_one_plays_stops_it(window, qt_app) -> None:
    browser = browse(window)
    hover(qt_app, browser, "Fade in")
    assert browser.timer.isActive()
    type_in_search(browser, "pop")
    assert browser.playing is None and not browser.timer.isActive()
    browser.timer.timeout.emit()  # a late tick is harmless
    assert browser.names() == ["Pop in"]


def test_closing_the_dialog_stops_the_playing_card(window, qt_app) -> None:
    browser = browse(window)
    hover(qt_app, browser, "Fade in")
    browser.close_button.click()
    assert not browser.isVisible() and browser.playing is None and not browser.timer.isActive()


def test_thumbnails_are_drawn_when_it_opens_and_kept_afterwards(window, monkeypatch) -> None:
    drawn = []
    real = preset_thumbs.render_thumbnail
    monkeypatch.setattr(preset_thumbs, "render_thumbnail", lambda p, b: drawn.append(p.name) or real(p, b))
    preset_thumbs.clear_cache()
    browser = browse(window)
    assert sorted(drawn) == sorted(p.name for p in window.library.presets)  # all at once, on open
    browser.close()
    browse(window)
    type_in_search(browser, "fade")
    browser.tabs.setCurrentIndex(2)
    assert len(drawn) == len(window.library.presets)  # no second drawing


# -- applying -------------------------------------------------------------------------------------------


def test_apply_button_applies_the_chosen_card_to_the_selection_in_one_step(window, qt_app) -> None:
    browser = browse(window)
    assert not browser.apply_button.isEnabled()  # nothing chosen yet
    window.selection.set("sq")
    window.seek(1.0)
    click(qt_app, browser, "Indicate")
    assert browser.apply_button.isEnabled()
    steps = window.document.undo_stack.count()
    browser.apply_button.click()
    (clip,) = window.project.layer("sq").clips
    assert (clip.kind, clip.start) == ("Indicate", 1.0)
    assert window.document.undo_stack.count() == steps + 1
    assert window.document.undo_stack.undoText() == "Apply Indicate"
    assert browser.isVisible()  # open for the next one
    assert browser.status.text() == window.statusBar().currentMessage() == "Indicate at 1.00 s"


def test_double_click_applies_the_card(window, qt_app) -> None:
    browser = browse(window)
    window.selection.set("sq")
    window.seek(2.0)
    click(qt_app, browser, "Fade out", double=True)
    (clip,) = window.project.layer("sq").clips
    assert (clip.kind, clip.start) == ("FadeOut", 2.0)
    assert len(window.project.layer("sq").clips) == 1  # once, not once per click


def test_enter_applies_the_current_card(window, qt_app) -> None:
    browser = browse(window)
    window.selection.set("sq")
    browser.grid.setCurrentItem(browser.item("Indicate"))
    browser.grid.setFocus()
    QApplication.sendEvent(
        browser.grid,
        QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier),
    )
    assert [c.kind for c in window.project.layer("sq").clips] == ["Indicate"]


def test_enter_in_the_search_field_does_not_apply_anything(window, qt_app) -> None:
    browser = browse(window)
    window.selection.set("sq")
    click(qt_app, browser, "Indicate")
    browser.search.setFocus()
    QTest.keyClick(browser.search, Qt.Key.Key_Return)
    assert window.project.layer("sq").clips == []


def test_several_selected_layers_get_the_preset_in_one_undo_step(window, qt_app) -> None:
    browser = browse(window)
    window.selection.set_layers(["sq", "tx"])
    window.seek(0.5)
    assert browser.status.text() == "Applies to 2 selected layers at the playhead"
    steps = window.document.undo_stack.count()
    click(qt_app, browser, "Indicate", double=True)
    for layer_id in ("sq", "tx"):
        (clip,) = window.project.layer(layer_id).clips
        assert (clip.kind, clip.start) == ("Indicate", 0.5)
    assert window.document.undo_stack.count() == steps + 1
    assert window.document.undo_stack.undoText() == "Apply Indicate"
    window.document.undo_stack.undo()
    assert window.project.layer("sq").clips == [] and window.project.layer("tx").clips == []
    assert window.document.undo_stack.count() == steps + 1  # one step undone, none left over


def test_a_refusal_shows_in_the_dialog_and_the_status_bar_and_changes_nothing(window, qt_app) -> None:
    browser = browse(window)
    window.selection.set_layers(["sq", "tx"])
    window.seek(5.8)  # the scene ends at 6 s
    before = window.project
    steps = window.document.undo_stack.count()
    click(qt_app, browser, "Fade out", double=True)
    assert window.project == before and window.document.undo_stack.count() == steps
    assert "the scene ends at 6 s" in browser.status.text()
    assert browser.status.text() == window.statusBar().currentMessage()
    assert browser.isVisible()


def test_a_preset_one_selected_layer_refuses_goes_on_none_of_them(window, qt_app) -> None:
    taken = window.project.layer("tx").model_copy(
        update={"clips": [Clip(id="busy", kind="FadeIn", start=0.5, duration=1.0)]}
    )
    window.document.replace(window.project.model_copy(update={"layers": [window.project.layer("sq"), taken]}))
    browser = browse(window)
    window.selection.set_layers(["sq", "tx"])  # the square is fine, the title is busy then
    window.seek(0.5)
    before = window.project
    steps = window.document.undo_stack.count()
    click(qt_app, browser, "Indicate", double=True)
    assert window.project == before and window.document.undo_stack.count() == steps
    assert browser.status.text().startswith("Title: ")  # which layer stopped it
    assert window.project.layer("sq").clips == []


def test_without_a_selection_the_dialog_says_so(window, qt_app) -> None:
    window.selection.clear()
    browser = browse(window)
    assert browser.status.text() == pb.NO_LAYER
    click(qt_app, browser, "Fade in", double=True)
    assert browser.status.text() == "Select a layer to animate first" == window.statusBar().currentMessage()
    assert window.project.layer("sq").clips == []
    window.selection.set("sq")  # choosing a layer updates the line
    assert browser.status.text() == "Applies to Square at the playhead"
    window.selection.set("tx")
    assert browser.status.text() == "Applies to Title at the playhead"


def test_apply_without_a_chosen_card_says_so(window) -> None:
    browser = browse(window)
    assert browser.apply_current() is False
    assert browser.status.text() == "Choose a preset first"


def test_apply_returns_whether_it_worked(window, qt_app) -> None:
    browser = browse(window)
    window.selection.set("sq")
    click(qt_app, browser, "Indicate")
    assert browser.apply_current() is True
    window.selection.clear()
    assert browser.apply_current() is False


def test_the_filtered_card_stays_chosen_when_it_is_still_shown(window, qt_app) -> None:
    browser = browse(window)
    click(qt_app, browser, "Pop in")
    type_in_search(browser, "in")
    assert browser.grid.currentItem().text() == "Pop in"
    type_in_search(browser, "zzzz")
    assert browser.grid.currentItem() is None and not browser.apply_button.isEnabled()


# -- from the timeline row ----------------------------------------------------------------------------


def test_the_timeline_row_menu_has_a_browse_item_next_to_apply_preset(window) -> None:
    menu = timeline_menu(window, "sq", 2.0)
    titles = [a.text() for a in menu.actions()]
    assert titles.index("Browse presets...") == titles.index("Apply preset") + 1
    action = menu_action(menu, "Browse presets...")
    assert "preview" in action.toolTip() and menu.toolTipsVisible()


def test_from_a_row_the_preset_goes_to_that_layer_at_that_time_only(window, qt_app) -> None:
    window.selection.set_layers(["sq", "tx"])  # both selected, the row clicked is the square's
    browser = browse(window, "sq", 2.0)
    assert browser.fixed_layer == "sq" and browser.fixed_time == 2.0
    assert browser.status.text() == "Applies to Square at 2.00 s"
    window.seek(0.0)
    steps = window.document.undo_stack.count()
    click(qt_app, browser, "Indicate", double=True)
    (clip,) = window.project.layer("sq").clips
    assert (clip.kind, clip.start) == ("Indicate", 2.0)
    assert window.project.layer("tx").clips == []
    assert window.document.undo_stack.count() == steps + 1


def test_the_menu_after_a_row_goes_back_to_the_selection_and_playhead(window, qt_app) -> None:
    browse(window, "sq", 2.0)
    browser = browse(window)
    assert browser.fixed_layer is None and browser.fixed_time is None
    window.selection.set("tx")
    window.seek(1.0)
    click(qt_app, browser, "Fade in", double=True)
    assert window.project.layer("sq").clips == []
    (clip,) = window.project.layer("tx").clips
    assert clip.start == 1.0


def test_a_row_deleted_since_the_menu_is_not_a_crash(window, qt_app) -> None:
    browser = browse(window, "sq", 2.0)
    window.document.replace(window.project.model_copy(update={"layers": [window.project.layer("tx")]}))
    click(qt_app, browser, "Fade in", double=True)
    assert browser.status.text() == "That layer is gone: select the layers to animate"
    assert browser.fixed_layer is None
    assert browser.apply_current() is False  # now it is the (empty) selection's
    assert browser.status.text() == pb.NO_LAYER or "Select a layer" in browser.status.text()


def test_the_line_survives_the_row_being_deleted_while_the_dialog_is_open(window) -> None:
    browser = browse(window, "sq", 2.0)
    window.document.replace(window.project.model_copy(update={"layers": [window.project.layer("tx")]}))
    window.selection.set("tx")  # the line is rebuilt: no row to name, so it names the selection
    assert browser.status.text() == "Applies to Title at the playhead"


def test_the_numeric_keypad_enter_applies_too(window, qt_app) -> None:
    browser = browse(window)
    window.selection.set("sq")
    browser.grid.setCurrentItem(browser.item("Indicate"))
    QApplication.sendEvent(
        browser.grid,
        QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Enter, Qt.KeyboardModifier.NoModifier),
    )
    assert [c.kind for c in window.project.layer("sq").clips] == ["Indicate"]


def test_the_empty_messages_say_why_there_are_no_cards(window) -> None:
    browser = browse(window)
    type_in_search(browser, "zzzz")
    window.selection.set("sq")  # a new line about the target must not replace "No presets match"
    assert browser.status.text() == "No presets match"
    window.library.presets.clear()
    browser.reload()
    type_in_search(browser, "")
    assert browser.names() == [] and browser.status.text() == "There are no presets"


def test_a_card_without_a_description_has_its_name_as_tooltip(window) -> None:
    save_a_preset(window, "Plain")
    browser = browse(window)
    assert browser.item("Plain").toolTip() == "Plain"


def test_frames_become_pixmaps_with_their_colours(qt_app) -> None:
    import numpy as np

    frame = np.zeros((2, 3, 4), dtype=np.uint8)
    frame[0, 1] = (0x3B, 0x82, 0xF6, 255)
    image = pb.to_pixmap(frame).toImage()
    assert (image.width(), image.height()) == (3, 2)
    assert image.pixelColor(1, 0).getRgb() == (0x3B, 0x82, 0xF6, 255)
    assert image.pixelColor(0, 0).getRgb() == (0, 0, 0, 0)


# -- the user's own presets -------------------------------------------------------------------------------


def save_a_preset(window, name="My grow", category="entrance"):
    window.document.replace(
        window.project.model_copy(
            update={
                "layers": [
                    window.project.layer("sq").model_copy(
                        update={"clips": [Clip(id="g", kind="GrowFromCenter", start=0.5, duration=0.7)]}
                    ),
                    window.project.layer("tx"),
                ]
            }
        )
    )
    window.selection.set("sq")
    window.ask_preset_name = lambda: (name, category)
    menu_action(window.menuBar(), "Animate", "Save Animation as Preset...").trigger()


def test_a_saved_preset_appears_marked_as_the_users_own(window, qt_app) -> None:
    save_a_preset(window)
    browser = browse(window)
    item = browser.item("My grow")
    assert item.data(pb.USER_ROLE) is True and item.data(pb.PRESET_ROLE).name == "My grow"
    assert [browser.item(n).data(pb.USER_ROLE) for n in ("Fade in", "Pop in")] == [False, False]
    plain = pb.to_pixmap(preset_thumbs.thumbnails(item.data(pb.PRESET_ROLE), pb.thumb_background())[4])
    assert shown(browser, "My grow") != plain.toImage()  # the "Yours" badge is on it
    browser.tabs.setCurrentIndex(1)
    assert "My grow" in browser.names()
    browser.tabs.setCurrentIndex(3)
    assert "My grow" not in browser.names()
    window.selection.set("tx")
    window.seek(3.0)
    browser.tabs.setCurrentIndex(0)
    click(qt_app, browser, "My grow", double=True)
    (clip,) = window.project.layer("tx").clips
    assert (clip.kind, clip.start, clip.duration) == ("GrowFromCenter", 3.0, 0.7)


def test_a_preset_saved_while_the_browser_is_open_appears_at_once(window) -> None:
    browser = browse(window)
    assert "Late one" not in browser.names()
    save_a_preset(window, "Late one")
    assert browser.isVisible() and "Late one" in browser.names()
    assert browser.item("Late one").data(pb.USER_ROLE) is True


def test_a_user_preset_of_a_built_in_name_is_marked_and_wins(window) -> None:
    save_a_preset(window, "Fade in")
    browser = browse(window)
    assert browser.names().count("Fade in") == 1
    assert browser.item("Fade in").data(pb.USER_ROLE) is True
    assert browser.item("Fade in").data(pb.PRESET_ROLE).clips[0].kinds == ["GrowFromCenter"]


def test_a_preset_a_square_cannot_show_gets_a_placeholder_and_stays_still(window, qt_app) -> None:
    text_only = library.Preset(
        name="Letters",
        category="entrance",
        description="Only for text",
        clips=[library.PresetClip(kinds=["AddTextLetterByLetter"], duration=1.0)],
    )
    window.library.add(text_only)
    browser = browse(window)
    assert shown(browser, "Letters") == pb.with_badge(pb.placeholder()).toImage()
    hover(qt_app, browser, "Letters")
    assert browser.playing is None and not browser.timer.isActive()
    window.selection.set("tx")  # it still applies to the text it is for
    click(qt_app, browser, "Letters", double=True)
    assert [c.kind for c in window.project.layer("tx").clips] == ["AddTextLetterByLetter"]


def test_close_button_hides_and_the_menu_shows_the_same_dialog_again(window) -> None:
    browser = browse(window)
    browser.close_button.click()
    assert not browser.isVisible()
    assert browse(window) is browser and browser.isVisible()


def test_escape_closes_the_dialog(window) -> None:
    browser = browse(window)
    QTest.keyClick(browser, Qt.Key.Key_Escape)
    assert not browser.isVisible()


def test_buttons_have_tooltips_and_the_search_has_a_hint(window) -> None:
    browser = browse(window)
    assert browser.apply_button.toolTip() and browser.close_button.toolTip() and browser.search.toolTip()
    assert browser.search.placeholderText() and browser.search.isClearButtonEnabled()
