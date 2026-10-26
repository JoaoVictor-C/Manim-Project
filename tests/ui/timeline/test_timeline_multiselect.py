"""Timeline multi-selection (U4b): Shift/Ctrl+click, a rubber band and Ctrl+A pick clips and keys;
dragging one moves them all by one snapped delta in one undo step; Delete removes them all; the
lifetime band of selected rows drags those layers whole. Real mouse events, as a user does it."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication

from manim_studio.core.model.schema import Canvas, Clip, Keyframe, Layer, Lifetime, Project, Spec
from manim_studio.ui.session.document import Document
from manim_studio.ui.timeline.view import KEY_OFFSET, ROW_HEIGHT, SUB_ROW_HEIGHT, TimelineView

pytestmark = pytest.mark.ui
FPS = 30
NO = Qt.KeyboardModifier.NoModifier
SHIFT = Qt.KeyboardModifier.ShiftModifier
CTRL = Qt.KeyboardModifier.ControlModifier
ALT = Qt.KeyboardModifier.AltModifier


def project(**canvas) -> Project:
    return Project(
        canvas=Canvas(duration=10.0, fps=FPS, **canvas),
        layers=[
            Layer(
                id="a",
                spec=Spec(type="Square"),
                clips=[
                    Clip(id="c1", kind="Create", start=0.5, duration=1.0),
                    Clip(id="c2", kind="Indicate", start=3.0, duration=1.0),
                ],
                tracks={"scale": [Keyframe(t=2.0, value=1.0), Keyframe(t=5.0, value=2.0)]},
            ),
            Layer(
                id="b", spec=Spec(type="Circle"), clips=[Clip(id="w", kind="Write", start=1.0, duration=1.0)]
            ),
            Layer(id="c", spec=Spec(type="Triangle")),
        ],
    )


def make_view(qt_app, proj: Project) -> TimelineView:
    doc = Document(proj)
    v = TimelineView()
    v.follow_playhead = False  # the playhead moved by a test does not scroll the rows away
    v.resize(1000, 220)
    v.set_document(doc)
    v.show()
    qt_app.processEvents()
    v.messages = []
    v.message.connect(v.messages.append)
    v.emitted = []
    v.clipSelected.connect(lambda *a: v.emitted.append(("clip", *a)))
    v.keySelected.connect(lambda *a: v.emitted.append(("key", *a)))
    v.layerPicked.connect(lambda *a: v.emitted.append(("layer", *a)))
    return v


@pytest.fixture
def view(qt_app):
    v = make_view(qt_app, project())
    yield v
    v.close()


def _send(view, kind, pos: QPointF, modifiers=NO) -> None:
    buttons = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease else Qt.MouseButton.LeftButton
    button = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseMove else Qt.MouseButton.LeftButton
    global_pos = QPointF(view.viewport().mapToGlobal(pos.toPoint()))
    QApplication.sendEvent(view.viewport(), QMouseEvent(kind, pos, global_pos, button, buttons, modifiers))


def press(view, pos, modifiers=NO):
    _send(view, QEvent.Type.MouseButtonPress, pos, modifiers)


def move(view, pos, modifiers=NO):
    _send(view, QEvent.Type.MouseMove, pos, modifiers)


def release(view, pos, modifiers=NO):
    _send(view, QEvent.Type.MouseButtonRelease, pos, modifiers)


def click(view, pos, modifiers=NO):
    press(view, pos, modifiers)
    release(view, pos, modifiers)


def drag(view, start: QPointF, end: QPointF, modifiers=NO) -> None:
    press(view, start, modifiers)
    move(view, QPointF(start.x() + 3, start.y()), modifiers)  # past nothing yet: a few px
    move(view, end, modifiers)
    release(view, end, modifiers)


def key(view, pressed) -> None:
    QApplication.sendEvent(view, QKeyEvent(QEvent.Type.KeyPress, pressed[0], pressed[1]))


def at(view, t: float, layer_id: str, dy: float = ROW_HEIGHT / 2) -> QPointF:
    """A viewport point at time ``t`` on a layer's row (``dy`` below its top)."""
    return QPointF(view.mapFromScene(QPointF(view.scale.x(t), view.row_top(layer_id) + dy)))


def key_point(view, t: float, layer_id: str) -> QPointF:
    return at(view, t, layer_id, KEY_OFFSET)


