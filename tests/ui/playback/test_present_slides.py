"""Present mode (ADR 0087): with slide stops, full screen plays a slide and waits at its stop.

The scene is 6 s at 10 fps (frames 0..59) with stops at 2 s (looping its last 0.5 s) and 4 s, so the slides are
frames [0, 21), [21, 41) and [41, 60). Ticks are driven by hand: the play origin is moved back to stand for the
wall clock having run on, coarser than a frame on purpose.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from manim_studio.core.model.schema import Canvas, Layer, Marker, Project, Spec
from manim_studio.ui.main_window import MainWindow

pytestmark = pytest.mark.ui

STOP_A, STOP_B, LAST = 2.0, 4.0, 5.9


def make_project(**extra) -> Project:
    markers = [
        Marker(id="a", t=STOP_A, slide="stop", loop=0.5),
        Marker(id="note", t=3.0, name="just a note"),
        Marker(id="b", t=STOP_B, slide="stop"),
    ]
    return Project(
        canvas=Canvas(width_px=320, height_px=180, fps=10, duration=6.0),
        layers=[Layer(id="dot", spec=Spec(type="Circle"))],
        markers=markers,
        **extra,
    )


def open_window(qt_app, tmp_path, project: Project) -> MainWindow:
    path = tmp_path / "Talk.json"
    path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.resize(1400, 850)
    win.show()
    win.load(path)
    qt_app.processEvents()
    win.present()
    qt_app.processEvents()
    return win


@pytest.fixture
def window(qt_app, tmp_path):
    win = open_window(qt_app, tmp_path, make_project())
    yield win
    win.presenter.finish()
    win.pause()
    win.document.undo_stack.setClean()
    win.close()


def press(window, key, modifiers=Qt.KeyboardModifier.NoModifier) -> None:
    QTest.keyClick(window.presenter, key, modifiers)


def run_for(window, seconds: float) -> None:
    """The wall clock moves on ``seconds`` since playback (re)started; one tick."""
    wall, start = window._play_origin
    window._play_origin = (time.perf_counter() - seconds, start)
    window._on_play_tick()


def test_slides_mode_is_on_when_the_project_has_stops(window) -> None:
    presenter = window.presenter
    assert presenter.slides_mode
    assert window.t == 0.0 and not window.play_timer.isActive()
    assert presenter.bar.slide.text() == "Slide 1 of 3" and not presenter.bar.slide.isHidden()


def test_without_stops_full_screen_is_the_plain_player(qt_app, tmp_path) -> None:
    win = open_window(qt_app, tmp_path, make_project().model_copy(update={"markers": []}))
    try:
        assert not win.presenter.slides_mode and win.presenter.bar.slide.isHidden()
        press(win, Qt.Key.Key_Right)
        assert win.t == pytest.approx(0.1)  # one frame, as before
    finally:
        win.presenter.finish()
        win.close()


def test_next_plays_the_slide_and_a_coarse_tick_stops_exactly_on_its_stop(window) -> None:
    press(window, Qt.Key.Key_PageDown)
    assert window.play_timer.isActive()
    run_for(window, 1.0)
    assert window.t == pytest.approx(1.0) and window.play_timer.isActive()
    shown = []
    window.playheadMoved.connect(shown.append)
    run_for(window, 3.7)  # far past the stop in one tick
    assert shown[0] == pytest.approx(STOP_A)  # it stopped on the stop's frame first
    assert max(shown) == pytest.approx(STOP_A)  # and never showed one past it
    assert window.presenter.waiting
    assert window.t == pytest.approx(1.6)  # then its loop starts


def test_a_tick_just_past_the_stop_stops_on_it(window) -> None:
    shown = []
    window.playheadMoved.connect(shown.append)
    press(window, Qt.Key.Key_PageDown)
    run_for(window, 2.3)  # three frames past the 2 s stop
    assert max(shown) == pytest.approx(STOP_A) and window.presenter.waiting


def test_a_looping_stop_repeats_its_last_moment_without_sound(window) -> None:
    press(window, Qt.Key.Key_PageDown)
    run_for(window, 5.0)
    assert window.presenter.waiting and window.play_loop == pytest.approx((1.6, STOP_A))
    assert window.play_timer.isActive() and window._audio_signature is None
    run_for(window, 0.2)
    assert window.t == pytest.approx(1.8)  # inside the loop
    run_for(window, 0.9)  # past the stop: back to the loop's start, never past the stop
    assert 1.6 - 1e-9 <= window.t <= STOP_A + 1e-9
    assert window.play_loop is not None


def test_next_while_waiting_plays_the_next_slide_to_its_stop(window) -> None:
    press(window, Qt.Key.Key_PageDown)
    run_for(window, 5.0)
    press(window, Qt.Key.Key_PageDown)
    assert window.play_loop is None and window.play_timer.isActive()
    assert window.t == pytest.approx(2.1)  # the frame after the stop
    assert window.presenter.bar.slide.text() == "Slide 2 of 3"
    run_for(window, 5.0)
    assert window.t == pytest.approx(STOP_B) and not window.play_timer.isActive()  # no loop here: holds still


def test_next_during_a_slide_jumps_to_its_stop(window) -> None:
    press(window, Qt.Key.Key_PageDown)
    run_for(window, 0.5)
    press(window, Qt.Key.Key_Right)
    assert window.presenter.waiting and window.play_loop == pytest.approx((1.6, STOP_A))


def test_space_and_a_click_are_next_too(window, qt_app) -> None:
    press(window, Qt.Key.Key_Space)
    assert window.play_timer.isActive()
    QTest.mouseClick(window.canvas, Qt.MouseButton.LeftButton, pos=window.canvas.rect().center())
    assert window.presenter.waiting and window.play_loop == pytest.approx((1.6, STOP_A))


def test_previous_shows_the_previous_stop_paused(window) -> None:
    press(window, Qt.Key.Key_PageDown)
    run_for(window, 5.0)
    press(window, Qt.Key.Key_PageDown)
    run_for(window, 5.0)  # waiting at 4 s, slide 2
    press(window, Qt.Key.Key_PageUp)
    assert window.t == pytest.approx(STOP_A) and not window.play_timer.isActive()
    assert window.presenter.bar.slide.text() == "Slide 1 of 3"
    press(window, Qt.Key.Key_Left)
    assert window.t == 0.0 and not window.play_timer.isActive()  # before the first stop: the start
    press(window, Qt.Key.Key_PageUp)
    assert window.t == 0.0


def test_the_last_slide_plays_to_the_end_and_next_does_nothing_more(window) -> None:
    press(window, Qt.Key.Key_End)  # the end of the talk: the last slide, done
    assert window.presenter.bar.slide.text() == "Slide 3 of 3"
    assert window.t == pytest.approx(LAST) and window.presenter.waiting
    press(window, Qt.Key.Key_PageDown)
    assert not window.play_timer.isActive() and window.t == pytest.approx(LAST)
    press(window, Qt.Key.Key_PageUp)
    assert window.t == pytest.approx(STOP_B)
    press(window, Qt.Key.Key_PageDown)  # the last slide plays from the frame after 4 s to the end
    run_for(window, 5.0)
    assert not window.play_timer.isActive() and window.t == pytest.approx(LAST)
    press(window, Qt.Key.Key_Home)
    assert window.t == 0.0 and window.presenter.bar.slide.text() == "Slide 1 of 3"


def test_shift_arrows_still_step_frames(window) -> None:
    press(window, Qt.Key.Key_Right, Qt.KeyboardModifier.ShiftModifier)
    assert window.t == pytest.approx(0.1) and not window.play_timer.isActive()
    press(window, Qt.Key.Key_Left, Qt.KeyboardModifier.ShiftModifier)
    assert window.t == pytest.approx(0.0)


def test_leaving_clears_the_play_range(window) -> None:
    press(window, Qt.Key.Key_PageDown)
    run_for(window, 5.0)
    window.presenter.finish()
    assert window.play_loop is None and window.play_until is None
    assert not window.play_timer.isActive()


def test_a_title_slide_opens_waiting_on_frame_zero(qt_app, tmp_path) -> None:
    project = make_project()
    project = project.model_copy(update={"markers": [Marker(id="t", t=0.0, slide="stop"), *project.markers]})
    win = open_window(qt_app, tmp_path, project)
    try:
        assert win.presenter.waiting and win.t == 0.0
        assert win.presenter.bar.slide.text() == "Slide 1 of 4"
        press(win, Qt.Key.Key_PageDown)
        assert win.t == pytest.approx(0.1) and win.play_timer.isActive()
    finally:
        win.presenter.finish()
        win.pause()
        win.close()
