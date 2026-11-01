"""Compound sequences on the timeline (ADR 0079): a bar over the members, a click picks them all, a drag moves
them together in one undo step; Edit > Make Sequence from Selection... and Dissolve Sequence."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from manim_studio.core.editing.sequences import Members, make_sequence
from manim_studio.core.model.schema import Canvas, Clip, Keyframe, Layer, Project, Spec
from manim_studio.ui.main_window import MainWindow
from manim_studio.ui.session.document import Document
from manim_studio.ui.timeline.view import SEQUENCE_BAR, SequenceItem, TimelineView

pytestmark = pytest.mark.ui
NO = Qt.KeyboardModifier.NoModifier
ALT = Qt.KeyboardModifier.AltModifier


def project() -> Project:
    return Project(
        canvas=Canvas(width_px=320, height_px=180, fps=10, duration=10.0),
        layers=[
            Layer(
                id="a",
                spec=Spec(type="Square"),
                clips=[
                    Clip(id="f", kind="FadeIn", start=1.0, duration=1.0),
                    Clip(id="i", kind="Indicate", start=6.0, duration=1.0),
                ],
                tracks={"scale": [Keyframe(t=2.0, value=1.0), Keyframe(t=8.0, value=2.0)]},
            ),
            Layer(
                id="b", spec=Spec(type="Circle"), clips=[Clip(id="w", kind="Write", start=2.0, duration=1.0)]
            ),
        ],
    )


def grouped() -> Project:
    members = Members(clips=(("a", "f"), ("b", "w")), keys=(("a", "scale", 2.0),))
    return make_sequence(project(), "Intro", members).project


@pytest.fixture
def view(qt_app):
    v = TimelineView()
    v.follow_playhead = False
    v.resize(1000, 220)
    v.set_document(Document(grouped()))
    v.show()
    qt_app.processEvents()
    v.messages = []
    v.message.connect(v.messages.append)
    yield v
    v.close()


def _send(view, kind, pos: QPointF, modifiers=NO) -> None:
    buttons = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease else Qt.MouseButton.LeftButton
    button = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseMove else Qt.MouseButton.LeftButton
    global_pos = QPointF(view.viewport().mapToGlobal(pos.toPoint()))
    QApplication.sendEvent(view.viewport(), QMouseEvent(kind, pos, global_pos, button, buttons, modifiers))


def bar_point(view, t: float) -> QPointF:
    (item,) = view.sequence_items()
    return QPointF(view.mapFromScene(QPointF(view.scale.x(t), item.rect().top() + SEQUENCE_BAR / 2)))


def test_a_bar_is_drawn_over_the_members_with_the_name(view) -> None:
    (item,) = view.sequence_items()
    assert isinstance(item, SequenceItem) and item.name == "Intro"
    assert item.rect().top() == min(view.row_top("a"), view.row_top("b"))
    assert item.box.bottom() == max(view.row_top("a"), view.row_top("b")) + 28
    assert item.rect().left() < view.scale.x(1.0) < view.scale.x(3.0) < item.rect().right()
    image = view.viewport().grab().toImage()  # it paints (smoke) - the bar in the accent colour
    p = bar_point(view, 2.5).toPoint()
    assert image.pixelColor(p) != image.pixelColor(p.x(), p.y() + 60)


def test_a_click_on_the_bar_picks_every_member(view) -> None:
    p = bar_point(view, 2.5)
    _send(view, QEvent.Type.MouseButtonPress, p)
    _send(view, QEvent.Type.MouseButtonRelease, p)
    assert view.picked_clips == {("a", "f"), ("b", "w")}
    assert view.picked_keys == {("a", 20, "scale")}
    assert view.document.undo_stack.count() == 0  # a click moves nothing
    assert "Intro" in view.messages[-1]


def test_dragging_the_bar_moves_the_sequence_in_one_undo_step(view) -> None:
    start = bar_point(view, 2.5)
    end = QPointF(start.x() + view.scale.x(2.0) - view.scale.x(0.0), start.y())
    _send(view, QEvent.Type.MouseButtonPress, start, ALT)
    _send(view, QEvent.Type.MouseMove, QPointF(start.x() + 3, start.y()), ALT)
    _send(view, QEvent.Type.MouseMove, end, ALT)
    _send(view, QEvent.Type.MouseButtonRelease, end, ALT)
    p = view.project
    assert [c.start for c in p.layer("a").clips] == pytest.approx([3.0, 6.0])
    assert p.layer("b").clips[0].start == pytest.approx(4.0)
    assert [k.t for k in p.layer("a").tracks["scale"]] == pytest.approx([4.0, 8.0])
    assert [r.t for r in p.sequences[0].keys] == pytest.approx([4.0])
    stack = view.document.undo_stack
    assert stack.count() == 1 and stack.text(0) == "Move sequence"
    stack.undo()
    assert view.project == grouped()


@pytest.fixture
def window(qt_app, tmp_path):
    path = tmp_path / "sequences.json"
    path.write_text(project().model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.resize(1200, 760)
    win.show()
    win.load(path)
    qt_app.processEvents()
    yield win
    win.close()


def edit_action(window: MainWindow, text: str):
    menu = next(a for a in window.menuBar().actions() if a.text() == "&Edit").menu()
    return next(a for a in menu.actions() if a.text() == text)


def test_make_a_sequence_from_the_selection_and_dissolve_it(window) -> None:
    make = edit_action(window, "Make Se&quence from Selection...")
    dissolve = edit_action(window, "&Dissolve Sequence")
    asked = []
    window.ask_sequence_name = lambda suggested: asked.append(suggested) or "Opening"
    make.trigger()  # nothing picked: refused, nothing asked
    assert window.project.sequences == [] and asked == []
    window.timeline.toggle_clip_pick("a", "f")
    window.timeline.toggle_clip_pick("b", "w")
    make.trigger()
    assert asked == ["Sequence 1"]
    (seq,) = window.project.sequences
    assert seq.name == "Opening"
    assert {(r.layer, r.clip) for r in seq.clips} == {("a", "f"), ("b", "w")}
    assert window.document.undo_stack.count() == 1
    assert len(window.timeline.sequence_items()) == 1
    dissolve.trigger()
    assert window.project.sequences == [] and window.document.undo_stack.count() == 2
    window.document.undo_stack.undo()
    assert window.project.sequences[0].name == "Opening"
    window.document.undo_stack.undo()
    assert window.project.sequences == [] and window.timeline.sequence_items() == []


def test_a_cancelled_name_makes_nothing(window) -> None:
    window.ask_sequence_name = lambda suggested: None
    window.selection.set("a", "f")
    edit_action(window, "Make Se&quence from Selection...").trigger()
    assert window.project.sequences == [] and window.document.undo_stack.count() == 0
