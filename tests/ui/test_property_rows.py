"""Property rows on the timeline (P7.3, ADR 0047): an object's row expands into one sub-row per
property it can key, with the value at the playhead, a diamond that keys that property alone, and
that property's keys on the one time axis - dragged, selected, deleted and eased one property at a
time. Driven by real mouse events, like ``test_timeline_view``."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication

from manim_studio.core.schema import Canvas, Clip, Easing, Keyframe, Layer, Project, Spec
from manim_studio.ui.document import Document
from manim_studio.ui.timeline.model import quantize
from manim_studio.ui.timeline.view import (
    HEADER_WIDTH,
    KEY_BUTTON_X,
    KEY_OFFSET,
    ROW_HEIGHT,
    RULER_HEIGHT,
    SUB_ROW_HEIGHT,
    TWIRL_X,
    WIDE_HEADER_WIDTH,
    KeyItem,
    PropKeyItem,
    TimelineView,
    format_value,
)
from ui.test_acceptance_v1 import menu_action as action

pytestmark = pytest.mark.ui
FPS = 30


def project() -> Project:
    return Project(
        canvas=Canvas(duration=6.0, fps=FPS),
        layers=[
            Layer(
                id="a",
                spec=Spec(type="Square"),
                clips=[Clip(id="c1", kind="Create", start=0.5, duration=1.0)],
                tracks={
                    "position": [Keyframe(t=1.0, value=(0.0, 0.0)), Keyframe(t=2.5, value=(2.0, 0.0))],
                    "rotation": [Keyframe(t=1.0, value=30.0), Keyframe(t=3.0, value=90.0)],
                },
            ),
            Layer(
                id="b", spec=Spec(type="Circle"), clips=[Clip(id="f", kind="FadeIn", start=0.0, duration=1.0)]
            ),
            Layer(id="axes", spec=Spec(type="Axes")),
            Layer(id="g", parent_id="axes", spec=Spec(type="Graph", params={"expression": "sin(x)"})),
        ],
    )


@pytest.fixture
def view(qt_app):
    doc = Document(project())
    v = TimelineView()
    v.resize(1000, 400)
    v.set_document(doc)
    v.show()
    qt_app.processEvents()
    yield v
    v.close()


def _send(widget, kind: QEvent.Type, pos: QPointF, modifiers=Qt.KeyboardModifier.NoModifier) -> None:
    buttons = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease else Qt.MouseButton.LeftButton
    button = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseMove else Qt.MouseButton.LeftButton
    global_pos = QPointF(widget.mapToGlobal(pos.toPoint()))
    QApplication.sendEvent(widget, QMouseEvent(kind, pos, global_pos, button, buttons, modifiers))


def press(view, pos, **kw):
    _send(view.viewport(), QEvent.Type.MouseButtonPress, pos, **kw)


def move(view, pos, **kw):
    _send(view.viewport(), QEvent.Type.MouseMove, pos, **kw)


def release(view, pos, **kw):
    _send(view.viewport(), QEvent.Type.MouseButtonRelease, pos, **kw)


def click_header(view: TimelineView, x: float, scene_y: float, **kw) -> None:
    pos = QPointF(x, scene_y - view.verticalScrollBar().value())
    _send(view.header, QEvent.Type.MouseButtonPress, pos, **kw)
    _send(view.header, QEvent.Type.MouseButtonRelease, pos, **kw)


def twirl(view: TimelineView, layer_id: str, **kw) -> None:
    click_header(view, TWIRL_X, view.row_top(layer_id) + ROW_HEIGHT / 2, **kw)


def sub_y(view: TimelineView, layer_id: str, prop: str) -> float:
    """The middle of a property's sub-row, in scene coordinates."""
    return view.prop_row_top(layer_id, prop) + SUB_ROW_HEIGHT / 2


def sub_point(view: TimelineView, t: float, layer_id: str, prop: str) -> QPointF:
    return QPointF(view.mapFromScene(QPointF(view.scale.x(t), sub_y(view, layer_id, prop))))


def key_delete(view) -> None:
    event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Delete, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(view, event)


def keys_of(view, layer_id: str = "a") -> dict:
    return {prop: [k.t for k in track] for prop, track in view.project.layer(layer_id).tracks.items()}


