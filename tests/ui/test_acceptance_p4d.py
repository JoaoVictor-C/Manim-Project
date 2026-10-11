"""P4d acceptance: a sound imported, placed, trimmed and faded in the editor is heard in the
exported video and in the exported Python scene (ADR 0034).

A square fades in while a sound plays: File > Import Audio... puts the sound at
the playhead; it is moved and trimmed on the timeline and given a gain and a
fade in Properties; playing follows the sound's clock; the export process's
video and the exact Python scene rendered by ``manim render`` carry the
editor's mix.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPointF

from core.test_audio import MANIM_DELAY, assert_plays, decoded_track
from manim_studio.core import audio
from manim_studio.ui.audio_player import FakePlayer
from manim_studio.ui.main_window import MainWindow
from ui.test_acceptance_p4a import manim_render
from ui.test_acceptance_v1 import menu_action, timeline_menu, wait_until
from ui.test_audio_ui import sound_point
from ui.test_timeline_view import move, press, release

pytestmark = [pytest.mark.ui, pytest.mark.slow]  # real processes; renders with the Manim command line


@pytest.fixture
def window(qt_app):
    win = MainWindow()
    win.resize(1280, 820)
    win.show()
    yield win
    win.close()


def test_a_sound_is_placed_trimmed_faded_and_exported(window, qt_app, tmp_path) -> None:
    beeps = tmp_path / "beeps.wav"  # three beeps, at 0.25, 1.25 and 2.25 s of the file
    t = np.arange(3 * audio.RATE) / audio.RATE
    gate = ((t % 1.0) >= 0.25) & ((t % 1.0) < 0.6)
    audio.write_wav(np.stack([0.5 * gate * np.sin(2 * np.pi * 440 * t)] * 2).astype(np.float32), beeps)

    menu_action(window.menuBar(), "File", "New").trigger()
    small = {"width_px": 320, "height_px": 180, "fps": 10, "duration": 4.0}
    window.document.replace(
        window.project.model_copy(update={"canvas": window.project.canvas.model_copy(update=small)})
    )
    menu_action(window.layers.library_menu, "Square").trigger()
    wait_until(qt_app, lambda: len(window.project.layers) == 1)
    menu_action(
        timeline_menu(window, window.project.layers[0].id, 0.0), "Add clip", "Appear / disappear", "FadeIn"
    ).trigger()

    window.seek(0.5)
    window.ask_audio_path = lambda: str(beeps)
    menu_action(window.menuBar(), "File", "Import Audio...").trigger()
    sound = window.project.audio[0].id
    assert window.project.audio[0].start == 0.5

    timeline = window.timeline
    press(timeline, sound_point(timeline, 1.5))  # move it 0.5 s later
    move(timeline, sound_point(timeline, 2.0))
    release(timeline, sound_point(timeline, 2.0))
    edge = timeline.mapFromScene(timeline.audio_items()[0].rect().topLeft()).x() + 2
    y = sound_point(timeline, 0).y()
    press(timeline, QPointF(edge, y))  # trim the first beep away
    move(timeline, QPointF(edge + timeline.scale.px_per_second * 0.7, y))
    release(timeline, QPointF(edge + timeline.scale.px_per_second * 0.7, y))
    window.properties.fields["audio.gain"].commit(-3.0)
    window.properties.fields["audio.fade_in"].commit(0.3)
    clip = window.project.audio[0]
    assert (clip.start, clip.offset, clip.duration, clip.gain, clip.fade_in) == pytest.approx(
        (1.7, 0.7, 2.3, -3.0, 0.3)
    )
    mix = audio.mix(window.project)
    assert np.abs(mix[:, : round(1.7 * audio.RATE)]).max() == 0  # silent before the sound
    assert (
        np.abs(mix[:, round(2.3 * audio.RATE) : round(2.55 * audio.RATE)]).max() > 0.3
    )  # the file's 2nd beep

    # playing follows the sound's clock
    player = FakePlayer()
    window.audio_player = player
    window.seek(1.0)
    window.play()
    player.elapsed = 1.6
    window._on_play_tick()
    window.pause()
    assert player.started[0][1] == 1.0 and window.t == pytest.approx(2.6)

    # the export process muxes the mix
    window.show_export_dialog()
    dialog = window.export_dialog
    video = tmp_path / "beeps.mp4"
    dialog.path.setText(str(video))
    dialog.start()
    wait_until(qt_app, lambda: not dialog.running, timeout=120)
    assert dialog.status.text().startswith("Exported to"), dialog.status.text()
    assert_plays(decoded_track(video), mix)  # to the sample

    # and the exact Python scene, rendered by manim, adds it
    scene = tmp_path / "beeps.py"
    window.ask_python_path = lambda start: str(scene)
    menu_action(window.menuBar(), "File", "Export Python...").trigger()
    message = window.statusBar().currentMessage()
    assert "a trimmed sound" in message and "a faded sound" in message, message
    manim_render(scene, "Beeps")
    assert_plays(decoded_track(next((tmp_path / "media").rglob("Beeps.mp4"))), mix, MANIM_DELAY)
    assert sound in {c.id for c in window.project.audio}
