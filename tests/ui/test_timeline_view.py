"""Timeline widget (S1.4, S1.5): layout, scrubbing, zoom, and mouse drags end to end."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication

from manim_studio.core.schema import Canvas, Clip, Layer, Project, Spec
from manim_studio.ui.document import Document
from manim_studio.ui.timeline.view import ROW_HEIGHT, RULER_HEIGHT, ClipItem, TimelineView

pytestmark = pytest.mark.ui
FPS = 30


def project() -> Project:
    return Project(
        canvas=Canvas(duration=6.0, fps=FPS),
        layers=[
            Layer(
                id="a",
                spec=Spec(type="Square"),
                clips=[
                    Clip(id="c1", kind="Create", start=0.5, duration=1.0),
                    Clip(id="c2", kind="Indicate", start=3.0, duration=1.0),
                ],
            ),
            Layer(
                id="b",
                spec=Spec(type="Circle"),
                clips=[Clip(id="m", kind="Transform", start=1.0, duration=1.0, to_layer="c")],
            ),
            Layer(id="c", spec=Spec(type="Triangle")),
        ],
    )


@pytest.fixture
def view(qt_app):
    doc = Document(project())
    v = TimelineView()
    v.resize(1000, 200)
    v.set_document(doc)
    v.show()
    qt_app.processEvents()
    v.changes = []
    doc.changed.connect(lambda *args: v.changes.append(args))
    yield v
    v.close()


def _send(
    view: TimelineView, kind: QEvent.Type, pos: QPointF, modifiers=Qt.KeyboardModifier.NoModifier
) -> None:
    buttons = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease else Qt.MouseButton.LeftButton
    button = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseMove else Qt.MouseButton.LeftButton
    global_pos = QPointF(view.viewport().mapToGlobal(pos.toPoint()))
    QApplication.sendEvent(view.viewport(), QMouseEvent(kind, pos, global_pos, button, buttons, modifiers))


def press(view, pos, **kw):
    _send(view, QEvent.Type.MouseButtonPress, pos, **kw)


def move(view, pos, **kw):
    _send(view, QEvent.Type.MouseMove, pos, **kw)


def release(view, pos, **kw):
    _send(view, QEvent.Type.MouseButtonRelease, pos, **kw)


def point(view: TimelineView, t: float, row: int) -> QPointF:
    scene = QPointF(view.scale.x(t), RULER_HEIGHT + row * ROW_HEIGHT + ROW_HEIGHT / 2)
    return QPointF(view.mapFromScene(scene))


def clip(view, layer_id, clip_id) -> Clip:
    return next(c for c in view.project.layer(layer_id).clips if c.id == clip_id)


# -- layout ------------------------------------------------------------------------


def test_one_bar_per_clip_at_the_right_place(view) -> None:
    items = view.clip_items()
    assert len(items) == 3
    bar = view.clip_item("a", "c2")
    assert bar.rect().x() == pytest.approx(view.scale.x(3.0))
    assert bar.rect().width() == pytest.approx(view.scale.px_per_second * 1.0)
    assert view.clip_item("b", "m").rect().y() > bar.rect().y()  # second row


def test_lifetime_bands_follow_inference(view) -> None:
    bands = [i for i in view.scene().items() if not isinstance(i, ClipItem)]
    starts = sorted(round(view.scale.t(b.rect().x()), 3) for b in bands)
    assert starts == [0.0, 0.5, 2.0]  # b from 0, a from its Create, c from the morph's end


def test_ruler_click_seeks(view) -> None:
    seeks = []
    view.seekRequested.connect(seeks.append)
    target = QPointF(view.mapFromScene(QPointF(view.scale.x(2.5), 0)).x(), RULER_HEIGHT / 2)
    press(view, target)
    move(view, QPointF(target.x() + view.scale.px_per_second, target.y()))
    release(view, target)
    assert seeks[0] == pytest.approx(2.5, abs=0.02)
    assert seeks[1] == pytest.approx(3.5, abs=0.02)
    assert view.document.undo_stack.count() == 0


def test_zoom_keeps_the_time_under_the_cursor(view) -> None:
    x = 400
    before = view.scale.t(view.mapToScene(x, 0).x())
    view.zoom(2.0, x)
    after = view.scale.t(view.mapToScene(x, 0).x())
    assert after == pytest.approx(before, abs=1 / view.scale.px_per_second)
    assert view.clip_item("a", "c2").rect().width() == pytest.approx(view.scale.px_per_second)


# -- drags ---------------------------------------------------------------------------


def test_drag_moves_a_clip_as_one_undo_step(view, qt_app) -> None:
    start = point(view, 3.5, 0)
    press(view, start)
    for dx in (10, 25, 36):
        move(view, QPointF(start.x() + dx, start.y()))
        qt_app.processEvents()
    release(view, QPointF(start.x() + 36, start.y()))
    assert clip(view, "a", "c2").start == pytest.approx(3.0 + 36 / view.scale.px_per_second, abs=1 / FPS)
    assert view.document.undo_stack.count() == 1
    assert view.document.undo_stack.undoText() == "Move clip"
    view.document.undo_stack.undo()
    assert clip(view, "a", "c2").start == 3.0


def test_drag_stops_at_the_neighbour(view, qt_app) -> None:
    start = point(view, 3.5, 0)
    press(view, start)
    move(view, QPointF(start.x() - 1000, start.y()))
    release(view, QPointF(start.x() - 1000, start.y()))
    assert clip(view, "a", "c2").start == 1.5  # end of c1


def test_dragging_the_right_edge_trims(view, qt_app) -> None:
    edge = point(view, 4.0, 0)
    grab = QPointF(edge.x() - 2, edge.y())
    press(view, grab)
    move(view, QPointF(grab.x() + view.scale.px_per_second * 0.5, grab.y()))
    release(view, QPointF(grab.x() + view.scale.px_per_second * 0.5, grab.y()))
    c2 = clip(view, "a", "c2")
    assert (c2.start, c2.end) == pytest.approx((3.0, 4.5), abs=1 / FPS)
    assert view.document.undo_stack.undoText() == "Trim clip"


def test_dragging_the_left_edge_trims(view, qt_app) -> None:
    edge = point(view, 3.0, 0)
    grab = QPointF(edge.x() + 2, edge.y())
    press(view, grab)
    move(view, QPointF(grab.x() - view.scale.px_per_second * 0.5, grab.y()))
    release(view, QPointF(grab.x() - view.scale.px_per_second * 0.5, grab.y()))
    c2 = clip(view, "a", "c2")
    assert (c2.start, c2.end) == pytest.approx((2.5, 4.0), abs=1 / FPS)


def test_moving_a_morph_moves_the_target_lifetime(view, qt_app) -> None:
    start = point(view, 1.5, 1)
    press(view, start)
    move(view, QPointF(start.x() + view.scale.px_per_second, start.y()))
    release(view, QPointF(start.x() + view.scale.px_per_second, start.y()))
    assert view.project.lifetime("c")[0] == pytest.approx(3.0, abs=1 / FPS)


def test_escape_cancels_the_drag(view, qt_app) -> None:
    before = view.project
    start = point(view, 3.5, 0)
    press(view, start)
    move(view, QPointF(start.x() + 60, start.y()))
    qt_app.processEvents()
    assert view.project is not before
    QApplication.sendEvent(
        view, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    )
    release(view, QPointF(start.x() + 60, start.y()))
    assert view.project is before
    assert view.document.undo_stack.count() == 0


def test_moves_are_coalesced(view, qt_app) -> None:
    """Many mouse moves before the event loop runs -> one applied preview (ADR 0009)."""
    start = point(view, 3.5, 0)
    press(view, start)
    for dx in range(1, 30):
        move(view, QPointF(start.x() + dx, start.y()))
    assert view.changes == []
    qt_app.processEvents()
    assert len(view.changes) == 1
    release(view, QPointF(start.x() + 29, start.y()))


def test_snapping_and_alt(view, qt_app) -> None:
    """An edge near the playhead snaps to it; with Alt only the frame grid applies."""
    view.set_playhead(2.23)
    start = point(view, 1.0, 0)  # c1 spans 0.5-1.5
    target_dx = view.scale.x(2.25 - 1.5) - view.scale.x(0)  # end lands at 2.25, 2 px from playhead
    press(view, start)
    move(view, QPointF(start.x() + target_dx, start.y()))
    release(view, QPointF(start.x() + target_dx, start.y()))
    assert clip(view, "a", "c1").end == pytest.approx(2.23)
    view.document.undo_stack.undo()
    press(view, start, modifiers=Qt.KeyboardModifier.AltModifier)
    move(view, QPointF(start.x() + target_dx, start.y()), modifiers=Qt.KeyboardModifier.AltModifier)
    release(view, QPointF(start.x() + target_dx, start.y()), modifiers=Qt.KeyboardModifier.AltModifier)
    c1 = clip(view, "a", "c1")
    assert c1.start == pytest.approx(round(1.25 * FPS) / FPS)  # start on the frame grid, no snap
    assert c1.end != pytest.approx(2.23)


def test_click_selects_without_creating_an_undo_step(view, qt_app) -> None:
    selected = []
    view.clipSelected.connect(lambda *ids: selected.append(ids))
    pos = point(view, 3.5, 0)
    press(view, pos)
    release(view, pos)
    assert selected == [("a", "c2")]
    assert view.clip_item("a", "c2").selected
    assert view.document.undo_stack.count() == 0


def test_clicking_empty_space_does_nothing(view) -> None:
    pos = point(view, 5.5, 2)
    press(view, pos)
    release(view, pos)
    assert view.document.undo_stack.count() == 0 and not view.document.dragging


def test_reset_clears_selection(view) -> None:
    view.selected = ("a", "c2")
    view.document.replace(project())
    assert view.selected is None
    assert len(view.clip_items()) == 3
