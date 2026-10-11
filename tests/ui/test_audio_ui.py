"""The audio track in the editor (P4d.2, ADR 0034): importing, the timeline rows, Properties,
missing files, and playback following the sound's clock."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent

from manim_studio.core import audio, edits
from manim_studio.core.schema import AudioClip, Canvas, Layer, Project, Spec
from manim_studio.ui.audio_player import AudioPlayer, FakePlayer
from manim_studio.ui.main_window import MainWindow
from manim_studio.ui.timeline.view import ROW_HEIGHT, RULER_HEIGHT, AudioItem
from ui.test_acceptance_v1 import menu_action
from ui.test_timeline_view import move, press, release

pytestmark = pytest.mark.ui

CANVAS = Canvas(width_px=320, height_px=180, fps=10, duration=4.0)


@pytest.fixture
def sound(tmp_path):
    path = tmp_path / "beat.wav"
    t = np.arange(round(2.5 * audio.RATE)) / audio.RATE
    audio.write_wav(np.stack([0.4 * np.sin(2 * np.pi * 220 * t)] * 2).astype(np.float32), path)
    return path


def open_window(tmp_path, project: Project) -> MainWindow:
    path = tmp_path / "scene.json"
    path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.resize(1200, 800)
    win.show()
    win.load(path)
    return win


@pytest.fixture
def window(qt_app, tmp_path):
    win = open_window(tmp_path, Project(canvas=CANVAS, layers=[Layer(id="dot", spec=Spec(type="Dot"))]))
    yield win
    win.close()


def test_tests_play_no_sound() -> None:
    assert not AudioPlayer.available()  # conftest: MANIM_STUDIO_AUDIO=0


def test_import_audio_adds_the_whole_file_at_the_playhead(window, sound) -> None:
    window.seek(1.0)
    window.ask_audio_path = lambda: str(sound)
    menu_action(window.menuBar(), "File", "Import Audio...").trigger()
    (clip,) = window.project.audio
    assert (clip.name, clip.start, clip.offset) == ("beat", 1.0, 0.0)
    assert clip.duration == pytest.approx(2.5, abs=1e-3)
    assert window.selection.audio_id == clip.id and window.selection.layer_id is None
    assert window.properties.title.text().startswith("<b>beat</b> - sound (beat.wav)")
    window.properties.fields["audio.gain"].commit(-6.0)
    window.properties.fields["audio.fade_out"].commit(0.5)
    assert (window.project.audio[0].gain, window.project.audio[0].fade_out) == (-6.0, 0.5)
    window.document.undo_stack.undo()
    assert window.project.audio[0].fade_out == 0.0


def test_a_file_that_is_not_a_sound_is_refused(window, tmp_path) -> None:
    junk = tmp_path / "notes.mp3"
    junk.write_text("hello", encoding="utf-8")
    window.ask_audio_path = lambda: str(junk)
    menu_action(window.menuBar(), "File", "Import Audio...").trigger()
    assert (
        window.project.audio == []
        and window.statusBar().currentMessage() == "Cannot read notes.mp3 as a sound"
    )


def test_a_missing_sound_is_reported_on_open(qt_app, tmp_path) -> None:
    gone = AudioClip(id="audio-1", name="Music", path=str(tmp_path / "gone.wav"), duration=2.0)
    win = open_window(tmp_path, Project(canvas=CANVAS, audio=[gone]))
    try:
        assert win.statusBar().currentMessage() == "Missing media: Music (gone.wav - file not found)"
    finally:
        win.close()


def sound_point(timeline, t: float) -> QPointF:
    row = len(timeline.rows()) + 1  # under the layers and the Subtitles row
    return QPointF(timeline.mapFromScene(QPointF(timeline.scale.x(t), RULER_HEIGHT + row * ROW_HEIGHT + 14)))


def test_sounds_are_moved_trimmed_and_deleted_on_the_timeline(qt_app, tmp_path, sound) -> None:
    clip = AudioClip(id="audio-1", name="beat", path=str(sound), start=1.0, duration=2.5)
    win = open_window(
        tmp_path, Project(canvas=CANVAS, layers=[Layer(id="dot", spec=Spec(type="Dot"))], audio=[clip])
    )
    try:
        timeline = win.timeline
        (item,) = timeline.audio_items()
        assert (
            isinstance(item, AudioItem)
            and len(item.peaks) == 250
            and item.peaks.max() == pytest.approx(0.4, abs=0.01)
        )
        press(timeline, sound_point(timeline, 2.0))  # the body: move
        assert win.selection.audio_id == "audio-1" and "audio.start" in win.properties.fields
        move(timeline, sound_point(timeline, 2.5))
        release(timeline, sound_point(timeline, 2.5))
        assert win.project.audio[0].start == pytest.approx(1.5)
        assert win.project.layers == [Layer(id="dot", spec=Spec(type="Dot"))]  # no layer touched
        edge = (
            timeline.mapFromScene(timeline.audio_items()[0].rect().topLeft()).x() + 2
        )  # the left edge: trim
        press(timeline, QPointF(edge, sound_point(timeline, 0).y()))
        move(timeline, QPointF(edge + timeline.scale.px_per_second * 0.5, sound_point(timeline, 0).y()))
        release(timeline, QPointF(edge + timeline.scale.px_per_second * 0.5, sound_point(timeline, 0).y()))
        trimmed = win.project.audio[0]
        assert (trimmed.start, trimmed.offset, trimmed.duration) == pytest.approx((2.0, 0.5, 2.0))
        timeline.setFocus()
        timeline.keyPressEvent(
            QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Delete, Qt.KeyboardModifier.NoModifier)
        )
        assert win.project.audio == [] and win.selection.audio_id is None
        win.document.undo_stack.undo()
        assert win.project.audio == [trimmed]
    finally:
        win.close()


def test_playback_follows_the_sounds_clock(qt_app, tmp_path, sound) -> None:
    clip = AudioClip(id="audio-1", path=str(sound), start=0.5, duration=2.5)
    win = open_window(tmp_path, Project(canvas=CANVAS, audio=[clip]))
    try:
        player = FakePlayer()
        win.audio_player = player
        win.seek(1.0)
        win.play()
        ((samples, t0),) = player.started
        assert t0 == 1.0 and np.array_equal(samples, audio.mix(win.project))
        win._on_play_tick()
        assert win.t == pytest.approx(1.0)  # the device has not started: the first frame holds
        player.elapsed = 0.73
        win._on_play_tick()
        assert win.t == pytest.approx(1.7)  # on the sound's clock, on a frame
        win.properties.show_audio("audio-1")
        win.properties.fields["audio.gain"].commit(3.0)  # an edit while playing: heard at once
        assert len(player.started) == 2 and player.started[1][1] == pytest.approx(1.7)
        win.pause()
        assert player.stopped >= 2
        win.document.apply(edits.remove_audio(win.project, "audio-1"), "Delete sound")
        win.play()
        assert len(player.started) == 2  # nothing to hear: the wall clock again
        win.pause()
    finally:
        win.close()


def test_the_real_player_clock_advances_from_the_start(qt_app) -> None:
    """With a sound device: silence played from 1 s, the clock starts there and advances (B47)."""
    from PySide6.QtMultimedia import QMediaDevices

    if QMediaDevices.defaultAudioOutput().isNull():
        pytest.skip("no sound device")
    import time

    player = AudioPlayer()
    player.play(np.zeros((2, 3 * audio.RATE), np.float32), 1.0)
    try:
        assert 1.0 <= player.position() < 1.15  # at most the device's first fill ahead
        deadline = time.perf_counter() + 3.0
        while player.position() < 1.2 and time.perf_counter() < deadline:
            qt_app.processEvents()
            time.sleep(0.01)
        assert 1.2 <= player.position() < 2.5
    finally:
        player.stop()
    assert player.position() == pytest.approx(1.0)  # stopped: back to its start


def test_the_waveform_shows_gain_and_fades(qt_app, tmp_path, sound) -> None:
    clip = AudioClip(id="audio-1", path=str(sound), duration=2.5, gain=-6.0, fade_in=1.0)
    win = open_window(tmp_path, Project(canvas=CANVAS, audio=[clip]))
    try:
        (item,) = win.timeline.audio_items()
        assert item.peaks[0] < 0.01  # faded in from silence
        assert item.peaks[200] == pytest.approx(0.4 * 10 ** (-6 / 20), abs=0.01)  # -6 dB after the fade
    finally:
        win.close()