def prop_keys(view) -> list[tuple[str, str, float]]:
    return sorted((i.layer_id, i.prop, i.t) for i in view.key_items() if isinstance(i, PropKeyItem))


# -- expanding --------------------------------------------------------------------------


def test_rows_start_collapsed_exactly_as_before(view) -> None:
    assert view.expanded == set()
    for row, layer in enumerate(view.rows()):
        assert view.row_top(layer.id) == RULER_HEIGHT + row * ROW_HEIGHT
    assert prop_keys(view) == []
    assert len(view.key_items()) == 3  # one diamond per key time on the object's row


def test_the_twirl_expands_a_row_into_one_sub_row_per_keyable_property(view, qt_app) -> None:
    assert view.row_of("b") < view.row_of("a")  # b is in front: above a
    below = view.clip_item("a", "c1").rect().y()
    height = view.scene().sceneRect().height()
    twirl(view, "b")
    assert view.expanded == {"b"}
    assert view.sub_rows("b") == ("position", "scale", "rotation", "opacity")
    tops = [view.prop_row_top("b", p) for p in view.sub_rows("b")]
    assert tops == [view.row_top("b") + ROW_HEIGHT + i * SUB_ROW_HEIGHT for i in range(4)]
    grown = 4 * SUB_ROW_HEIGHT
    assert view.clip_item("a", "c1").rect().y() == below + grown  # the rows under it move down
    assert view.scene().sceneRect().height() == height + grown
    assert view.header_width == WIDE_HEADER_WIDTH and view.header.width() == WIDE_HEADER_WIDTH
    assert view.document.undo_stack.count() == 0  # editor state, not an edit
    view.header.grab()  # paints names, values and diamonds
    twirl(view, "b")
    assert view.expanded == set() and view.clip_item("a", "c1").rect().y() == below
    assert view.header_width == HEADER_WIDTH  # collapsed: the timeline as it always was


def test_alt_click_on_a_name_expands_it_too(view) -> None:
    picked = []
    view.layerPicked.connect(lambda *a: picked.append(a))
    click_header(view, 60, view.row_top("b") + ROW_HEIGHT / 2, modifiers=Qt.KeyboardModifier.AltModifier)
    assert view.expanded == {"b"} and picked == []


def test_a_locked_child_has_an_opacity_row_only(view) -> None:
    below = view.row_top("b")
    view.set_expanded("g", True)
    assert view.sub_rows("g") == ("opacity",)
    assert view.row_top("b") == below + SUB_ROW_HEIGHT  # one property row only
    with pytest.raises(ValueError):
        view.prop_row_top("g", "position")


def test_expanded_rows_are_dropped_with_the_project(view) -> None:
    view.set_expanded("a", True)
    click_header(view, 60, view.prop_row_top("a", "scale") + 2)
    view.document.replace(project())  # File > Open
    assert view.expanded == set() and view.selected_props == ()


# -- the sub-rows' keys -------------------------------------------------------------------


def test_each_sub_row_shows_its_own_keys(view) -> None:
    view.set_expanded("a", True)
    assert prop_keys(view) == [
        ("a", "position", 1.0),
        ("a", "position", 2.5),
        ("a", "rotation", 1.0),
        ("a", "rotation", 3.0),
    ]
    collapsed = [i for i in view.key_items() if not isinstance(i, PropKeyItem)]
    assert sorted(i.t for i in collapsed) == [1.0, 2.5, 3.0]  # the object's row is unchanged
    item = next(i for i in view.key_items() if (i.prop, i.t) == ("rotation", 3.0))
    assert item.pos().y() == pytest.approx(sub_y(view, "a", "rotation"))


def test_dragging_a_sub_row_key_retimes_that_property_only(view, qt_app) -> None:
    view.set_expanded("a", True)
    start = sub_point(view, 1.0, "a", "rotation")
    end = QPointF(start.x() + view.scale.px_per_second * 0.5, start.y())
    press(view, start)
    move(view, end)
    qt_app.processEvents()
    release(view, end)
    assert keys_of(view) == {"position": [1.0, 2.5], "rotation": [pytest.approx(1.5), 3.0]}
    assert view.document.undo_stack.count() == 1
    assert view.document.undo_stack.undoText() == "Move rotation key"
    assert view.selected_key == ("a", pytest.approx(1.5)) and view.selected_key_prop == "rotation"
    view.document.undo_stack.undo()
    assert keys_of(view) == {"position": [1.0, 2.5], "rotation": [1.0, 3.0]}


