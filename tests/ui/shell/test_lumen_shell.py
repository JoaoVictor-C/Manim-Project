"""The Lumen shell (ADR 0063): top bar, page switcher, transport pill, toasts and the command palette."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon, QUndoCommand
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget

from manim_studio.core.model.schema import Canvas, Layer, Project, Spec
from manim_studio.ui.main_window import MainWindow
from manim_studio.ui.playback.transport import SPEEDS, PlayButton, TransportPill
from manim_studio.ui.shell.palette import (
    CommandPalette,
    PaletteItem,
    collect_items,
    match_positions,
    rank_items,
)
from manim_studio.ui.style.fuzzy import score
from manim_studio.ui.style.page_switcher import PageSwitcher
from manim_studio.ui.style.toast import MAX_TOASTS, ToastHost, tone_of

pytestmark = pytest.mark.ui


@pytest.fixture
def window(qt_app, tmp_path):
    project = Project(
        canvas=Canvas(width_px=320, height_px=180, fps=10, duration=2.0),
        layers=[Layer(id="dot", spec=Spec(type="Circle")), Layer(id="box", spec=Spec(type="Square"))],
    )
    path = tmp_path / "scene.json"
    path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.resize(1400, 850)
    win.show()
    win.load(path)
    qt_app.processEvents()
    yield win
    win.document.undo_stack.setClean()
    win.close()


# -- fuzzy matching and ranking ------------------------------------------------------------------------


def test_fuzzy_matching_wants_the_letters_in_order_and_prefers_tight_starts() -> None:
    assert score("zz", "Layers") is None
    assert score("", "anything") == 0
    assert score("lay", "Layers") > score("lay", "Select all layers")  # the start and a run beat a scatter
    assert match_positions("lyr", "Layers") == [0, 2, 4]
    assert match_positions("xyz", "Layers") == []


def test_ranking_filters_by_prefix_kind_and_looks_in_the_menu_path_last() -> None:
    items = [
        PaletteItem("command", "Export Video", "File"),
        PaletteItem("command", "Add Circle", "Layer › New"),
        PaletteItem("layer", "Circle 1", "Circle layer"),
    ]
    assert {i.title for i in rank_items(items, "circ")} == {"Add Circle", "Circle 1"}
    assert [i.title for i in rank_items(items, ">circ")] == ["Add Circle"]
    assert [i.title for i in rank_items(items, "@circ")] == ["Circle 1"]
    assert [i.title for i in rank_items(items, "file")] == ["Export Video"]  # found through the menu path
    assert len(rank_items(items, "")) == 3


# -- the command palette -------------------------------------------------------------------------------


def test_the_palette_lists_the_menus_commands_and_the_layers(window) -> None:
    items = collect_items(window)
    kinds = {i.kind for i in items}
    assert kinds == {"command", "layer"}
    assert len([i for i in items if i.kind == "layer"]) == 2
    assert any(i.title == "Full Screen" and i.shortcut for i in items)


def test_the_palette_runs_the_chosen_item_on_enter(qt_app) -> None:
    ran: list[str] = []
    items = [
        PaletteItem("command", "Alpha", run=lambda: ran.append("a")),
        PaletteItem("command", "Beta", run=lambda: ran.append("b")),
        PaletteItem("command", "Off", enabled=False, run=lambda: ran.append("off")),
    ]
    palette = CommandPalette(items)
    palette.show()
    assert palette.list.count() == 3 and palette.list.currentRow() == 0
    palette.search.setText("bet")
    assert [i.title for i in palette.shown] == ["Beta"]
    QTest.keyClick(palette.search, Qt.Key.Key_Return)
    assert palette.chosen is not None and palette.chosen.title == "Beta"
    palette.search.setText("")
    palette.chosen = None
    palette.list.setCurrentRow(2)  # a disabled row cannot be chosen
    palette.search.returnPressed.emit()
    assert palette.chosen is None


def test_the_palette_arrows_move_and_stay_inside_the_list(qt_app) -> None:
    palette = CommandPalette([PaletteItem("command", n) for n in ("One", "Two", "Three")])
    palette.show()
    QTest.keyClick(palette, Qt.Key.Key_Down)
    QTest.keyClick(palette, Qt.Key.Key_Down)
    QTest.keyClick(palette, Qt.Key.Key_Down)
    assert palette.list.currentRow() == 2
    QTest.keyClick(palette, Qt.Key.Key_Up)
    assert palette.list.currentRow() == 1


def test_ctrl_k_opens_the_palette_and_the_search_button_asks_for_it(window) -> None:
    seen: list[bool] = []
    window.topbar.paletteRequested.connect(lambda: seen.append(True))
    opened: list[str] = []

    def close_it() -> None:  # the palette is modal: look at it, then close it
        opened.append(window.palette.search.placeholderText())
        window.palette.reject()

    QTimer.singleShot(0, close_it)
    window.topbar.search.click()
    assert seen == [True] and opened and opened[0].startswith("Search")
    assert window.palette_action.shortcut().toString() == "Ctrl+K"


# -- the page switcher ---------------------------------------------------------------------------------


def test_the_page_switcher_speaks_the_tab_bar_subset_and_emits_on_change(qt_app) -> None:
    switcher = PageSwitcher()
    for name in ("Compose", "Animate", "Code"):
        switcher.addTab(QIcon(), name)
    switcher.setTabData(1, "animate")
    switcher.setTabToolTip(1, "Animate")
    seen: list[int] = []
    switcher.currentChanged.connect(seen.append)
    assert switcher.count() == 3 and switcher.currentIndex() == 0 and switcher.tabText(2) == "Code"
    switcher.setCurrentIndex(1)
    switcher.setCurrentIndex(1)  # no change, no signal
    assert seen == [1] and switcher.tabData(1) == "animate" and switcher.tabData(9) is None


def test_the_page_switcher_clicks_and_arrows_and_keeps_icons_when_compact(qt_app) -> None:
    switcher = PageSwitcher()
    for name in ("Compose", "Animate", "Code"):
        switcher.addTab(QIcon(), name)
    switcher.show()
    wide = switcher.width()
    QTest.mouseClick(switcher, Qt.MouseButton.LeftButton, pos=switcher._segments[2].rect.center().toPoint())
    assert switcher.currentIndex() == 2
    QTest.keyClick(switcher, Qt.Key.Key_Left)
    assert switcher.currentIndex() == 1
    switcher.set_compact(True)
    assert switcher.is_compact() and switcher.sizeHint().width() < wide
    assert switcher.full_width() >= wide - 2 and switcher.is_compact()


def test_the_window_switcher_follows_the_pages(window) -> None:
    switcher = window.pages.bar
    assert [switcher.tabText(i) for i in range(switcher.count())][:2] == ["Compose", "Animate"]
    assert switcher.count() == 5
    window.pages.show_page("animate")
    assert switcher.tabData(switcher.currentIndex()) == "animate"
    QTest.keyClick(window, Qt.Key.Key_1, Qt.KeyboardModifier.ControlModifier)
    assert switcher.currentIndex() == 0


# -- the top bar ---------------------------------------------------------------------------------------


def test_the_top_bar_is_the_menu_bar_with_the_tools_in_its_right_corner(window) -> None:
    bar = window.topbar
    assert window.menuBar() is bar and bar.height() == 52
    assert bar.export_button.property("role") == "primary"
    assert bar.undo_button.isVisibleTo(bar) and bar.search.isVisibleTo(bar)
    right = bar._right.geometry()
    assert right.right() <= bar.width() and right.left() > bar.width() // 2


def test_the_undo_and_redo_buttons_follow_the_edit_menu(window) -> None:
    bar = window.topbar
    assert not bar.undo_button.isEnabled() and not bar.redo_button.isEnabled()
    window.document.undo_stack.push(QUndoCommand("Test edit"))
    assert bar.undo_button.isEnabled() and "Test edit" in bar.undo_button.toolTip()
    bar.undo_button.click()
    assert not bar.undo_button.isEnabled() and bar.redo_button.isEnabled()
    bar.redo_button.click()
    assert bar.undo_button.isEnabled()


def test_the_top_bar_turns_compact_in_a_narrow_window_and_back(window, qt_app) -> None:
    bar = window.topbar
    window.resize(1000, 700)
    qt_app.processEvents()
    assert bar.search._compact and bar.switcher.is_compact()
    window.resize(1500, 850)
    qt_app.processEvents()
    assert not bar.search._compact and not bar.switcher.is_compact()
    centre = bar.switcher.x() + bar.switcher.width() / 2
    assert abs(centre - bar.width() / 2) <= 2  # the switcher stays centred


def test_without_a_project_the_bar_keeps_only_the_menus_and_search(qt_app) -> None:
    win = MainWindow()
    win.resize(1400, 850)
    win.show()
    qt_app.processEvents()
    bar = win.topbar
    assert not bar.export_button.isVisibleTo(bar) and not bar.undo_button.isVisibleTo(bar)
    assert bar.search.isVisibleTo(bar)
    win.close()


# -- the transport pill --------------------------------------------------------------------------------


def make_pill(calls: list):
    from PySide6.QtWidgets import QSlider

    slider = QSlider(Qt.Orientation.Horizontal)
    pill = TransportPill(
        PlayButton(),
        slider,
        to_start=lambda: calls.append("start"),
        to_end=lambda: calls.append("end"),
        set_loop=lambda on: calls.append(("loop", on)),
        set_speed=lambda s: calls.append(("speed", s)),
    )
    return pill


def test_the_play_button_keeps_its_size_and_its_text_names_the_state(qt_app) -> None:
    button = PlayButton()
    button.show()
    assert (button.width(), button.height()) == (38, 38) and button.minimumSize().height() == 38
    assert button.text() == "Play"
    button.setText("Pause")
    button.repaint()
    assert button.text() == "Pause"


def test_the_pill_buttons_call_what_they_were_given(qt_app) -> None:
    calls: list = []
    pill = make_pill(calls)
    pill.show()
    pill.start_button.click()
    pill.end_button.click()
    pill.loop_button.click()
    assert calls == ["start", "end", ("loop", True)]
    assert set(pill.speed_actions) == set(SPEEDS)
    pill.speed_actions[1.5].trigger()
    assert calls[-1] == ("speed", 1.5) and pill.speed_button.text() == "1.5×"
    assert pill.speed_actions[1.5].isChecked() and not pill.speed_actions[1.0].isChecked()


def test_the_pill_shows_the_clock_and_goes_compact_when_the_room_is_short(qt_app) -> None:
    pill = make_pill([])
    pill.show()
    pill.set_time(65.5, 125.25)
    assert pill.time.text() == "1:05.50" and pill.total.text() == "/ 2:05.25"
    pill.fit(10_000)
    assert pill.slider.isVisibleTo(pill) and pill.speed_button.isVisibleTo(pill)
    pill.fit(200)
    assert not pill.slider.isVisibleTo(pill) and pill.time.isVisibleTo(pill)
    pill.set_loop(True)
    assert pill.loop_button.isChecked()


def test_the_window_pill_floats_inside_the_stage(window) -> None:
    window.pages.show_welcome(False)
    stage = window.viewer_card
    pill = window.transport
    assert pill.parentWidget() is not None and window.play_button.parentWidget() is pill
    assert stage.rect().contains(pill.geometry())


# -- toasts --------------------------------------------------------------------------------------------


def test_a_tone_is_guessed_from_the_words() -> None:
    assert tone_of("Export failed: ffmpeg is missing") == "bad"
    assert tone_of("Saved scene.json") == "ok"
    assert tone_of("Render is still running") == "warn"
    assert tone_of("2 clips selected") == "info"


def test_toasts_stack_expire_and_are_capped(qt_app) -> None:
    host_window = QWidget()
    host_window.resize(800, 600)
    host_window.show()
    host = ToastHost(host_window)
    for i in range(MAX_TOASTS + 2):
        host.show(f"Added {i}", timeout=0)
    assert len(host.active()) == MAX_TOASTS
    assert host.container.isVisible()
    newest = host.active()[-1]
    assert newest.tone == "ok" and newest.text_label.text() == f"Added {MAX_TOASTS + 1}"
    geometry = host.container.geometry()
    assert geometry.right() <= host_window.width() and geometry.bottom() <= host_window.height()
    newest.dismiss()
    assert len(host.active()) == MAX_TOASTS - 1
    host.clear()
    qt_app.processEvents()
    assert not host.active()
    host_window.close()


def test_a_toast_action_runs_once_and_dismisses(qt_app) -> None:
    host_window = QWidget()
    host_window.resize(800, 600)
    host_window.show()
    host = ToastHost(host_window)
    ran: list[int] = []
    toast = host.show("Layer deleted", action=("Undo", lambda: ran.append(1)), timeout=0)
    assert toast.action_button is not None
    toast.action_button.click()
    assert ran == [1] and toast.closing
    host_window.close()


def test_the_status_bar_message_also_becomes_a_toast_and_stays_readable(window) -> None:
    window.statusBar().showMessage("Copied 2 layers", 3000)
    assert window.statusBar().currentMessage() == "Copied 2 layers"
    assert window.toasts.active()[-1].text_label.text() == "Copied 2 layers"
    window.statusBar().showMessage("sticky")  # no timeout: a status line, not a toast
    assert window.toasts.active()[-1].text_label.text() == "Copied 2 layers"
