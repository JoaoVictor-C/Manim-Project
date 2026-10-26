"""Document snapshots and undo (ADR 0014), and their wiring in the editor."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from manim_studio.core.editing import edits
from manim_studio.core.engine.evaluator import Evaluator
from manim_studio.core.model.schema import Clip, Layer, Project, Transform2D
from manim_studio.render.cairo_export import make_camera, render_frame
from manim_studio.ui.main_window import MainWindow
from manim_studio.ui.session.document import Document
from support import CANVAS, FRAMES, TEXT, max_diff

pytestmark = pytest.mark.ui

DEMO = Path(__file__).resolve().parents[3] / "examples" / "euler.json"


def project() -> Project:
    return Project(
        canvas=CANVAS,
        layers=[
            Layer(
                id="a",
                spec=TEXT,
                clips=[
                    Clip(id="w", kind="Write", start=0.0, duration=0.4),
                    Clip(id="i", kind="Indicate", start=0.5, duration=0.3),
                ],
            )
        ],
    )


@pytest.fixture
def doc(qt_app):
    document = Document(project())
    events = []
    document.changed.connect(lambda p, ids, kind: events.append((p, ids, kind)))
    document.events = events
    return document


def test_apply_pushes_one_step_and_undo_redo_swap_snapshots(doc) -> None:
    before = doc.project
    edit = edits.move_clip(before, "a", "i", 0.6)
    doc.apply(edit, "Move clip")
    assert doc.project is edit.project
    assert doc.undo_stack.count() == 1
    assert doc.undo_stack.undoText() == "Move clip"
    doc.undo_stack.undo()
    assert doc.project is before
    doc.undo_stack.redo()
    assert doc.project is edit.project
    assert [kind for _, _, kind in doc.events] == ["timing", "timing", "timing"]


def test_undo_reports_the_reverse_kind(doc) -> None:
    doc.apply(edits.update_layer(doc.project, "a", base=Transform2D(position=(1.0, 0.0))), "Move layer")
    doc.undo_stack.undo()
    assert doc.events[-1][1:] == (frozenset({"a"}), "transform")


def test_a_drag_is_one_undo_step(doc) -> None:
    before = doc.project
    doc.begin_preview()
    for start in (0.55, 0.6, 0.65):
        doc.preview(edits.move_clip(before, "a", "i", start))
    assert doc.undo_stack.count() == 0
    doc.commit_preview("Move clip")
    assert doc.undo_stack.count() == 1
    assert doc.project.layer("a").clips[1].start == pytest.approx(0.65)
    doc.undo_stack.undo()
    assert doc.project is before


def test_commit_without_change_records_nothing(doc) -> None:
    doc.begin_preview()
    doc.commit_preview("Move clip")
    assert doc.undo_stack.count() == 0
    assert not doc.dragging


def test_an_edit_that_changes_nothing_records_nothing(doc) -> None:
    doc.apply(edits.move_layer(doc.project, "a", 0), "Reorder layers")
    doc.apply(edits.update_layer(doc.project, "a", name=""), "Rename layer")
    assert doc.undo_stack.count() == 0
    assert doc.events == []


def test_repeated_edits_merge_into_one_step(doc) -> None:
    """ADR 0016: an arrow key held down is one undo step; separate taps are separate."""
    before = doc.project
    key = ("nudge", "a")
    for i, merge in enumerate((False, True, True)):
        doc.apply(
            edits.update_layer(doc.project, "a", base={"position": (0.1 * (i + 1), 0)}), "Nudge", key, merge
        )
    assert doc.undo_stack.count() == 1
    doc.apply(edits.update_layer(doc.project, "a", base={"position": (1.0, 0)}), "Nudge", key, merge=False)
    assert doc.undo_stack.count() == 2  # a new tap
    doc.undo_stack.undo()
    assert doc.project.layer("a").base.position == pytest.approx((0.3, 0))
    doc.undo_stack.undo()
    assert doc.project is before


def test_merging_needs_the_same_key(doc) -> None:
    doc.apply(edits.update_layer(doc.project, "a", base={"position": (1, 0)}), "Nudge", ("nudge", "a"))
    doc.apply(edits.update_layer(doc.project, "a", name="x"), "Rename", ("rename", "a"), merge=True)
    doc.apply(edits.update_layer(doc.project, "a", base={"position": (2, 0)}), "Nudge", None, merge=True)
    assert doc.undo_stack.count() == 3


def test_cancel_restores_the_drag_start(doc) -> None:
    before = doc.project
    doc.begin_preview()
    doc.preview(edits.move_clip(before, "a", "i", 0.7))
    doc.cancel_preview()
    assert doc.project is before
    assert doc.undo_stack.count() == 0
    assert doc.events[-1][2] == "timing"


def test_misuse_is_rejected(doc) -> None:
    with pytest.raises(RuntimeError):
        doc.preview(edits.move_clip(doc.project, "a", "i", 0.6))
    doc.begin_preview()
    with pytest.raises(RuntimeError):
        doc.begin_preview()
    with pytest.raises(RuntimeError):
        doc.apply(edits.move_clip(doc.project, "a", "i", 0.6), "x")
    doc.cancel_preview()


def test_replace_clears_history(doc) -> None:
    doc.apply(edits.move_clip(doc.project, "a", "i", 0.6), "Move clip")
    resets = []
    doc.reset.connect(resets.append)
    fresh = project()
    doc.replace(fresh)
    assert doc.project is fresh and doc.undo_stack.count() == 0 and resets == [fresh]


# -- editor wiring ------------------------------------------------------------------


@pytest.fixture
def window(qt_app, tmp_path):
    path = tmp_path / "euler.json"
    path.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
    win = MainWindow()
    win.resize(640, 400)
    win.show()
    win.load(path)
    yield win
    win.close()
    qt_app.processEvents()


def _assert_matches_fresh(window: MainWindow) -> None:
    camera = make_camera(window.project.canvas.model_copy(update={"width_px": 320, "height_px": 180}))
    fresh = Evaluator(window.project)
    for t in (0.3, 1.2, 3.0, 4.8, 6.4):
        diff = max_diff(render_frame(camera, window.evaluator.frame(t)), render_frame(camera, fresh.frame(t)))
        assert diff <= 1, f"t={t}"


def test_edits_undo_and_redo_keep_the_evaluator_in_sync(window) -> None:
    doc = window.document
    doc.apply(edits.move_clip(doc.project, "eq1", "e1-write", 0.8), "Move Write")
    doc.apply(edits.update_clip(doc.project, "eq1", "e1-ind", ease={"name": "linear"}), "Ease")
    doc.apply(edits.move_clip(doc.project, "eq1", "e1-morph", 4.6), "Move morph")
    _assert_matches_fresh(window)
    for _ in range(3):
        doc.undo_stack.undo()
        _assert_matches_fresh(window)
    for _ in range(3):
        doc.undo_stack.redo()
    _assert_matches_fresh(window)


def test_title_marks_unsaved_changes(window) -> None:
    assert not window.windowTitle().endswith("*")
    window.document.apply(edits.move_clip(window.document.project, "eq1", "e1-write", 0.6), "Move")
    assert window.windowTitle().endswith("*")
    window.save()
    assert not window.windowTitle().endswith("*")
    window.document.undo_stack.undo()
    assert window.windowTitle().endswith("*")


def test_edit_menu_has_undo_and_redo(window) -> None:
    menu = next(a.menu() for a in window.menuBar().actions() if a.text() == "&Edit")
    texts = [a.text() for a in menu.actions()]
    assert any(t.startswith("&Undo") for t in texts) and any(t.startswith("&Redo") for t in texts)


def test_loading_another_project_resets_history(window, tmp_path) -> None:
    window.document.apply(edits.move_clip(window.document.project, "eq1", "e1-write", 0.6), "Move")
    other = tmp_path / "other.json"
    other.write_text(project().model_dump_json(by_alias=True), encoding="utf-8")
    window.load(other)
    assert window.document.undo_stack.count() == 0
    assert window.project.layers[0].id == "a"
    assert window.evaluator.project is window.project
    assert len(FRAMES) and window.evaluator.frame(0.2)  # renders the new project


def test_layers_dock_edits_reach_the_canvas(window) -> None:
    """S2.4 wiring: the dock goes through the build service to the evaluator."""
    assert window.layers.isEnabled()
    assert window.layers.ids_front_to_back()[-1] == window.project.layers[0].id
    window.layers.add_object("Star")
    window.layers.shift_selected(-1)
    window.layers.select(window.project.layers[0].id)
    window.layers.delete_selected()
    assert [window.document.undo_stack.text(i) for i in range(3)] == [
        "Add Star",
        "Reorder layers",
        "Delete layer",
    ]
    _assert_matches_fresh(window)
    window.document.undo_stack.undo()
    _assert_matches_fresh(window)


def test_selection_flows_to_the_properties_dock(window) -> None:
    first = window.project.layers[0]
    window.layers.select(first.id)
    assert window.properties.layer_id == first.id and window.properties.clip_id is None
    clip = first.clips[0]
    window.timeline.clipSelected.emit(first.id, clip.id)
    assert (window.properties.layer_id, window.properties.clip_id) == (first.id, clip.id)
    assert window.layers.selected_id() == first.id
    window.properties.fields["clip.duration"].commit(clip.duration + 0.1)
    assert window.project.layers[0].clips[0].duration == pytest.approx(clip.duration + 0.1)
    _assert_matches_fresh(window)


@pytest.mark.parametrize(
    ("answer", "replaced", "saved"),
    [("discard", True, False), ("cancel", False, False), ("save", True, True)],
)
def test_unsaved_changes_are_confirmed_before_new(window, monkeypatch, answer, replaced, saved) -> None:
    asked = []
    monkeypatch.setattr(window, "ask_unsaved", lambda: asked.append(1) or answer)
    path = window.path
    window.document.apply(edits.move_clip(window.project, "eq1", "e1-write", 0.8), "Move Write")
    window.new_project()
    assert asked == [1]
    assert (window.project.layers == []) is replaced
    assert ('"start": 0.8' in path.read_text(encoding="utf-8")) is saved


def test_no_question_when_nothing_changed(window, monkeypatch) -> None:
    monkeypatch.setattr(window, "ask_unsaved", lambda: pytest.fail("asked although saved"))
    window.new_project()
    assert window.project.layers == []


def test_cancel_keeps_the_window_open(window, monkeypatch) -> None:
    from PySide6.QtGui import QCloseEvent

    monkeypatch.setattr(window, "ask_unsaved", lambda: "cancel")
    window.document.apply(edits.move_clip(window.project, "eq1", "e1-write", 0.8), "Move Write")
    event = QCloseEvent()
    window.closeEvent(event)
    assert not event.isAccepted()
