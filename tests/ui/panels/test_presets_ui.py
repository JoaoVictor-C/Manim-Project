"""Presets and themes in the editor (P5e.1, ADR 0039): Animate > Apply Preset at the playhead,
the timeline row's Apply preset at its time, refusals in the status bar, saving a layer's
animation as a preset, View > Themes on the selection or the scene, skipped library files."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from acceptance.test_acceptance_v1 import menu_action, timeline_menu
from manim_studio.core.editing import library
from manim_studio.core.model.schema import Canvas, Clip, Layer, Project, Spec
from manim_studio.ui.main_window import MainWindow

pytestmark = pytest.mark.ui


@pytest.fixture
def window(qt_app, tmp_path):
    project = Project(
        canvas=Canvas(width_px=320, height_px=180, fps=10, duration=6.0),
        layers=[
            Layer(id="sq", name="Square", spec=Spec(type="Square")),
            Layer(id="tx", name="Title", spec=Spec(type="Text", params={"text": "Hi"})),
        ],
    )
    path = tmp_path / "scene.json"
    path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.show()
    win.load(path)
    yield win
    win.close()


def test_apply_a_preset_to_the_selection_at_the_playhead_in_one_step(window) -> None:
    window.selection.set("tx")
    window.seek(1.0)
    steps = window.document.undo_stack.count()
    menu_action(window.menuBar(), "Animate", "Apply Preset", "Entrance", "Typewriter").trigger()
    (clip,) = window.project.layer("tx").clips
    assert (clip.kind, clip.start) == ("AddTextLetterByLetter", 1.0)
    assert window.document.undo_stack.count() == steps + 1
    assert window.document.undo_stack.undoText() == "Apply Typewriter"
    action = menu_action(window.menuBar(), "Animate", "Apply Preset", "Entrance", "Pop in")
    assert action.toolTip().startswith("Fades in while growing")


def test_without_a_selection_or_room_the_status_bar_says_why(window) -> None:
    window.selection.clear()
    menu_action(window.menuBar(), "Animate", "Apply Preset", "Exit", "Fade out").trigger()
    assert window.statusBar().currentMessage() == "Select a layer to animate first"
    window.selection.set("sq")
    window.seek(5.8)
    menu_action(window.menuBar(), "Animate", "Apply Preset", "Exit", "Fade out").trigger()
    assert "the scene ends at 6 s" in window.statusBar().currentMessage()
    assert window.project.layer("sq").clips == []


def test_the_timeline_row_applies_at_its_own_time(window) -> None:
    menu = timeline_menu(window, "sq", 2.0)
    menu_action(menu, "Apply preset", "Emphasis", "Indicate").trigger()
    (clip,) = window.project.layer("sq").clips
    assert (clip.kind, clip.start) == ("Indicate", 2.0)


def test_save_a_layers_animation_as_a_preset_and_reuse_it(window) -> None:
    window.document.replace(
        window.project.model_copy(
            update={
                "layers": [
                    window.project.layer("sq").model_copy(
                        update={"clips": [Clip(id="g", kind="GrowFromCenter", start=0.5, duration=0.7)]}
                    ),
                    window.project.layer("tx"),
                ]
            }
        )
    )
    window.selection.set("sq")
    window.ask_preset_name = lambda: ("My grow", "entrance")
    menu_action(window.menuBar(), "Animate", "Save Animation as Preset...").trigger()
    saved = Path(os.environ["MANIM_STUDIO_LIBRARY"]) / "preset-My grow.json"
    try:
        assert saved.is_file() and "Saved the preset My grow" in window.statusBar().currentMessage()
        window.selection.set("tx")
        window.seek(3.0)
        menu_action(window.menuBar(), "Animate", "Apply Preset", "Entrance", "My grow").trigger()
        (clip,) = window.project.layer("tx").clips
        assert (clip.kind, clip.start, clip.duration) == ("GrowFromCenter", 3.0, 0.7)
        window.ask_preset_name = lambda: None  # cancelled: nothing written
        menu_action(window.menuBar(), "Animate", "Save Animation as Preset...").trigger()
    finally:
        saved.unlink(missing_ok=True)


def test_a_theme_recolours_the_selection_or_the_scene(window) -> None:
    window.selection.set("tx")
    menu_action(window.menuBar(), "View", "Themes", "Paper").trigger()
    paper = next(t for t in window.library.themes if t.name == "Paper")
    assert window.project.layer("tx").spec.style == {"fill": paper.text}
    assert window.project.layer("sq").spec.style == {} and window.project.canvas.background == "#000000"
    window.selection.clear()
    menu_action(window.menuBar(), "View", "Themes", "Midnight").trigger()
    midnight = next(t for t in window.library.themes if t.name == "Midnight")
    assert window.project.canvas.background == midnight.background
    assert window.project.layer("sq").spec.style["stroke"] == midnight.shape
    assert window.document.undo_stack.undoText() == "Apply the Midnight theme"


def test_skipped_library_files_are_reported_at_start(qt_app) -> None:
    bad = Path(os.environ["MANIM_STUDIO_LIBRARY"]) / "broken.json"
    bad.write_text("{oops", encoding="utf-8")
    try:
        win = MainWindow()
        assert "preset or theme file skipped: broken.json" in win.statusBar().currentMessage()
        assert len(win.library.presets) == len(library.load_library([library.BUILTIN_FOLDER]).presets)
        win.close()
    finally:
        bad.unlink()


def test_insert_a_template_from_the_add_menu_and_save_one(window) -> None:
    window.selection.set("sq")
    window.seek(1.0)
    menu_action(window.layers.library_menu, "Lower third").trigger()
    added = [x for x in window.project.layers if x.id not in ("sq", "tx")]
    assert [x.name for x in added] == ["Band", "Name", "Role"]
    assert window.selection.layer_id == added[0].id
    assert window.document.undo_stack.undoText() == "Insert Lower third"
    assert [x.id for x in window.project.layers].index(added[0].id) == 1  # right above the square
    window.ask_template_name = lambda: "My band"
    menu_action(window.menuBar(), "Animate", "Save Object as Template...").trigger()
    saved = Path(os.environ["MANIM_STUDIO_LIBRARY"]) / "template-My band.json"
    try:
        assert saved.is_file()
        window.seek(3.0)
        menu_action(window.layers.library_menu, "My band").trigger()
        band = window.project.layer(window.selection.layer_id)
        assert band.name == "Band copy" and band.clips[0].start == 3.0
    finally:
        saved.unlink(missing_ok=True)


def test_a_template_that_does_not_fit_is_refused(window) -> None:
    window.seek(5.9)
    menu_action(window.layers.library_menu, "Title card").trigger()
    assert "Title card needs until" in window.statusBar().currentMessage()
    assert len(window.project.layers) == 2
