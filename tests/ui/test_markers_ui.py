"""Markers and snapping in the editor (P5c.2, ADR 0037): Add Marker (M) at the playhead, flags on
the ruler that are picked, dragged with snapping, renamed and deleted, [ and ] to jump between
them, Properties, the guide line of a snapped drag, and sounds added at a clip or a marker."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent

from manim_studio.core import audio, edits
from manim_studio.core.schema import AudioClip, Canvas, Clip, Layer, Marker, Project, Spec
from manim_studio.ui.main_window import MainWindow
from manim_studio.ui.timeline.view import RULER_HEIGHT
from ui.test_acceptance_v1 import menu_action
from ui.test_timeline_view import move, point, press, release

pytestmark = pytest.mark.ui

CANVAS = Canvas(width_px=320, height_px=180, fps=10, duration=6.0)


def sound_file(tmp_path, name: str, seconds: float) -> str:
    path = tmp_path / name
    t = np.arange(round(seconds * audio.RATE)) / audio.RATE
    audio.write_wav(np.stack([0.3 * np.sin(2 * np.pi * 330 * t)] * 2).astype(np.float32), path)
    return str(path)


@pytest.fixture
def window(qt_app, tmp_path):
    circle = Layer(
        id="c",
        name="Circle",
        spec=Spec(type="Circle"),
        clips=[
            Clip(id="f", kind="FadeIn", start=1.0, duration=1.0),
            Clip(id="i", kind="Indicate", start=3.0, duration=1.0),
        ],
    )
    project = Project(canvas=CANVAS, layers=[circle], markers=[Marker(id="m1", t=2.5, name="Formula")])
    path = tmp_path / "scene.json"
    path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.resize(1200, 800)
    win.show()
    win.load(path)
    yield win
    win.close()


def ruler_point(timeline, t: float) -> QPointF:
    return QPointF(timeline.mapFromScene(QPointF(timeline.scale.x(t), 0)).x(), RULER_HEIGHT / 2)


def key(widget, code) -> None:
    widget.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, code, Qt.KeyboardModifier.NoModifier))


def test_add_marker_at_the_playhead_and_name_it(window) -> None:
    window.seek(1.23)
    menu_action(window.menuBar(), "Edit", "Add Marker").trigger()
    marker = window.project.markers[0]
    assert marker.t == pytest.approx(1.2) and window.selection.marker_id == marker.id
    assert window.selection.layer_id is None and window.properties.marker_id == marker.id
    window.properties.fields["marker.name"].commit("  Intro  ")
    window.properties.fields["marker.colour"].commit("#22d3ee")
    marker = window.project.markers[0]
    assert (marker.name, marker.colour) == ("Intro", "#22d3ee")
    window.seek(1.2)
    menu_action(window.menuBar(), "Edit", "Add Marker").trigger()  # on a marker: selects it
    assert len(window.project.markers) == 2 and window.selection.marker_id == marker.id
    window.properties.fields["marker.t"].commit(2.5)  # onto another marker: refused, shown again
    assert window.project.markers[0].t == pytest.approx(1.2)
    assert "already at" in window.statusBar().currentMessage()


def test_the_m_shortcut_is_bound(window) -> None:
    action = menu_action(window.menuBar(), "Edit", "Add Marker")
    assert action.shortcut().toString() == "M"
    assert menu_action(window.menuBar(), "Edit", "Previous Marker").shortcut().toString() == "["
    assert menu_action(window.menuBar(), "Edit", "Next Marker").shortcut().toString() == "]"


def test_jump_between_markers(window) -> None:
    window.document.apply(edits.add_marker(window.project, 4.5), "Add marker")
    window.seek(0.0)
    menu_action(window.menuBar(), "Edit", "Next Marker").trigger()
    assert window.t == pytest.approx(2.5)
    menu_action(window.menuBar(), "Edit", "Next Marker").trigger()
    assert window.t == pytest.approx(4.5)
    menu_action(window.menuBar(), "Edit", "Next Marker").trigger()  # none further: stays
    assert window.t == pytest.approx(4.5)
    menu_action(window.menuBar(), "Edit", "Previous Marker").trigger()
    assert window.t == pytest.approx(2.5)


def test_a_flag_is_picked_and_dragged_with_snapping_in_one_undo_step(window, qt_app) -> None:
    timeline = window.timeline
    steps = window.document.undo_stack.count()
    press(timeline, ruler_point(timeline, 2.5))
    assert window.selection.marker_id == "m1" and window.t == 0.0  # picked, not scrubbed
    move(timeline, ruler_point(timeline, 3.04))  # near the Indicate clip's start
    timeline.apply_pending()
    assert window.project.markers[0].t == pytest.approx(3.0) and timeline.guide == pytest.approx(3.0)
    move(timeline, ruler_point(timeline, 3.04), modifiers=Qt.KeyboardModifier.AltModifier)
    timeline.apply_pending()
    assert window.project.markers[0].t == pytest.approx(3.0) and timeline.guide is None  # frame grid only
    move(timeline, ruler_point(timeline, 4.42))
    timeline.apply_pending()
    release(timeline, ruler_point(timeline, 4.42))
    assert window.project.markers[0].t == pytest.approx(4.4) and timeline.guide is None
    assert window.document.undo_stack.count() == steps + 1
    assert window.document.undo_stack.undoText() == "Move marker"


def test_escape_cancels_a_marker_drag(window) -> None:
    timeline = window.timeline
    press(timeline, ruler_point(timeline, 2.5))
    move(timeline, ruler_point(timeline, 5.0))
    timeline.apply_pending()
    key(timeline, Qt.Key.Key_Escape)
    assert window.project.markers[0].t == 2.5 and timeline.guide is None


def test_clicking_the_ruler_away_from_markers_scrubs(window) -> None:
    timeline = window.timeline
    press(timeline, ruler_point(timeline, 4.0))
    release(timeline, ruler_point(timeline, 4.0))
    assert window.t == pytest.approx(4.0) and window.selection.marker_id is None


def test_ruler_menu_adds_renames_and_deletes(window) -> None:
    timeline = window.timeline
    menu = timeline.context_menu(ruler_point(timeline, 5.0))
    menu_action(menu, "Add marker here").trigger()
    assert [m.t for m in window.project.markers] == [2.5, 5.0]
    timeline.ask_marker_name = lambda current: "Ending"
    menu_action(timeline.context_menu(ruler_point(timeline, 5.0)), "Rename marker...").trigger()
    assert window.project.markers[1].name == "Ending"
    timeline.ask_marker_name = lambda current: None  # cancelled
    menu_action(timeline.context_menu(ruler_point(timeline, 5.0)), "Rename marker...").trigger()
    assert window.project.markers[1].name == "Ending"
    menu_action(timeline.context_menu(ruler_point(timeline, 5.0)), "Delete marker").trigger()
    assert [m.id for m in window.project.markers] == ["m1"]


def test_delete_removes_the_selected_marker(window) -> None:
    timeline = window.timeline
    press(timeline, ruler_point(timeline, 2.5))
    release(timeline, ruler_point(timeline, 2.5))
    key(timeline, Qt.Key.Key_Delete)
    assert window.project.markers == [] and window.selection.marker_id is None


def test_selecting_a_clip_deselects_the_marker(window) -> None:
    timeline = window.timeline
    press(timeline, ruler_point(timeline, 2.5))
    release(timeline, ruler_point(timeline, 2.5))
    press(timeline, point(timeline, 3.5, "c"))
    release(timeline, point(timeline, 3.5, "c"))
    assert window.selection.clip_id == "i" and window.selection.marker_id is None
    assert timeline.selected_marker is None


def test_a_clip_drag_snaps_to_a_marker_and_shows_the_guide(window) -> None:
    timeline = window.timeline
    press(timeline, point(timeline, 3.5, "c"))  # the Indicate clip, 3-4 s
    move(timeline, point(timeline, 3.04, "c"))  # its start near the marker at 2.5
    timeline.apply_pending()
    clip = window.project.layer("c").clips[1]
    assert clip.start == pytest.approx(2.5) and timeline.guide == pytest.approx(2.5)
    release(timeline, point(timeline, 3.04, "c"))
    assert timeline.guide is None


def test_sounds_at_a_clip_or_a_marker_from_the_projects_sounds(window, tmp_path) -> None:
    pop = sound_file(tmp_path, "pop.wav", 0.3)
    whoosh = sound_file(tmp_path, "whoosh.wav", 0.6)
    window.document.apply(edits.add_audio(window.project, pop, 0.0, 0.3), "Add")
    timeline = window.timeline
    menu = timeline.context_menu(point(timeline, 3.5, "c"))
    files = menu_action(menu, "Add sound at end").menu()
    assert [a.text() for a in files.actions() if not a.isSeparator()] == ["pop.wav", "Other file..."]
    menu_action(menu, "Add sound at end", "pop.wav").trigger()
    added = window.project.audio[-1]
    assert (added.path, added.start, added.duration) == (pop, 4.0, pytest.approx(0.3, abs=1e-3))
    assert window.selection.audio_id == added.id

    timeline.ask_sound_path = lambda: whoosh
    menu_action(
        timeline.context_menu(point(timeline, 3.5, "c")), "Add sound at start", "Other file..."
    ).trigger()
    assert window.project.audio[-1].path == whoosh and window.project.audio[-1].start == 3.0
    menu = timeline.context_menu(ruler_point(timeline, 2.5))
    assert [
        a.text() for a in menu_action(menu, "Add sound here").menu().actions() if not a.isSeparator()
    ] == [
        "whoosh.wav",
        "pop.wav",
        "Other file...",
    ]  # the last added first
    menu_action(menu, "Add sound here", "pop.wav").trigger()
    assert window.project.audio[-1].start == 2.5


def test_a_sound_that_cannot_be_read_is_refused(window, tmp_path) -> None:
    broken = tmp_path / "broken.wav"
    broken.write_bytes(b"not a sound")
    timeline = window.timeline
    timeline.ask_sound_path = lambda: str(broken)
    menu_action(
        timeline.context_menu(point(timeline, 3.5, "c")), "Add sound at start", "Other file..."
    ).trigger()
    assert window.project.audio == []
    assert "Cannot read broken.wav" in window.statusBar().currentMessage()
    timeline.ask_sound_path = lambda: ""  # cancelled
    menu_action(
        timeline.context_menu(point(timeline, 3.5, "c")), "Add sound at start", "Other file..."
    ).trigger()
    assert window.project.audio == []


def test_unreadable_project_sounds_are_not_offered(window, tmp_path) -> None:
    missing = AudioClip(id="s", path=str(tmp_path / "gone.wav"), start=0.0, duration=1.0)
    window.document.replace(window.project.model_copy(update={"audio": [missing]}))
    assert window.timeline.sound_files() == []


def test_marker_edits_keep_rendered_frames(window) -> None:
    from manim_studio.core.frame_cache import changed_spans

    before = window.project
    menu_action(window.timeline.context_menu(ruler_point(window.timeline, 5.0)), "Add marker here").trigger()
    assert changed_spans(before, window.project) == []


def test_a_marker_dragged_onto_another_stays_where_it_last_was_free(window) -> None:
    window.document.apply(edits.add_marker(window.project, 4.5), "Add marker")
    timeline = window.timeline
    press(timeline, ruler_point(timeline, 2.5))
    move(timeline, ruler_point(timeline, 3.62))  # free: follows
    timeline.apply_pending()
    move(timeline, ruler_point(timeline, 4.51))  # the other marker's frame: stays at 3.6
    timeline.apply_pending()
    release(timeline, ruler_point(timeline, 4.51))
    assert [m.t for m in window.project.markers] == [pytest.approx(3.6), 4.5]