def test_a_sub_row_key_stops_before_its_own_neighbour_only(view, qt_app) -> None:
    view.set_expanded("a", True)
    start = sub_point(view, 1.0, "a", "rotation")
    end = QPointF(start.x() + view.scale.px_per_second * 2.5, start.y())
    press(view, start)
    move(view, end)
    release(view, end)
    assert keys_of(view)["rotation"] == [pytest.approx(3.0 - 1 / FPS), 3.0]  # past position's 2.5 s key
    assert keys_of(view)["position"] == [1.0, 2.5]


def test_sub_row_keys_snap_like_every_drag(view, qt_app) -> None:
    view.set_expanded("a", True)
    view.set_playhead(2.0)
    start = sub_point(view, 1.0, "a", "rotation")
    near = QPointF(view.mapFromScene(QPointF(view.scale.x(2.0) + 5, 0)).x(), start.y())
    press(view, start)
    move(view, near)
    release(view, near)
    assert keys_of(view)["rotation"][0] == pytest.approx(2.0)  # onto the playhead
    view.document.undo_stack.undo()
    press(view, start)
    move(view, near, modifiers=Qt.KeyboardModifier.AltModifier)
    release(view, near, modifiers=Qt.KeyboardModifier.AltModifier)
    assert keys_of(view)["rotation"][0] == pytest.approx(quantize(2.0 + 5 / view.scale.px_per_second, FPS))


def test_delete_removes_the_selected_sub_row_key_only(view) -> None:
    view.set_expanded("a", True)
    selected = []
    view.keySelected.connect(lambda *a: selected.append(a))
    pos = sub_point(view, 1.0, "a", "position")
    press(view, pos)
    release(view, pos)
    assert selected == [("a", 1.0)] and view.selected_key_prop == "position"
    assert view.document.undo_stack.count() == 0
    key_delete(view)
    assert keys_of(view) == {"position": [2.5], "rotation": [1.0, 3.0]}
    assert view.document.undo_stack.count() == 1


def test_the_object_row_still_deletes_every_key_at_that_time(view) -> None:
    view.set_expanded("a", True)
    pos = QPointF(view.mapFromScene(QPointF(view.scale.x(1.0), view.row_top("a") + KEY_OFFSET)))
    press(view, pos)
    release(view, pos)
    assert view.selected_key == ("a", 1.0) and view.selected_key_prop is None
    key_delete(view)
    assert keys_of(view) == {"position": [2.5], "rotation": [3.0]}


def test_right_click_a_sub_row_key_deletes_or_eases_that_property(view) -> None:
    view.set_expanded("a", True)
    menu = view.context_menu(sub_point(view, 1.0, "a", "rotation"))
    action(menu, "ease out back").trigger()
    layer = view.project.layer("a")
    assert layer.tracks["rotation"][0].ease == Easing(name="ease_out_back")
    assert layer.tracks["position"][0].ease != Easing(name="ease_out_back")
    action(view.context_menu(sub_point(view, 1.0, "a", "rotation")), "Delete rotation key at 1 s").trigger()
    assert keys_of(view) == {"position": [1.0, 2.5], "rotation": [3.0]}
    assert view.document.undo_stack.count() == 2
    menu = view.context_menu(sub_point(view, 3.0, "a", "rotation"))  # the last key: no motion follows
    assert not any("ease" in a.text().lower() and a.isEnabled() for a in menu.actions() if a.menu() is None)


def test_right_click_an_empty_sub_row_keys_that_property(view) -> None:
    view.set_expanded("a", True)
    view.set_playhead(2.0)
    action(view.context_menu(sub_point(view, 4.5, "a", "scale")), "Add scale key at playhead").trigger()
    assert keys_of(view)["scale"] == [2.0]
    assert keys_of(view)["position"] == [1.0, 2.5]


# -- the sub-row's header ---------------------------------------------------------------------


