"""Subtitles in the editor (P5a.2, ADR 0035): the Subtitles row, Properties, menus, .srt in and
out, and the canvas drawing them."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent

from manim_studio.core import edits, subtitles
from manim_studio.core.schema import Canvas, Cue, Layer, Project, Spec
from manim_studio.ui.main_window import MainWindow
from manim_studio.ui.timeline.view import ROW_HEIGHT, RULER_HEIGHT, CueItem
from ui.test_acceptance_v1 import menu_action
from ui.test_timeline_view import move, press, release

pytestmark = pytest.mark.ui

CANVAS = Canvas(width_px=320, height_px=180, fps=10, duration=6.0)
SRT = (
    "1\n00:00:00,500 --> 00:00:02,000\nHello there\n\n2\n00:00:03,000 --> 00:00:04,500\nSecond <b>line</b>\n"
)


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


def row_point(timeline, t: float) -> QPointF:
    row = len(timeline.rows())  # the Subtitles row, right under the layers
    return QPointF(timeline.mapFromScene(QPointF(timeline.scale.x(t), RULER_HEIGHT + row * ROW_HEIGHT + 14)))


def test_add_a_subtitle_at_the_playhead_and_type_it(window) -> None:
    window.seek(1.0)
    menu_action(window.menuBar(), "Edit", "Add Subtitle").trigger()
    (cue,) = window.project.subtitles
    assert (cue.start, cue.end, cue.text) == (1.0, 3.0, "New subtitle")
    assert window.selection.subtitle_id == cue.id and window.selection.layer_id is None
    fields = window.properties.fields
    fields["cue.text"].commit("Every day we ask: how fast is something changing?")
    fields["cue.end"].commit(2.5)
    fields["subtitle_style.font_size"].commit(30.0)
    fields["subtitle_style.band"].commit(False)
    cue = window.project.subtitles[0]
    assert (cue.end, cue.text[:9]) == (2.5, "Every day")
    assert window.project.subtitle_style.font_size == 30 and not window.project.subtitle_style.band
    window.seek(1.8)
    assert len(window.evaluator.overlay(1.8)) == 1
    window.seek(1.5)
    menu_action(window.menuBar(), "Edit", "Add Subtitle").trigger()  # inside a cue: after it
    assert [c.start for c in window.project.subtitles] == [1.0, 2.5]
    window.document.undo_stack.undo()
    assert len(window.project.subtitles) == 1


def test_import_and_export_srt(window, tmp_path) -> None:
    source = tmp_path / "talk.srt"
    source.write_text("\ufeff" + SRT, encoding="utf-8")
    window.ask_subtitles_path = lambda: str(source)
    menu_action(window.menuBar(), "File", "Import Subtitles...").trigger()
    assert [c.text for c in window.project.subtitles] == ["Hello there", "Second line"]
    assert window.statusBar().currentMessage() == "Imported 2 subtitles from talk.srt"
    out = tmp_path / "out.srt"
    window.ask_subtitles_save_path = lambda: str(out)
    menu_action(window.menuBar(), "File", "Export Subtitles...").trigger()
    assert subtitles.read_srt(out.read_text(encoding="utf-8")) == window.project.subtitles


def test_subtitles_are_moved_trimmed_and_deleted_on_their_row(qt_app, tmp_path) -> None:
    cues = [
        Cue(id="cue-1", start=0.5, end=2.0, text="Hello"),
        Cue(id="cue-2", start=3.0, end=4.5, text="Bye"),
    ]
    win = open_window(tmp_path, Project(canvas=CANVAS, subtitles=cues))
    try:
        timeline = win.timeline
        assert sorted(item.text for item in timeline.cue_items()) == ["Bye", "Hello"]
        press(timeline, row_point(timeline, 1.2))
        assert win.selection.subtitle_id == "cue-1" and "cue.text" in win.properties.fields
        move(timeline, row_point(timeline, 3.2))  # would run into the next cue: stops against it
        release(timeline, row_point(timeline, 3.2))
        first = win.project.subtitles[0]
        assert (first.start, first.end) == pytest.approx((1.5, 3.0))
        edge = timeline.mapFromScene(QPointF(timeline.scale.x(3.0), 0)).x() - 2  # its right edge: trim
        y = row_point(timeline, 0).y()
        press(timeline, QPointF(edge, y))
        move(timeline, QPointF(edge - timeline.scale.px_per_second * 0.5, y))
        release(timeline, QPointF(edge - timeline.scale.px_per_second * 0.5, y))
        assert win.project.subtitles[0].end == pytest.approx(2.5)
        timeline.setFocus()
        timeline.keyPressEvent(
            QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Delete, Qt.KeyboardModifier.NoModifier)
        )
        assert [c.id for c in win.project.subtitles] == ["cue-2"] and win.selection.subtitle_id is None
        menu = timeline.context_menu(row_point(timeline, 0.2))
        add = next(a for a in menu.actions() if a.text() == "Add subtitle here")
        add.trigger()
        assert [(c.start, c.end) for c in win.project.subtitles] == [(pytest.approx(0.2), 2.2), (3.0, 4.5)]
        assert isinstance(timeline.cue_items()[0], CueItem)
    finally:
        win.close()


def test_the_canvas_draws_subtitles_but_clicks_go_to_the_objects(qt_app, tmp_path) -> None:
    project = Project(
        canvas=CANVAS,
        layers=[Layer(id="dot", spec=Spec(type="Dot"))],
        subtitles=[Cue(id="cue-1", start=0.0, end=3.0, text="Over everything")],
    )
    win = open_window(tmp_path, project)
    try:
        win.seek(1.0)
        with_subtitle = win.canvas._image.copy()
        win.document.apply(edits.set_subtitle_style(win.project, burn_in=False), "Burn in subtitles")
        win.seek(1.0)
        assert win.canvas._image != with_subtitle  # the subtitle was drawn, and now is not
        assert [layer_id for layer_id, _ in win.evaluator.frame_layers(1.0)] == ["dot"]
    finally:
        win.close()
