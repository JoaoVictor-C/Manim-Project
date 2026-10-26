"""The full-screen player's controls (P12): the seek bar, the transport, repeat, speed, volume."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from manim_studio.core.model.schema import Canvas, Layer, Project, Spec
from manim_studio.ui.main_window import MainWindow
from manim_studio.ui.playback import player_bar
from manim_studio.ui.playback.audio_player import FakePlayer

pytestmark = pytest.mark.ui


@pytest.fixture
def window(qt_app, tmp_path):
    project = Project(
        canvas=Canvas(width_px=320, height_px=180, fps=10, duration=4.0),
        layers=[Layer(id="dot", spec=Spec(type="Circle"))],
    )
    path = tmp_path / "Lesson.json"
    path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.resize(1400, 850)
    win.show()
    win.load(path)
    qt_app.processEvents()
    win.present()
    qt_app.processEvents()
    yield win
    win.presenter.finish()
    win.pause()
    win.document.undo_stack.setClean()
    win.close()


def bar(window):
    return window.presenter.bar


# -- the pieces -----------------------------------------------------------------------------


def test_the_clock_shows_minutes_seconds_and_hundredths() -> None:
    assert player_bar.clock(0) == "0:00.00" and player_bar.clock(2.4) == "0:02.40"
    assert player_bar.clock(75.5) == "1:15.50" and player_bar.clock(-3) == "0:00.00"
    assert player_bar.speed_text(1.0) == "1×" and player_bar.speed_text(0.25) == "0.25×"


def test_the_bar_shows_the_title_and_the_total_time(window) -> None:
    assert bar(window).title.text() == "Lesson" and bar(window).total.text() == "0:04.00"
    assert bar(window).elapsed.text() == "0:00.00"


def test_the_seek_bar_follows_the_playhead(window) -> None:
    window.seek(1.5)
    assert bar(window).elapsed.text() == "0:01.50"
    assert bar(window).seek.value() == 1500 and bar(window).seek.maximum() == 4000


def test_moving_the_seek_bar_moves_the_playhead(window) -> None:
    bar(window).seek.sliderMoved.emit(2500)
    assert window.t == pytest.approx(2.5)


def test_clicking_the_seek_bar_jumps_to_that_place(window, qt_app) -> None:
    seek = bar(window).seek
    seek.resize(400, 20)
    QTest.mouseClick(seek, Qt.MouseButton.LeftButton, pos=QPoint(100, 10))
    assert window.t == pytest.approx(1.0, abs=0.15)  # a quarter of 4 s
    assert not seek.isSliderDown()


# -- the transport ------------------------------------------------------------------------------


def test_the_play_button_plays_and_pauses_and_follows_the_state(window) -> None:
    play = bar(window).play_button
    assert "Play" in play.toolTip()
    play.click()
    assert window.play_timer.isActive() and "Pause" in play.toolTip()
    play.click()
    assert not window.play_timer.isActive() and "Play" in play.toolTip()
    window.play()  # from the editor's own button: the bar follows
    assert "Pause" in play.toolTip()
    window.pause()


def test_skip_buttons_move_five_seconds_and_stay_inside_the_scene(window) -> None:
    window.seek(1.0)
    bar(window).forward_button.click()
    assert window.t == pytest.approx(4.0)  # 6.0 is clamped to the end
    bar(window).back_button.click()
    assert window.t == pytest.approx(0.0)  # -1.0 is clamped to the start


def test_start_and_end_buttons(window) -> None:
    bar(window).end_button.click()
    assert window.t == pytest.approx(4.0)
    bar(window).start_button.click()
    assert window.t == 0.0


def test_the_leave_button_leaves(window) -> None:
    bar(window).leave_button.click()
    assert not window.presenter.active


def test_a_double_click_leaves(window, qt_app) -> None:
    QTest.mouseDClick(window.canvas, Qt.MouseButton.LeftButton, pos=window.canvas.rect().center())
    assert not window.presenter.active


# -- repeat -----------------------------------------------------------------------------------


def run_past_the_end(window) -> None:
    window.play()
    window._play_origin = (time.perf_counter() - 10.0, 0.0)  # ten seconds of a four second scene
    window._on_play_tick()


def test_without_repeat_playback_stops_at_the_end(window) -> None:
    run_past_the_end(window)
    assert not window.play_timer.isActive() and window.t == pytest.approx(4.0)


def test_repeat_starts_again_from_the_beginning(window) -> None:
    bar(window).loop_button.click()
    assert window.loop_playback
    run_past_the_end(window)
    assert window.play_timer.isActive() and window.t == 0.0
    window.pause()
    bar(window).loop_button.click()
    assert not window.loop_playback


def test_the_bar_shows_the_editors_repeat_setting(window) -> None:
    window.presenter.finish()
    window.loop_playback = True
    window.present()
    assert bar(window).loop_button.isChecked()


# -- speed ------------------------------------------------------------------------------------


def test_the_speed_menu_sets_the_playback_speed(window) -> None:
    action = bar(window).speed_actions[0.5]
    action.trigger()
    assert window.play_speed == 0.5 and bar(window).speed_button.text() == player_bar.speed_text(0.5)
    window.play()
    window._play_origin = (time.perf_counter() - 2.0, 0.0)  # two seconds of wall clock: one of scene
    window._on_play_tick()
    assert window.t == pytest.approx(1.0, abs=0.15)
    window.pause()


def test_changing_the_speed_while_playing_continues_from_here(window) -> None:
    window.seek(2.0)
    window.play()
    window.set_play_speed(2.0)
    wall, start = window._play_origin
    assert start == 2.0 and time.perf_counter() - wall < 1.0


def test_speed_is_off_for_a_scene_with_sound(window) -> None:
    bar(window).set_speed_available(False)
    assert not bar(window).speed_button.isEnabled() and "sound" in bar(window).speed_button.toolTip()


# -- volume ------------------------------------------------------------------------------------


def test_volume_and_mute_reach_the_player(window) -> None:
    player = window.audio_player = FakePlayer()
    bar(window).volume.setEnabled(True)
    bar(window).mute_button.setEnabled(True)
    bar(window).volume.setValue(40)
    assert player.volume == pytest.approx(0.4) and not player.muted
    bar(window).mute_button.click()
    assert player.muted
    bar(window).mute_button.click()
    assert not player.muted


def test_a_project_without_sound_has_the_volume_off(window) -> None:
    assert not bar(window).volume.isEnabled() and not bar(window).mute_button.isEnabled()
    assert "no sound" in bar(window).volume.toolTip()


def test_the_bar_shows_the_players_volume_when_it_opens(window) -> None:
    window.presenter.finish()
    player = window.audio_player = FakePlayer()
    player.volume, player.muted = 0.3, True
    window.present()
    assert bar(window).volume.value() == 30 and bar(window).mute_button.isChecked()


# -- keys -------------------------------------------------------------------------------------


def test_l_toggles_repeat_and_the_arrow_keys_change_the_volume(window) -> None:
    presenter = window.presenter
    QTest.keyClick(presenter, Qt.Key.Key_L)
    assert window.loop_playback
    QTest.keyClick(presenter, Qt.Key.Key_L)
    assert not window.loop_playback
    player = window.audio_player = FakePlayer()
    bar(window).volume.setEnabled(True)
    bar(window).mute_button.setEnabled(True)
    QTest.keyClick(presenter, Qt.Key.Key_Down)
    assert player.volume == pytest.approx(0.95)
    QTest.keyClick(presenter, Qt.Key.Key_M)
    assert player.muted


def test_the_cursor_goes_with_the_bar_while_playing(window) -> None:
    presenter = window.presenter
    window.play()
    presenter._rest()
    assert presenter.cursor().shape() == Qt.CursorShape.BlankCursor
    presenter.wake()
    assert presenter.cursor().shape() != Qt.CursorShape.BlankCursor
    window.pause()
