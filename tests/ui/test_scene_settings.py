"""Scene settings and the scene's length in the window (P7.1)."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from manim_studio.core import edits, scene_length
from manim_studio.ui.document import Document
from manim_studio.ui.main_window import MainWindow
from manim_studio.core.schema import Clip, Layer, Project
from support import CANVAS, TEXT

pytestmark = pytest.mark.ui

DEMO = Path(__file__).resolve().parents[2] / "examples" / "euler.json"


@pytest.fixture
def window(qt_app, tmp_path):
    project_file = tmp_path / "euler.json"
    project_file.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
    win = MainWindow()
    win.resize(1200, 760)
    win.show()
    win.load(project_file)
    qt_app.processEvents()
    yield win
    win.pause()
    win.close()
    qt_app.processEvents()


def a_clip(window: MainWindow) -> tuple[str, str]:
    layer = next(layer for layer in window.project.layers if layer.clips)
    return layer.id, layer.clips[0].id


def slider_end(window: MainWindow) -> float:
    return window.slider.maximum() / window.SLIDER_STEPS_PER_SECOND


def small_project() -> Project:
    clips = [
        Clip(id="w", kind="Write", start=0.0, duration=0.4),
        Clip(id="i", kind="Indicate", start=0.5, duration=0.3),
    ]
    return Project(canvas=CANVAS, layers=[Layer(id="a", spec=TEXT, clips=clips)])


# -- the document --------------------------------------------------------------------------------


def test_an_edit_past_the_end_grows_the_scene_in_the_same_undo_step(qt_app) -> None:
    doc = Document(small_project())
    before = doc.project
    end = before.canvas.duration
    doc.apply(edits.move_clip(before, "a", "i", end + 1.0), "Move clip")
    assert doc.project.canvas.duration == pytest.approx(end + 1.3)  # the clip lasts 0.3 s
    assert doc.undo_stack.count() == 1
    doc.undo_stack.undo()
    assert doc.project is before


def test_a_drag_past_the_end_grows_the_scene_once_it_is_dropped(qt_app) -> None:
    doc = Document(small_project())
    before = doc.project
    doc.begin_preview()
    doc.preview(edits.move_clip(before, "a", "i", before.canvas.duration + 2.0))
    assert doc.project.canvas.duration == before.canvas.duration  # not while dragging
    doc.commit_preview("Move clip")
    assert doc.project.canvas.duration > before.canvas.duration + 2.0
    assert doc.undo_stack.count() == 1
    doc.undo_stack.undo()
    assert doc.project is before


# -- the window ----------------------------------------------------------------------------------


def test_with_nothing_selected_properties_shows_the_scene(window) -> None:
    window.selection.clear()
    fields = window.properties.fields
    assert {"canvas.duration", "canvas.width_px", "canvas.fps", "canvas.background"} <= fields.keys()
    assert fields["canvas.duration"].widget.value() == pytest.approx(window.project.canvas.duration)
    assert window.properties.fit_button is not None


def test_typing_a_length_is_one_undo_step_and_moves_the_slider(window) -> None:
    window.selection.clear()
    evaluator = window.evaluator
    length = window.project.canvas.duration + 5.0
    window.properties.fields["canvas.duration"].commit(length)
    assert window.project.canvas.duration == pytest.approx(length)
    assert slider_end(window) == pytest.approx(length)
    assert window.evaluator is evaluator  # the length draws nothing: the frames stay
    assert window.document.undo_stack.count() == 1
    window.document.undo_stack.undo()
    assert slider_end(window) == pytest.approx(length - 5.0)
    assert window.properties.fields["canvas.duration"].widget.value() == pytest.approx(length - 5.0)


def test_a_length_shorter_than_the_content_stops_the_growth(window) -> None:
    window.selection.clear()
    window.seek(window.project.canvas.duration)
    short = scene_length.content_end(window.project) / 2
    window.properties.fields["canvas.duration"].commit(short)
    assert window.project.canvas.duration == pytest.approx(short)
    assert not window.project.canvas.grow_with_content
    assert "no longer grows" in window.statusBar().currentMessage()
    assert window.t <= short + 1e-9  # the playhead stays inside the scene
    assert window.document.undo_stack.count() == 1


def test_moving_a_clip_past_the_end_grows_the_window_scene(window) -> None:
    layer_id, clip_id = a_clip(window)
    end = window.project.canvas.duration
    window.document.apply(edits.move_clip(window.project, layer_id, clip_id, end + 3.0), "Move clip")
    assert window.project.canvas.duration > end + 3.0
    assert slider_end(window) == pytest.approx(window.project.canvas.duration)
    window.seek(end + 3.0)  # the grown part can be shown
    assert window.t == pytest.approx(end + 3.0)


def test_fit_length_to_content_trims_the_scene(window) -> None:
    window.selection.clear()
    window.properties.fields["canvas.duration"].commit(window.project.canvas.duration + 30.0)
    window.properties.fit_button.click()
    expected = scene_length.fit_to_content(window.project).canvas.duration
    assert window.project.canvas.duration == pytest.approx(expected)
    assert window.document.undo_stack.undoText() == "Fit Length to Content"


def test_a_new_size_redraws_the_scene(window) -> None:
    window.selection.clear()
    evaluator = window.evaluator
    window.properties.fields["canvas.width_px"].commit(640)
    window.properties.fields["canvas.height_px"].commit(640)
    assert (window.project.canvas.width_px, window.project.canvas.height_px) == (640, 640)
    assert window.evaluator is not evaluator
    window.seek(1.0)
    image = window.canvas._image
    assert image is not None and not image.isNull()
    window.document.undo_stack.undo()
    window.document.undo_stack.undo()
    assert window.project.canvas.width_px != 640


def test_scene_settings_in_the_edit_menu_shows_the_length(window, qt_app) -> None:
    layer_id, _ = a_clip(window)
    window.selection.set(layer_id)
    window.panel_toggles[window.properties].setChecked(False)
    action = next(a for a in window.menuBar().actions() if a.text() == "&Edit").menu()
    next(a for a in action.actions() if a.text() == "&Scene Settings...").trigger()
    qt_app.processEvents()
    assert window.selection.layer_ids == () or not window.selection.layer_ids
    assert window.panel_toggles[window.properties].isChecked()
    assert window.properties.fields["canvas.duration"].has_focus()