def starts(view, layer_id: str) -> list[float]:
    return [round(c.start, 4) for c in view.project.layer(layer_id).clips]


def key_times(view, layer_id: str, prop: str = "scale") -> list[float]:
    return [round(k.t, 4) for k in view.project.layer(layer_id).tracks.get(prop, [])]


def pick_three(view) -> None:
    """c1 and w and the key of a at 2 s."""
    click(view, at(view, 1.0, "a"))
    click(view, at(view, 1.5, "b"), SHIFT)
    click(view, key_point(view, 2.0, "a"), CTRL)


# -- picking ---------------------------------------------------------------------------------


def test_shift_and_ctrl_click_add_clips_and_keys_and_the_status_bar_counts_them(view) -> None:
    pick_three(view)
    assert view.picked_clips == {("a", "c1"), ("b", "w")}
    assert view.picked_key_times() == {("a", 2.0, None)}
    assert view.clip_item("a", "c1").selected and view.clip_item("b", "w").selected
    assert not view.clip_item("a", "c2").selected
    assert [k.selected for k in view.key_items() if k.t == 2.0] == [True]
    assert view.messages[-1] == "2 clips, 1 key selected"
    assert view.emitted[-1] == ("key", "a", 2.0)  # the last picked is the primary (Properties)


def test_a_modifier_click_on_a_picked_item_takes_it_out(view) -> None:
    pick_three(view)
    click(view, at(view, 1.5, "b"), CTRL)
    assert view.picked_clips == {("a", "c1")}
    assert view.picked_key_times() == {("a", 2.0, None)}
    assert not view.clip_item("b", "w").selected


def test_a_plain_click_selects_one_item_again(view) -> None:
    pick_three(view)
    click(view, at(view, 3.5, "a"))
    assert view.picked_clips == {("a", "c2")} and view.picked_key_times() == set()


def test_a_plain_click_on_a_picked_item_without_moving_keeps_only_it(view) -> None:
    pick_three(view)
    click(view, at(view, 1.0, "a"))
    assert view.picked_clips == {("a", "c1")} and view.picked_key_times() == set()
    assert view.document.undo_stack.count() == 0


def test_a_selection_made_elsewhere_replaces_the_picks_unless_it_is_one_of_them(view) -> None:
    pick_three(view)
    view.set_selected("b", "w")  # the window echoes the primary: kept
    assert len(view.picked_clips) == 2
    view.set_selected("a", "c2")  # chosen in Properties or the canvas: the picks give way
    assert view.picked_clips == {("a", "c2")} and view.picked_key_times() == set()


def test_a_pick_removed_by_another_edit_leaves_the_picks(view) -> None:
    from manim_studio.core.editing import edits

    pick_three(view)
    view.document.apply(edits.remove_clip(view.project, "b", "w"), "Delete clip")
    assert view.picked_clips == {("a", "c1")} and view.picked_count() == 2


def test_ctrl_a_selects_every_clip_and_key(view) -> None:
    view.setFocus()
    key(view, (Qt.Key.Key_A, CTRL))
    assert view.picked_clips == {("a", "c1"), ("a", "c2"), ("b", "w")}
    assert view.picked_key_times() == {("a", 2.0, None), ("a", 5.0, None)}
    assert view.messages[-1] == "3 clips, 2 keys selected"


def test_escape_clears_the_multi_selection_down_to_the_primary(view) -> None:
    pick_three(view)
    key(view, (Qt.Key.Key_Escape, NO))
    assert view.picked_clips == set() and view.picked_key_times() == {("a", 2.0, None)}
    assert not view.clip_item("a", "c1").selected


def prop_key_point(view, t: float, layer_id: str, prop: str) -> QPointF:
    y = view.prop_row_top(layer_id, prop) + SUB_ROW_HEIGHT / 2
    return QPointF(view.mapFromScene(QPointF(view.scale.x(t), y)))


def test_a_property_rows_key_is_picked_alone_and_moves_with_the_rest(view) -> None:
    view.set_expanded("a", True)
    click(view, at(view, 1.0, "a"))
    click(view, prop_key_point(view, 5.0, "a", "scale"), CTRL)
    assert view.picked_key_times() == {("a", 5.0, "scale")}
    shown = [k for k in view.key_items() if k.prop == "scale" and k.t == 5.0]
    assert [k.selected for k in shown] == [True]
    drag(view, at(view, 1.0, "a"), at(view, 2.0, "a"), ALT)
    assert starts(view, "a") == [1.5, 3.0] and key_times(view, "a") == [2.0, 6.0]
    click(view, prop_key_point(view, 6.0, "a", "scale"), CTRL)  # out again
    assert view.picked_key_times() == set()


