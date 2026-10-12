"""P6b.4 acceptance: on the Audio page, import two sounds and an .srt, edit rows in both tables, see the
timeline, the evaluator and the canvas follow, read the level meter on known tones, refuse an overlap,
and undo everything (ADR 0041, 0034, 0035)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from manim_studio.core import audio, levels
from manim_studio.ui.main_window import MainWindow
from ui.test_acceptance_v1 import menu_action, wait_until
from ui.test_audio_page import cell, steps, type_in

pytestmark = [pytest.mark.ui, pytest.mark.slow]

SRT = """1
00:00:00,500 --> 00:00:01,500
First line of the talk

2
00:00:02,000 --> 00:00:03,000
Second line
"""


def tone(path, seconds: float, amplitude: float, hz: float):
    t = np.arange(round(seconds * audio.RATE)) / audio.RATE
    wave = (amplitude * np.sin(2 * np.pi * hz * t)).astype(np.float32)
    audio.write_wav(np.stack([wave, wave]), path)
    return path


@pytest.fixture
def window(qt_app):
    win = MainWindow()
    win.resize(1400, 900)
    win.show()
    yield win
    win.close()


def test_sounds_and_subtitles_edited_in_tables(window, qt_app, tmp_path) -> None:
    menu_action(window.menuBar(), "File", "New").trigger()
    small = {"width_px": 320, "height_px": 180, "fps": 10, "duration": 6.0}
    window.document.replace(
        window.project.model_copy(update={"canvas": window.project.canvas.model_copy(update=small)})
    )
    menu_action(window.layers.library_menu, "Circle").trigger()
    wait_until(qt_app, lambda: len(window.project.layers) == 1)
    layers = window.project.layers
    window.show_page("audio")
    page = window.pages.pages["audio"]
    sounds, cues = page.sounds_model, page.cues_model
    base_steps = steps(window)

    # two sounds imported at the playhead, with the page's button
    low = tone(tmp_path / "low.wav", 3.0, 0.5, 220.0)
    high = tone(tmp_path / "high.wav", 2.0, 0.25, 880.0)
    window.ask_audio_path = lambda: str(low)
    window.seek(0.0)
    page.import_sound_button.click()
    window.ask_audio_path = lambda: str(high)
    window.seek(2.0)
    page.import_sound_button.click()
    assert [cell(sounds, r, "name") for r in range(2)] == ["low", "high"]
    assert [cell(sounds, r, "start") for r in range(2)] == ["0.000", "2.000"]
    assert len(window.timeline.audio_items()) == 2

    # the meter reads the tones: low alone, then both (checked against the full mix)
    window.seek(1.0)
    assert page.meter.level.peak == pytest.approx((0.5, 0.5), abs=2e-3)
    assert page.meter.level.rms_db == pytest.approx((-9.03, -9.03), abs=0.1)
    window.seek(2.5)
    mixed = audio.mix(window.project)[:, round(2.45 * audio.RATE) : round(2.55 * audio.RATE)]
    expected = np.sqrt((mixed.astype(np.float64) ** 2).mean(axis=1))
    assert page.meter.level.rms == pytest.approx(tuple(expected), abs=1e-4)
    assert page.meter.level.rms[0] == pytest.approx(np.sqrt(0.5**2 / 2 + 0.25**2 / 2), abs=3e-3)

    # subtitles from an .srt, with the page's button
    srt = tmp_path / "talk.srt"
    srt.write_text(SRT, encoding="utf-8")
    window.ask_subtitles_path = lambda: str(srt)
    page.import_srt_button.click()
    assert [[cell(cues, r, k) for k in ("start", "end", "text")] for r in range(2)] == [
        ["0.500", "1.500", "First line of the talk"],
        ["2.000", "3.000", "Second line"],
    ]

    # edits in the sounds table: the timeline, the evaluator and the meter follow
    assert type_in(sounds, 0, "gain", "-6 dB")
    window.seek(1.0)
    assert page.meter.level.peak[0] == pytest.approx(0.25, abs=2e-3)
    assert type_in(sounds, 1, "start", "3.5")
    assert type_in(sounds, 1, "fade_out", "0.5")
    assert window.evaluator.project.audio == window.project.audio
    assert window.project.audio[1].start == 3.5 and window.project.audio[1].fade_out == 0.5
    right = max(item.rect().right() for item in window.timeline.audio_items())
    assert window.timeline.scale.x(5.5) == pytest.approx(right, abs=1.5)  # the bar ends at 3.5 + 2
    window.seek(2.5)
    assert page.meter.level.peak[0] == pytest.approx(0.25, abs=2e-3)  # only the quieter low tone now

    # edits in the subtitles table: the canvas shows the new timing
    window.seek(3.5)
    without = window.canvas.grab().toImage()
    assert type_in(cues, 1, "end", "4")
    window.seek(3.5)
    assert window.canvas.grab().toImage() != without
    assert window.evaluator.project.subtitles == window.project.subtitles
    assert type_in(cues, 0, "text", "First line ↵ of the talk")
    assert window.project.subtitles[0].text == "First line\nof the talk"

    # an overlap is refused with its reason, and nothing changes
    before, count = window.project, steps(window)
    assert not type_in(cues, 0, "end", "2.5")
    assert "overlap" in window.statusBar().currentMessage()
    assert window.project is before and steps(window) == count
    assert not type_in(sounds, 0, "fade_in", "9")
    assert "fades are longer" in window.statusBar().currentMessage()

    # clicking a subtitle row selects it and moves the playhead; Properties shows its style
    window.seek(5.0)
    index = cues.index(1, 0)
    QTest.mouseClick(
        page.cues.viewport(), Qt.MouseButton.LeftButton, pos=page.cues.visualRect(index).center()
    )
    assert window.selection.subtitle_id == "cue-2" and window.t == pytest.approx(2.0)
    assert "subtitle_style.colour" in window.properties.fields

    # delete the first sound, then undo every edit of the page
    window.selection.set_audio("audio-1")
    page.delete_sound_button.click()
    assert [cell(sounds, r, "name") for r in range(sounds.rowCount())] == ["high"]
    while steps(window) and window.document.undo_stack.index() > base_steps:
        window.document.undo_stack.undo()
    assert window.project.audio == [] and window.project.subtitles == []
    assert window.project.layers == layers and sounds.rowCount() == 0 and cues.rowCount() == 0
    assert page.meter.level == levels.SILENCE
    window.document.undo_stack.redo()
    assert sounds.rowCount() == 1