def test_the_diamond_keys_that_property_at_the_playhead_and_removes_it_again(view) -> None:
    view.set_expanded("a", True)
    view.set_playhead(2.0)
    y = sub_y(view, "a", "scale")
    click_header(view, KEY_BUTTON_X, y)
    assert view.project.layer("a").tracks["scale"][0].t == 2.0
    assert view.project.layer("a").tracks["scale"][0].value == 1.0  # holds the value played there
    assert keys_of(view)["position"] == [1.0, 2.5]  # nothing else keyed
    assert view.selected_key == ("a", 2.0) and view.selected_key_prop == "scale"
    assert view.document.undo_stack.undoText() == "Add scale key"
    click_header(view, KEY_BUTTON_X, y)  # a key there: removed
    assert "scale" not in view.project.layer("a").tracks
    assert view.document.undo_stack.count() == 2


def test_the_header_shows_each_value_at_the_playhead(view) -> None:
    view.set_playhead(1.0)
    assert view.prop_value("a", "rotation") == format_value("rotation", 30.0) == "30°"
    assert view.prop_value("a", "position") == format_value("position", (0.0, 0.0)) == "0, 0"
    assert format_value("opacity", 0.5) == "50%" and format_value("scale", 1.25) == "1.25"
    view.set_playhead(2.0)
    assert view.prop_value("a", "rotation") == "60°"  # between its keys
    assert view.has_key_at_playhead("a", "rotation") is False
    view.set_playhead(3.0)
    assert view.has_key_at_playhead("a", "rotation") is True


def test_moving_the_playhead_repaints_the_values(view) -> None:
    view.set_expanded("a", True)
    painted = []
    view.header.update = lambda *a: painted.append(1)
    view.set_playhead(2.0)
    assert painted


# -- choosing properties for the graph ----------------------------------------------------------


def test_clicking_a_sub_row_name_chooses_that_property(view) -> None:
    view.set_expanded("a", True)
    view.set_expanded("b", True)
    picked, chosen = [], []
    view.layerPicked.connect(lambda *a: picked.append(a))
    view.propsSelected.connect(lambda: chosen.append((view.prop_layer, view.selected_props)))
    click_header(view, 60, sub_y(view, "a", "rotation"))
    assert (view.prop_layer, view.selected_props) == ("a", ("rotation",))
    assert picked == [("a", False)]  # the object is selected with it
    click_header(view, 60, sub_y(view, "a", "position"), modifiers=Qt.KeyboardModifier.ShiftModifier)
    assert view.selected_props == ("rotation", "position")
    click_header(view, 60, sub_y(view, "a", "rotation"), modifiers=Qt.KeyboardModifier.ControlModifier)
    assert view.selected_props == ("position",)  # Ctrl takes one out again
    click_header(view, 60, sub_y(view, "b", "scale"), modifiers=Qt.KeyboardModifier.ShiftModifier)
    assert (view.prop_layer, view.selected_props) == ("b", ("scale",))  # another object: starts over
    assert len(chosen) == 4
    assert view.document.undo_stack.count() == 0


def test_another_object_selected_elsewhere_drops_the_chosen_properties(view) -> None:
    view.set_expanded("a", True)
    click_header(view, 60, sub_y(view, "a", "rotation"))
    view.set_selected("a", None)  # the same object: kept
    assert view.selected_props == ("rotation",)
    view.set_selected("b", None)
    assert view.selected_props == () and view.prop_layer is None


def test_property_rows_are_banded_and_the_chosen_one_stands_out(view, qt_app) -> None:
    def colour(prop: str):
        point = sub_point(view, 5.5, "a", prop).toPoint()  # nothing drawn there but the band
        return view.viewport().grab().toImage().pixelColor(point)

    from manim_studio.ui.timeline.view import BACKGROUND

    view.set_expanded("a", True)
    qt_app.processEvents()
    assert colour("scale").rgb() != BACKGROUND.rgb()  # a band over the timeline's background
    click_header(view, 60, sub_y(view, "a", "rotation"))
    qt_app.processEvents()
    assert colour("rotation") != colour("scale")


def test_empty_space_in_a_sub_row_chooses_it_too(view) -> None:
    view.set_expanded("a", True)
    pos = sub_point(view, 5.0, "a", "opacity")
    press(view, pos)
    release(view, pos)
    assert view.selected_props == ("opacity",)


def test_collapsed_rows_draw_no_extra_items(view) -> None:
    before = len(view.scene().items())
    view.set_expanded("a", True)
    view.set_expanded("a", False)
    assert len(view.scene().items()) == before
    assert all(type(i) is KeyItem for i in view.key_items())