def test_escape_drops_a_rubber_band_being_drawn(view) -> None:
    click(view, at(view, 3.5, "a"))
    start = at(view, 0.2, "b", 2)
    press(view, start)
    move(view, QPointF(start.x() + 150, start.y() + 10))
    assert ("b", "w") in view.picked_clips
    key(view, (Qt.Key.Key_Escape, NO))
    assert view.rubber is None and view.picked_clips == {("a", "c2")}
    release(view, QPointF(start.x() + 150, start.y() + 10))
    assert view.picked_clips == {("a", "c2")}


# -- the rubber band -------------------------------------------------------------------------


def test_a_rubber_band_from_empty_space_picks_every_clip_and_key_it_touches(view) -> None:
    start = at(view, 0.2, view.rows()[0].id, 2)  # the top row's empty space
    end = at(view, 2.1, "a", ROW_HEIGHT - 2)  # down to the bottom of a's row, past its key at 2 s
    drag(view, start, end)
    assert view.picked_clips == {("a", "c1"), ("b", "w")}
    assert view.picked_key_times() == {("a", 2.0, None)}
    assert view.rubber is None  # gone with the release
    assert view.document.undo_stack.count() == 0


def test_a_rubber_band_with_shift_adds_to_the_picks(view) -> None:
    click(view, at(view, 3.5, "a"))
    drag(view, at(view, 0.2, "b", 2), at(view, 1.9, "b", ROW_HEIGHT - 2), SHIFT)
    assert view.picked_clips == {("a", "c2"), ("b", "w")}


def test_a_rubber_band_without_shift_starts_over(view) -> None:
    click(view, at(view, 3.5, "a"))
    drag(view, at(view, 0.2, "b", 2), at(view, 1.9, "b", ROW_HEIGHT - 2))
    assert view.picked_clips == {("b", "w")}


def test_a_click_on_empty_space_without_moving_still_picks_the_row(view) -> None:
    click(view, at(view, 6.0, "c"))
    assert ("layer", "c", False) in view.emitted
    assert view.rubber is None


def test_the_rubber_band_is_drawn_while_dragging(view) -> None:
    start = at(view, 0.2, "b", 2)
    press(view, start)
    move(view, QPointF(start.x() + 20, start.y() + 20))
    assert view.rubber is not None and view.picked_clips == set()
    move(view, QPointF(start.x() + 120, start.y() + 20))  # to 1.2 s: over w
    assert view.picked_clips == {("b", "w")}  # picked as it grows
    release(view, QPointF(start.x() + 120, start.y() + 20))


# -- dragging the picks ----------------------------------------------------------------------


def test_dragging_one_picked_item_moves_them_all_in_one_undo_step(view) -> None:
    pick_three(view)
    drag(view, at(view, 1.0, "a"), at(view, 2.0, "a"), ALT)  # c1 one second later, no snapping
    assert starts(view, "a") == [1.5, 3.0]  # c2 was not picked
    assert starts(view, "b") == [2.0]
    assert key_times(view, "a") == [3.0, 5.0]
    stack = view.document.undo_stack
    assert stack.count() == 1 and stack.undoText() == "Move selection"
    assert view.picked_key_times() == {("a", 3.0, None)}  # the moved key stays picked
    assert view.picked_clips == {("a", "c1"), ("b", "w")}
    assert view.emitted[-1] == ("clip", "a", "c1")  # the dragged item is the primary
    stack.undo()
    assert starts(view, "a") == [0.5, 3.0] and starts(view, "b") == [1.0]
    assert key_times(view, "a") == [2.0, 5.0]
    assert view.picked_key_times() == set()  # the key it picked at 3 s is gone with the undo


def test_dragging_a_picked_key_moves_the_clips_with_it(view) -> None:
    pick_three(view)
    drag(view, key_point(view, 2.0, "a"), key_point(view, 2.5, "a"), ALT)
    assert starts(view, "b") == [1.5] and key_times(view, "a") == [2.5, 5.0]
    assert view.emitted[-1] == ("key", "a", 2.5)  # the primary key moved: Properties follows it
    assert view.selected_key == ("a", 2.5)


