"""P5c acceptance: markers placed with M and the ruler, clips, sounds and markers dragged onto each
other with snapping, sounds added at a clip and at a marker from the project's sounds, frames
rendered ahead kept through marker edits, and markers saved with the project (ADR 0037).
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

pytest.importorskip("PySide6")

from manim_studio.core import audio
from manim_studio.core.schema import Project
from manim_studio.ui.main_window import MainWindow
from ui.test_acceptance_v1 import menu_action, timeline_menu, wait_until
from ui.test_markers_ui import ruler_point
from ui.test_timeline_view import move, point, press, release

pytestmark = [pytest.mark.ui, pytest.mark.slow]  # the real preview process renders ahead


@pytest.fixture
def window(qt_app, monkeypatch):
    monkeypatch.setenv("MANIM_STUDIO_PREVIEW", "1")
    win = MainWindow()
    win.resize(1280, 820)
    win.show()
    yield win
    win.close()


def drag(timeline, start, end) -> None:
    press(timeline, start)
    move(timeline, end)
    timeline.apply_pending()
    release(timeline, end)


def test_markers_snapping_and_sounds_in_the_editor(window, qt_app, tmp_path) -> None:
    menu_action(window.menuBar(), "File", "New").trigger()
    small = {"width_px": 320, "height_px": 180, "fps": 10, "duration": 6.0}
    window.document.replace(
        window.project.model_copy(update={"canvas": window.project.canvas.model_copy(update=small)})
    )
    menu_action(window.layers.library_menu, "Circle").trigger()
    wait_until(qt_app, lambda: len(window.project.layers) == 1)
    circle = window.project.layers[0].id
    timeline = window.timeline
    menu_action(timeline_menu(window, circle, 0.5), "Add clip", "Appear / disappear", "FadeIn").trigger()
    menu_action(timeline_menu(window, circle, 3.6), "Add clip", "Emphasis", "Indicate").trigger()

    # markers: M at the playhead, named in Properties; another from the ruler's menu
    window.seek(2.0)
    menu_action(window.menuBar(), "Edit", "Add Marker").trigger()
    window.properties.fields["marker.name"].commit("Formula")
    menu_action(timeline.context_menu(ruler_point(timeline, 5.0)), "Add marker here").trigger()
    assert [(m.t, m.name) for m in window.project.markers] == [(2.0, "Formula"), (5.0, "")]

    # a clip dragged near a marker snaps onto it; a marker dragged near a clip end snaps onto it
    drag(timeline, point(timeline, 4.0, circle), point(timeline, 2.45, circle))  # Indicate 3.6-4.6 -> 2.0
    indicate = window.project.layer(circle).clips[1]
    assert indicate.start == pytest.approx(2.0)
    drag(timeline, ruler_point(timeline, 5.0), ruler_point(timeline, 3.04))  # onto Indicate's end (3.0)
    assert window.project.markers[1].t == pytest.approx(3.0)

    # sounds: at the FadeIn's end from another file, then at a marker from the project's sounds
    path = tmp_path / "pop.wav"
    t = np.arange(round(0.4 * audio.RATE)) / audio.RATE
    audio.write_wav(np.stack([0.3 * np.sin(2 * np.pi * 440 * t)] * 2).astype(np.float32), path)
    timeline.ask_sound_path = lambda: str(path)
    menu_action(
        timeline.context_menu(point(timeline, 0.7, circle)), "Add sound at end", "Other file..."
    ).trigger()
    fade = window.project.layer(circle).clips[0]
    assert window.project.audio[0].start == pytest.approx(fade.end)
    menu = timeline.context_menu(ruler_point(timeline, 2.0))
    menu_action(menu, "Add sound here", "pop.wav").trigger()
    assert [round(c.start, 6) for c in window.project.audio] == [round(fade.end, 6), 2.0]

    # frames rendered ahead survive marker edits
    ahead = window.render_ahead
    wait_until(qt_app, lambda: ahead is not None and len(ahead.store) == ahead.store.total, timeout=120)
    window.seek(3.5)
    menu_action(window.menuBar(), "Edit", "Add Marker").trigger()
    window.properties.fields["marker.name"].commit("Tangent")
    assert len(ahead.store) == ahead.store.total  # nothing to render again
    window.seek(2.5)
    assert window.canvas.from_cache

    # [ and ] walk the markers; the project saves and reopens with them
    window.seek(0.0)
    menu_action(window.menuBar(), "Edit", "Next Marker").trigger()
    assert window.t == pytest.approx(2.0)
    menu_action(window.menuBar(), "Edit", "Next Marker").trigger()
    assert window.t == pytest.approx(3.0)
    saved = tmp_path / "markers.json"
    window.path = saved
    menu_action(window.menuBar(), "File", "Save").trigger()
    again = Project.model_validate_json(saved.read_text(encoding="utf-8"))
    assert [(m.t, m.name) for m in again.markers] == [(2.0, "Formula"), (3.0, ""), (3.5, "Tangent")]
