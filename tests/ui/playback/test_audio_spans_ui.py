"""The editor reads the mix per span (B70): playback pulls spans, long waveforms load in the
background."""

from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

pytest.importorskip("PySide6")

from manim_studio.core.model.schema import AudioClip, Canvas, Project
from manim_studio.core.sound import audio
from manim_studio.ui.playback import audio_player
from manim_studio.ui.playback.audio_player import FakePlayer, MixDevice
from manim_studio.ui.timeline import view as timeline_view
from ui.playback.test_audio_ui import open_window

pytestmark = pytest.mark.ui

CANVAS = Canvas(width_px=320, height_px=180, fps=10, duration=4.0)


@pytest.fixture(autouse=True)
def _fresh():
    audio.forget()
    yield
    audio.forget()


@pytest.fixture
def sound(tmp_path):
    path = tmp_path / "beat.wav"
    t = np.arange(round(2.5 * audio.RATE)) / audio.RATE
    audio.write_wav(np.stack([0.4 * np.sin(2 * np.pi * 220 * t)] * 2).astype(np.float32), path)
    return path


def read_all(device: MixDevice, sizes: list[int]) -> bytes:
    out, i = b"", 0
    while not device.atEnd():
        out += bytes(device.read(sizes[i % len(sizes)]))
        i += 1
    return out


def test_the_device_gives_the_whole_mixs_bytes_from_the_playhead(qt_app, sound) -> None:
    clips = [
        AudioClip(id="a", path=str(sound), start=0.5, duration=2.5, gain=-3.0, fade_in=0.4),
        AudioClip(id="b", path=str(sound), start=1.2, offset=0.3, duration=1.0, gain=9.0),
    ]
    project = Project(canvas=CANVAS, audio=clips)
    whole = audio.mix(project)
    for t in (0.0, 1.337, 3.99, 4.0):
        first = round(t * audio.RATE)
        device = MixDevice(audio.source(project), first)
        assert read_all(device, [4096, 777, 50_000, 3]) == audio.to_int16(whole[:, first:]), t
    array = MixDevice(audio_player._ArraySource(whole), 1000)  # a whole array plays the same way
    assert read_all(array, [10_000]) == audio.to_int16(whole[:, 1000:])


def test_playback_hands_the_player_a_source_not_a_whole_mix(qt_app, tmp_path, sound) -> None:
    clip = AudioClip(id="audio-1", path=str(sound), start=0.5, duration=2.5)
    win = open_window(tmp_path, Project(canvas=CANVAS, audio=[clip]))
    try:
        player = FakePlayer()
        win.audio_player = player
        win.seek(1.0)
        win.play()
        ((source, t0),) = player.started
        assert isinstance(source, audio.MixSource) and t0 == 1.0
        assert np.array_equal(source.span(48_000, 1000), audio.mix(win.project)[:, 48_000:49_000])
        win.pause()
    finally:
        win.close()


def test_a_long_sounds_waveform_is_flat_until_scanned_in_the_background(
    qt_app, tmp_path, sound, monkeypatch
) -> None:
    monkeypatch.setattr(timeline_view, "SYNC_PEAKS_SECONDS", 1.0)  # 2.5 s counts as long here
    clip = AudioClip(id="audio-1", path=str(sound), duration=2.5)
    win = open_window(tmp_path, Project(canvas=CANVAS, audio=[clip]))
    try:
        deadline = time.perf_counter() + 10.0
        while not len(win.timeline.audio_items()[0].peaks) and time.perf_counter() < deadline:
            qt_app.processEvents()
            time.sleep(0.01)
        (item,) = win.timeline.audio_items()
        assert len(item.peaks) == 250 and item.peaks.max() == pytest.approx(0.4, abs=0.01)
    finally:
        win.close()


def test_the_first_sync_does_not_wait_for_a_long_sound(qt_app, tmp_path, sound, monkeypatch) -> None:
    monkeypatch.setattr(timeline_view, "SYNC_PEAKS_SECONDS", 1.0)
    started = []
    monkeypatch.setattr(timeline_view._PeaksLoader, "request", lambda self, path: started.append(path))
    clip = AudioClip(id="audio-1", path=str(sound), duration=2.5)
    win = open_window(tmp_path, Project(canvas=CANVAS, audio=[clip]))
    try:
        (item,) = win.timeline.audio_items()
        assert not len(item.peaks) and started and started[0] == str(sound)  # a flat row meanwhile
        assert audio.peaks_ready(str(sound)) is None  # nothing was decoded on the GUI thread
    finally:
        win.close()