def test_a_group_drag_snaps_from_the_dragged_item_but_not_to_the_picks(view) -> None:
    pick_three(view)
    view.set_playhead(2.6)
    # c1 (0.5-1.5) dragged by about 1.07 s: its end comes to ~2.57, 3 px from the playhead
    drag(view, at(view, 1.0, "a"), at(view, 2.07, "a"))
    assert starts(view, "a")[0] == pytest.approx(1.6)  # its end on the playhead
    assert starts(view, "b") == [pytest.approx(2.1)]
    view.document.undo_stack.undo()
    pick_three(view)  # the undo put the key back where it was not picked
    view.set_playhead(9.0)
    # w starts at 1.0 and a's key sits at 2.0: c1 dragged to 1.05-2.05 (6 px from each) snaps to
    # neither, both being picked (they move with it)
    drag(view, at(view, 1.0, "a"), at(view, 1.55, "a"))
    assert starts(view, "a")[0] == pytest.approx(1.05, abs=1 / FPS)
    assert starts(view, "a")[0] != pytest.approx(1.0)


def test_a_group_drag_is_clamped_at_zero_for_all_of_it(view) -> None:
    pick_three(view)
    grab = at(view, 1.0, "a")
    drag(view, grab, QPointF(grab.x() - 600, grab.y()), ALT)  # far before 0 s
    assert starts(view, "a") == [0.0, 3.0]  # c1 stopped at 0: everything moved by -0.5
    assert starts(view, "b") == [0.5] and key_times(view, "a") == [1.5, 5.0]
    assert view.picked_key_times() == {("a", 1.5, None)}  # the picks followed the clamped move


def test_a_refused_group_drag_previews_nothing_and_says_why(view) -> None:
    click(view, at(view, 1.0, "a"))
    click(view, at(view, 1.5, "b"), SHIFT)
    press(view, at(view, 1.0, "a"))
    move(view, at(view, 3.0, "a"), ALT)  # c1 onto c2, which is not picked
    view.apply_pending()
    assert starts(view, "a") == [0.5, 3.0] and starts(view, "b") == [1.0]
    assert view.messages and "overlap" in view.messages[-1].lower()
    release(view, at(view, 3.0, "a"), ALT)
    assert view.document.undo_stack.count() == 0


def test_dropping_a_selection_past_the_end_grows_the_scene(view) -> None:
    view.set_selected(None, None)
    key(view, (Qt.Key.Key_A, CTRL))
    view.scale = view.scale.__class__(px_per_second=60.0)  # 10 s in 600 px: room to drag past the end
    view.sync()
    drag(view, key_point(view, 5.0, "a"), key_point(view, 11.0, "a"), ALT)
    assert key_times(view, "a") == [8.0, 11.0]
    assert view.project.canvas.duration >= 11.0


def test_a_lifetime_cut_by_the_drop_is_warned_about(qt_app) -> None:
    proj = project()
    held = proj.layer("a").model_copy(update={"lifetime": Lifetime(out=5.0)})
    v = make_view(qt_app, proj.model_copy(update={"layers": [held, *proj.layers[1:]]}))
    try:
        click(v, at(v, 3.5, "a"))
        click(v, at(v, 1.5, "b"), SHIFT)
        drag(v, at(v, 3.5, "a"), at(v, 5.5, "a"), ALT)  # c2 ends at 6, after Disappears at 5
        assert starts(v, "a")[1] == pytest.approx(5.0)
        assert "lifetime ends before its animation" in v.messages[-1]
    finally:
        v.close()


# -- deleting --------------------------------------------------------------------------------


def test_delete_removes_every_pick_in_one_undo_step(view) -> None:
    pick_three(view)
    view.setFocus()
    key(view, (Qt.Key.Key_Delete, NO))
    assert starts(view, "a") == [3.0] and starts(view, "b") == []
    assert key_times(view, "a") == [5.0]
    stack = view.document.undo_stack
    assert stack.count() == 1 and stack.undoText() == "Delete selection"
    assert view.picked_clips == set() and view.picked_key_times() == set()
    stack.undo()
    assert starts(view, "a") == [0.5, 3.0] and key_times(view, "a") == [2.0, 5.0]


# -- moving whole layers by their lifetime band ----------------------------------------------


