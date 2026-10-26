"""Paths in the editor (P3c.3, ADR 0025): the Move menu, the Path choice, the drag hint."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPointF

from acceptance.test_acceptance_v1 import menu_action, timeline_menu
from manim_studio.core.model.schema import Canvas, Clip, Layer, Project, Spec, Transform2D
from manim_studio.ui.main_window import MainWindow
from manim_studio.ui.timeline.view import ClipItem
from ui.canvas.test_canvas_tools import drag, px

pytestmark = pytest.mark.ui


@pytest.fixture
def window(qt_app, tmp_path):
    project = Project(
        canvas=Canvas(width_px=640, height_px=360, fps=30, duration=4.0),
        layers=[
            Layer(id="ring", spec=Spec(type="Circle", params={"radius": 2.0})),
            Layer(id="line", spec=Spec(type="Line")),
            Layer(id="axes", spec=Spec(type="Axes")),
            Layer(id="sin", parent_id="axes", spec=Spec(type="Graph", params={"expression": "sin(x)"})),
            Layer(
                id="dot",
                spec=Spec(type="Dot", params={"radius": 0.3}),
                base=Transform2D(position=(-5.0, 2.5)),
            ),
        ],
    )
    path = tmp_path / "paths.json"
    path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.resize(1100, 800)
    win.show()
    win.load(path)
    qt_app.processEvents()
    win.messages = []
    win.move_tool.message.connect(win.messages.append)
    yield win
    win.close()


def test_move_along_a_path_from_the_timeline(window, qt_app) -> None:
    menu = timeline_menu(window, "dot", 0.0)
    paths = menu_action(menu, "Add clip", "Move", "MoveAlongPath").menu()
    assert [a.text() for a in paths.actions()] == ["ring", "line", "axes", "sin"]  # not the dot itself
    menu_action(menu, "Add clip", "Move", "MoveAlongPath", "sin").trigger()
    clip = window.project.layer("dot").clips[0]
    assert (clip.kind, clip.params) == ("MoveAlongPath", {"path": "sin"})
    assert window.document.undo_stack.undoText() == "Add MoveAlongPath clip"
    clips = [item for item in window.timeline.scene().items() if isinstance(item, ClipItem)]
    assert [(c.layer_id, c.kind) for c in clips] == [("dot", "MoveAlongPath")]  # the timeline draws it


def test_graphs_do_not_travel(window) -> None:
    menu = timeline_menu(window, "sin", 0.0)
    titles = [a.text() for a in menu_action(menu, "Add clip").menu().actions()]
    assert "Move" not in titles


def test_the_path_can_be_changed_in_properties(window, qt_app) -> None:
    menu_action(timeline_menu(window, "dot", 0.0), "Add clip", "Move", "MoveAlongPath", "ring").trigger()
    clip = window.project.layer("dot").clips[0]
    window.selection.set("dot", clip.id)
    qt_app.processEvents()
    field = window.properties.fields["clip.params.path"]
    assert [field.widget.itemText(i) for i in range(field.widget.count())] == ["ring", "line", "axes", "sin"]
    field.commit("line")
    qt_app.processEvents()
    assert window.project.layer("dot").clips[0].params == {"path": "line"}


def test_dragging_a_path_follower_after_its_start_explains_why_it_stays(window, qt_app) -> None:
    run = Clip(id="run", kind="MoveAlongPath", start=0.0, duration=1.0, params={"path": "ring"})
    from manim_studio.core.editing import edits

    window.document.apply(edits.update_layer(window.project, "dot", clips=[run]), "Run")
    window.seek(2.0)
    at = window.canvas.evaluator.frame_layers(2.0)
    dot = dict(at)["dot"].get_center()
    start = px(window, dot[0], dot[1])
    drag(window, start, start + QPointF(40, 0), qt_app)
    assert "follows a path" in window.messages[-1]
