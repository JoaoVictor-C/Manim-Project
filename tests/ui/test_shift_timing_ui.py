"""Edit > Shift Timing... (U4): move the selection on the timeline by a typed delta."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from manim_studio.core.schema import Canvas, Clip, Keyframe, Layer, Lifetime, Project, Spec
from manim_studio.ui.main_window import MainWindow

pytestmark = pytest.mark.ui

CANVAS = Canvas(width_px=320, height_px=180, fps=10, duration=20.0)


def project() -> Project:
    return Project(
        canvas=CANVAS,
        layers=[
            Layer(
                id="a",
                name="Title",
                spec=Spec(type="Square"),
                lifetime=Lifetime(in_=2.0),
                clips=[
                    Clip(id="f", kind="FadeIn", start=2.0, duration=1.0),
                    Clip(id="i", kind="Indicate", start=5.0, duration=1.0),
                ],
                tracks={"scale": [Keyframe(t=3.0, value=1.0), Keyframe(t=4.0, value=2.0)]},
            ),
            Layer(
                id="b", spec=Spec(type="Circle"), clips=[Clip(id="w", kind="Write", start=1.0, duration=1.0)]
            ),
        ],
    )


@pytest.fixture
def window(qt_app, tmp_path):
    path = tmp_path / "shift.json"
    path.write_text(project().model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.resize(1200, 760)
    win.show()
    win.load(path)
    qt_app.processEvents()
    yield win
    win.close()


def shift(window: MainWindow, delta: float | None) -> None:
    window.ask_shift = lambda: delta  # the dialog's answer
    action = next(a for a in window.menuBar().actions() if a.text() == "&Edit").menu()
    next(a for a in action.actions() if a.text() == "Shift &Timing...").trigger()


def test_a_selected_layer_moves_whole_in_one_undo_step(window) -> None:
    window.selection.set("a")
    shift(window, 5.0)
    layer = window.project.layer("a")
    assert [c.start for c in layer.clips] == [7.0, 10.0]
    assert [k.t for k in layer.tracks["scale"]] == [8.0, 9.0]
    assert layer.lifetime.in_ == 7.0  # Appears at went along: no copying it by hand
    assert window.document.undo_stack.count() == 1
    window.document.undo_stack.undo()
    assert [c.start for c in window.project.layer("a").clips] == [2.0, 5.0]


def test_several_selected_layers_move_together(window) -> None:
    window.selection.set_layers(["a", "b"])
    shift(window, 3.0)
    assert window.project.layer("a").clips[0].start == 5.0 and window.project.layer("b").clips[0].start == 4.0
    assert window.document.undo_stack.count() == 1


def test_a_selected_clip_moves_alone_and_carries_its_boundary(window) -> None:
    window.selection.set("a", "f")
    shift(window, 1.0)
    layer = window.project.layer("a")
    assert [c.start for c in layer.clips] == [3.0, 5.0] and layer.lifetime.in_ == 3.0


def test_selected_keys_move(window) -> None:
    window.selection.set("a", None, 3.0)
    shift(window, 2.0)
    times = [k.t for k in window.project.layer("a").tracks["scale"]]
    assert times == [pytest.approx(4.0), pytest.approx(5.0)]  # the key at 3 s went to 5 s, past the one at 4


def test_a_cancelled_dialog_changes_nothing(window) -> None:
    window.selection.set("a")
    shift(window, None)
    assert window.document.undo_stack.count() == 0


def test_with_nothing_selected_it_says_so(window) -> None:
    window.selection.clear()
    shift(window, 1.0)
    assert window.document.undo_stack.count() == 0
    assert "select a layer" in window.statusBar().currentMessage()


def test_a_refused_move_says_why_and_changes_nothing(window) -> None:
    window.selection.set("a", "f")
    shift(window, 3.0)  # the FadeIn (2-3 s) would run into the Indicate at 5 s
    assert window.document.undo_stack.count() == 0
    assert "Shift timing" in window.statusBar().currentMessage()


def test_a_move_that_cuts_an_animation_warns(window) -> None:
    from manim_studio.core import edits

    window.document.apply(edits.update_layer(window.project, "a", lifetime=Lifetime(in_=2.0, out=7.0)), "Out")
    window.selection.set("a", "i")
    shift(window, 3.0)  # the Indicate moves past Disappears at 7 s
    assert window.document.undo_stack.count() == 2
    assert "ends before its animation" in window.statusBar().currentMessage()
