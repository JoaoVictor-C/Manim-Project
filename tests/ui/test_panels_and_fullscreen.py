"""Panel buttons on the page bar, Ctrl+1..5 for the pages, and full screen (P12)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest

from acceptance.test_acceptance_v1 import menu_action
from manim_studio.core.model.schema import Canvas, Layer, Project, Spec
from manim_studio.ui.main_window import MainWindow

pytestmark = pytest.mark.ui


def make_window(qt_app, tmp_path) -> MainWindow:
    project = Project(
        canvas=Canvas(width_px=320, height_px=180, fps=10, duration=2.0),
        layers=[Layer(id="dot", spec=Spec(type="Circle"))],
    )
    path = tmp_path / "scene.json"
    path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.resize(1400, 850)
    win.show()
    win.load(path)
    qt_app.processEvents()
    return win


@pytest.fixture
def window(qt_app, tmp_path):
    win = make_window(qt_app, tmp_path)
    yield win
    win.document.undo_stack.setClean()
    win.close()


def buttons(window) -> dict[str, object]:
    """The panel buttons by the panel they switch."""
    names = {
        window.layers_card: "layers",
        window.properties_card: "properties",
        window.timeline_card: "timeline",
    }
    return {names[view]: button for view, button in window.pages.panel_buttons}


def shown(window, name: str) -> bool:
    return buttons(window)[name].isVisibleTo(window.pages)


# -- Ctrl+1..5 ------------------------------------------------------------------------------


def test_every_page_has_ctrl_n_and_keeps_shift_n(window) -> None:
    for number, page in enumerate(window.pages.pages.values(), start=1):
        action = menu_action(window.menuBar(), "View", "Pages", page.title)
        assert [s.toString() for s in action.shortcuts()] == [f"Ctrl+{number}", f"Shift+{number}"]
        assert f"Ctrl+{number}" in page.tooltip


def test_the_keys_switch_pages(window, qt_app) -> None:
    for number, name in enumerate(window.pages.pages, start=1):
        QTest.keyClick(window, Qt.Key(Qt.Key.Key_0 + number), Qt.KeyboardModifier.ControlModifier)
        qt_app.processEvents()
        assert window.page == name, number
    QTest.keyClick(window, Qt.Key.Key_1, Qt.KeyboardModifier.ShiftModifier)
    qt_app.processEvents()
    assert window.page == "compose"


def test_actual_size_moved_off_ctrl_1(window) -> None:
    action = menu_action(window.menuBar(), "View", "Actual Size (100 %)")
    assert action.shortcuts() == [QKeySequence("Ctrl+Shift+0")]


# -- the panel buttons ------------------------------------------------------------------------


def test_compose_has_a_button_for_each_panel(window) -> None:
    window.show_page("compose")
    assert all(shown(window, name) for name in ("layers", "properties", "timeline"))
    assert all(button.isChecked() for button in buttons(window).values())


def test_a_button_hides_its_panel_and_the_view_menu_follows(window, qt_app) -> None:
    window.show_page("compose")
    buttons(window)["properties"].click()
    qt_app.processEvents()
    assert not window.properties.isVisibleTo(window)
    assert not window.panel_toggles[window.properties].isChecked()
    buttons(window)["timeline"].click()
    qt_app.processEvents()
    assert not window.timeline.isVisibleTo(window) and window.layers.isVisibleTo(window)
    buttons(window)["properties"].click()
    assert window.properties.isVisibleTo(window)


def test_the_view_menu_switches_the_button_too(window) -> None:
    window.show_page("compose")
    window.panel_toggles[window.layers].setChecked(False)
    assert not buttons(window)["layers"].isChecked() and not window.layers.isVisibleTo(window)
    window.panel_toggles[window.layers].setChecked(True)
    assert buttons(window)["layers"].isChecked()


def test_a_hidden_panel_stays_hidden_on_the_other_pages(window, qt_app) -> None:
    window.show_page("compose")
    buttons(window)["timeline"].click()
    window.show_page("animate")
    qt_app.processEvents()
    assert not window.timeline.isVisibleTo(window)
    window.show_page("compose")
    qt_app.processEvents()
    assert not window.timeline.isVisibleTo(window)


def test_buttons_only_show_for_the_panels_a_page_has(window, qt_app) -> None:
    window.show_page("animate")
    qt_app.processEvents()
    assert not shown(window, "layers") and shown(window, "properties") and shown(window, "timeline")
    window.show_page("code")
    qt_app.processEvents()
    assert not any(shown(window, name) for name in ("layers", "properties", "timeline"))
    window.show_page("deliver")
    qt_app.processEvents()
    assert not any(shown(window, name) for name in ("layers", "properties", "timeline"))
    window.show_page("compose")
    qt_app.processEvents()
    assert all(shown(window, name) for name in ("layers", "properties", "timeline"))


def test_hidden_panels_are_remembered_between_runs(qt_app, tmp_path) -> None:
    first = make_window(qt_app, tmp_path)
    first.show_page("compose")
    buttons(first)["layers"].click()
    first.document.undo_stack.setClean()
    first.close()
    second = make_window(qt_app, tmp_path)
    try:
        second.show_page("compose")
        qt_app.processEvents()
        assert not second.layers.isVisibleTo(second) and not buttons(second)["layers"].isChecked()
        assert second.properties.isVisibleTo(second)
    finally:
        second.document.undo_stack.setClean()
        second.close()


# -- full screen: the animation alone ---------------------------------------------------------


def test_the_menu_and_the_button_start_the_presenter(window, qt_app) -> None:
    action = menu_action(window.menuBar(), "View", "Full Screen")
    assert action.shortcut() == QKeySequence("F11") and action.toolTip()
    assert not window.presenter.active
    action.trigger()
    qt_app.processEvents()
    assert window.presenter.active and window.presenter.isFullScreen()
    action.trigger()  # again: leave
    qt_app.processEvents()
    assert not window.presenter.active and not window.presenter.isVisible()
    window.fullscreen_button.click()
    qt_app.processEvents()
    assert window.presenter.active
    window.presenter.finish()


def test_the_canvas_moves_into_the_presenter_plain_and_comes_back(window, qt_app) -> None:
    canvas = window.canvas
    window.show_page("compose")
    qt_app.processEvents()
    window.selection.select_layer("dot")
    window.refresh()
    assert canvas.outline is not None and canvas.parent() is window.stage
    before_view = canvas.view
    window.present()
    qt_app.processEvents()
    assert canvas.parent() is window.presenter and window.presenter.isFullScreen()
    assert not canvas.show_overlays and canvas.outline is None  # only the picture
    window.presenter.finish()
    qt_app.processEvents()
    assert canvas.parent() is window.stage and canvas.show_overlays and canvas.view == before_view
    assert window.stage.layout().indexOf(canvas) == 0 and canvas.isVisibleTo(window)


def test_the_editor_window_itself_is_not_made_full_screen(window, qt_app) -> None:
    window.present()
    qt_app.processEvents()
    assert not window.isFullScreen()
    window.presenter.finish()


def test_space_plays_and_pauses_and_arrows_step(window, qt_app) -> None:
    window.present()
    presenter = window.presenter
    QTest.keyClick(presenter, Qt.Key.Key_Space)
    assert window.play_timer.isActive()
    QTest.keyClick(presenter, Qt.Key.Key_Space)
    assert not window.play_timer.isActive()
    window.seek(0.0)
    QTest.keyClick(presenter, Qt.Key.Key_Right)
    assert window.t == pytest.approx(0.1)
    QTest.keyClick(presenter, Qt.Key.Key_Right, Qt.KeyboardModifier.ShiftModifier)
    assert window.t == pytest.approx(1.1)
    QTest.keyClick(presenter, Qt.Key.Key_Left)
    assert window.t == pytest.approx(1.0)
    QTest.keyClick(presenter, Qt.Key.Key_End)
    assert window.t == pytest.approx(2.0)
    QTest.keyClick(presenter, Qt.Key.Key_Home)
    assert window.t == 0.0
    presenter.finish()


@pytest.mark.parametrize("key", [Qt.Key.Key_Escape, Qt.Key.Key_F11])
def test_escape_and_f11_leave(window, qt_app, key) -> None:
    window.present()
    QTest.keyClick(window.presenter, key)
    qt_app.processEvents()
    assert not window.presenter.active and window.canvas.parent() is window.stage


def test_a_click_plays_and_pauses_without_selecting_or_moving(window, qt_app) -> None:
    window.selection.clear()
    window.present()
    qt_app.processEvents()
    canvas = window.canvas
    position = window.project.layer("dot").base.position
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.rect().center())
    assert window.play_timer.isActive() and window.selection.layer_id is None
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.rect().center())
    assert not window.play_timer.isActive()
    assert window.project.layer("dot").base.position == position
    window.presenter.finish()


def test_the_bar_goes_when_the_mouse_rests_while_playing_and_stays_when_paused(window, qt_app) -> None:
    window.present()
    presenter = window.presenter
    assert presenter.bar.isVisibleTo(presenter) and presenter.hint.isVisibleTo(presenter)
    presenter._rest()  # paused: the bar stays
    assert presenter.bar.isVisibleTo(presenter)
    window.play()
    presenter._rest()
    assert not presenter.bar.isVisibleTo(presenter)
    presenter.wake()
    assert presenter.bar.isVisibleTo(presenter)
    window.pause()
    presenter.finish()


def test_without_a_project_there_is_nothing_to_show(qt_app) -> None:
    win = MainWindow()
    win.resize(1200, 800)
    win.show()
    try:
        win.present()
        assert not win.presenter.active and "project" in win.statusBar().currentMessage()
    finally:
        win.close()


def test_closing_the_window_while_presenting_leaves_cleanly(qt_app, tmp_path) -> None:
    win = make_window(qt_app, tmp_path)
    win.present()
    win.document.undo_stack.setClean()
    win.close()
    assert not win.presenter.active and not win.presenter.isVisible()


def test_what_lies_outside_the_frame_is_black_while_presenting(window, qt_app) -> None:
    window.present()
    assert window.canvas.presenting
    window.presenter.finish()
    assert not window.canvas.presenting