def test_dragging_a_selected_rows_band_moves_those_layers_whole(view) -> None:
    view.set_selected("b", None)
    view.set_selected_layers(("a", "b"))
    grab = at(view, 2.5, "a", 6)  # a's band, between its clips and above its keys
    move(view, grab)
    assert view.viewport().cursor().shape() == Qt.CursorShape.SizeAllCursor
    drag(view, grab, at(view, 3.5, "a", 6), ALT)
    assert starts(view, "a") == [1.5, 4.0] and key_times(view, "a") == [3.0, 6.0]
    assert starts(view, "b") == [2.0]
    stack = view.document.undo_stack
    assert stack.count() == 1 and stack.undoText() == "Move layers"


def test_one_selected_row_drags_alone(view) -> None:
    view.set_selected("b", None)
    view.set_selected_layers(("b",))
    drag(view, at(view, 3.0, "b", 6), at(view, 4.0, "b", 6), ALT)
    assert starts(view, "b") == [2.0] and starts(view, "a") == [0.5, 3.0]


def test_the_band_of_a_row_not_selected_is_empty_space(view) -> None:
    view.set_selected("b", None)
    view.set_selected_layers(("b",))
    drag(view, at(view, 2.5, "a", 6), at(view, 3.5, "a", 6), ALT)
    assert starts(view, "a") == [0.5, 3.0]  # not moved: a rubber band
    assert view.document.undo_stack.count() == 0


# -- in the window -----------------------------------------------------------------------------


@pytest.fixture
def window(qt_app, tmp_path):
    from manim_studio.ui.main_window import MainWindow

    path = tmp_path / "multi.json"
    path.write_text(project().model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.resize(1200, 760)
    win.show()
    win.load(path)
    qt_app.processEvents()
    win.timeline.follow_playhead = False
    yield win
    win.close()


def test_in_the_window_properties_shows_the_primary_and_the_picks_stay(window) -> None:
    tl = window.timeline
    click(tl, at(tl, 1.0, "a"))
    click(tl, at(tl, 1.5, "b"), SHIFT)
    assert tl.picked_clips == {("a", "c1"), ("b", "w")}  # the shared selection's echo kept them
    assert (window.selection.layer_id, window.selection.clip_id) == ("b", "w")
    assert (window.properties.layer_id, window.properties.clip_id) == ("b", "w")
    assert window.statusBar().currentMessage() == "2 clips selected"
    window.selection.set("a", "c2")  # chosen elsewhere: the picks give way
    assert tl.picked_clips == {("a", "c2")}


def test_in_the_window_dragging_a_picked_key_keeps_every_pick(window) -> None:
    """The moved key leaves the shared selection mid-drag (no key at its old time): the picks stay."""
    tl = window.timeline
    click(tl, key_point(tl, 2.0, "a"))
    click(tl, at(tl, 1.5, "b"), SHIFT)
    click(tl, key_point(tl, 2.0, "a"), CTRL)
    click(tl, key_point(tl, 2.0, "a"), CTRL)  # out and in again: the key is the primary
    drag(tl, key_point(tl, 2.0, "a"), key_point(tl, 2.5, "a"), ALT)
    assert key_times(tl, "a") == [2.5, 5.0] and starts(tl, "b") == [1.5]
    assert tl.picked_clips == {("b", "w")} and tl.picked_key_times() == {("a", 2.5, None)}
    assert (window.selection.layer_id, window.selection.key_time) == ("a", 2.5)


def test_in_the_window_selected_layers_drag_whole_by_a_band(window) -> None:
    tl = window.timeline
    window.selection.set_layers(["a", "b"])
    drag(tl, at(tl, 2.5, "a", 6), at(tl, 3.5, "a", 6), ALT)
    assert starts(tl, "a") == [1.5, 4.0] and starts(tl, "b") == [2.0]
    assert window.document.undo_stack.undoText() == "Move layers"
    assert window.selection.layer_ids == ("a", "b")


def test_in_the_window_shift_timing_moves_the_picks(window) -> None:
    tl = window.timeline
    click(tl, at(tl, 1.0, "a"))
    click(tl, key_point(tl, 5.0, "a"), CTRL)
    window.ask_shift = lambda: 1.0
    window.shift_selection()
    assert starts(tl, "a") == [1.5, 3.0] and key_times(tl, "a") == [2.0, 6.0]
