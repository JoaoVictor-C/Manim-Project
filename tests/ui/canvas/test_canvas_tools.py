"""Selecting and moving objects on the canvas (S3.4-S3.5, ADR 0016), with real input events."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication

from manim_studio.core.engine.evaluator import layer_transform
from manim_studio.core.model.schema import Canvas, Clip, Keyframe, Layer, Project, Spec, Transform2D
from manim_studio.ui.main_window import MainWindow

pytestmark = pytest.mark.ui

FILLED = {"fill": "#3b82f6", "fill_opacity": 0.8}
FPS = 30


def project() -> Project:
    return Project(
        canvas=Canvas(width_px=640, height_px=360, fps=FPS, duration=4.0),
        layers=[
            Layer(id="big", spec=Spec(type="Square", params={"side_length": 4}, style=FILLED)),
            Layer(
                id="dot",
                spec=Spec(type="Circle", params={"radius": 0.5}, style=FILLED),
                base=Transform2D(position=(1.0, 0.0)),
            ),
            Layer(
                id="keyed",
                spec=Spec(type="Square", params={"side_length": 1}, style=FILLED),
                tracks={"position": [Keyframe(t=0, value=(-5.0, 2.0)), Keyframe(t=2, value=(-3.0, 2.0))]},
            ),
            Layer(
                id="src",
                spec=Spec(type="Triangle", style=FILLED),
                base=Transform2D(position=(5.0, -2.0)),
                clips=[Clip(id="m", kind="Transform", start=1.0, duration=1.0, to_layer="dst")],
            ),
            Layer(id="dst", spec=Spec(type="Star", style=FILLED), base=Transform2D(position=(5.0, -2.0))),
            Layer(
                id="tiny",
                spec=Spec(type="Circle", params={"radius": 0.15}, style=FILLED),
                base=Transform2D(position=(-5.0, -3.0)),
            ),
        ],
    )


@pytest.fixture
def window(qt_app, tmp_path):
    path = tmp_path / "scene.json"
    path.write_text(project().model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.resize(1100, 800)
    win.show()
    win.load(path)
    qt_app.processEvents()
    win.messages = []
    win.move_tool.message.connect(win.messages.append)
    yield win
    win.close()


def px(window, x: float, y: float) -> QPointF:
    """Manim units -> canvas widget pixels."""
    return window.canvas.units_transform().map(QPointF(x, y))


def mouse(window, kind, pos: QPointF, modifiers=Qt.KeyboardModifier.NoModifier) -> None:
    canvas = window.canvas
    button = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseMove else Qt.MouseButton.LeftButton
    buttons = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease else Qt.MouseButton.LeftButton
    global_pos = QPointF(canvas.mapToGlobal(pos.toPoint()))
    QApplication.sendEvent(canvas, QMouseEvent(kind, pos, global_pos, button, buttons, modifiers))


def click(window, pos, **kw) -> None:
    mouse(window, QEvent.Type.MouseButtonPress, pos, **kw)
    mouse(window, QEvent.Type.MouseButtonRelease, pos, **kw)


def drag(window, start: QPointF, end: QPointF, qt_app, modifiers=Qt.KeyboardModifier.NoModifier) -> None:
    mouse(window, QEvent.Type.MouseButtonPress, start, modifiers)
    for f in (0.3, 0.7, 1.0):
        mouse(window, QEvent.Type.MouseMove, start + (end - start) * f, modifiers)
        qt_app.processEvents()
    mouse(window, QEvent.Type.MouseButtonRelease, end, modifiers)


def key(window, k, modifiers=Qt.KeyboardModifier.NoModifier, repeat=False) -> None:
    QApplication.sendEvent(window.canvas, QKeyEvent(QEvent.Type.KeyPress, k, modifiers, "", repeat))


def base(window, layer_id: str) -> tuple[float, float]:
    return window.project.layer(layer_id).base.position


# -- selection ---------------------------------------------------------------------


def test_click_selects_the_front_most_object_and_outlines_it(window) -> None:
    click(window, px(window, 1.0, 0.0))  # the dot, in front of the big square
    assert window.selection.layer_id == "dot"
    assert window.layers.selected_id() == "dot"
    assert window.canvas.outline is not None
    assert window.canvas.outline.bounds.center().x() == pytest.approx(1.0, abs=0.01)
    assert window.document.undo_stack.count() == 0  # a click is not an edit


def test_stage_text_tool_places_an_object_at_the_click_and_returns_to_select(window) -> None:
    window.stage_tool_buttons["text"].click()
    pos = px(window, -2.0, 1.0)
    click(window, pos)

    text = next(layer for layer in window.project.layers if layer.spec.type == "Text")
    assert text.base.position == pytest.approx((-2.0, 1.0), abs=0.02)
    assert window.canvas.interaction_mode == "select"
    assert window.stage_tool_buttons["select"].isChecked()


def test_anchor_tool_drags_the_selected_objects_anchor(window, qt_app) -> None:
    window.selection.select_layer("dot")
    window.refresh()
    window.stage_tool_buttons["anchor"].click()
    before = window.project.layer("dot").base.anchor
    start = px(window, 0.0, 0.0)
    drag(window, start, start + QPointF(35, 20), qt_app)

    assert window.project.layer("dot").base.anchor != before


def test_click_on_nothing_clears_the_selection(window) -> None:
    click(window, px(window, 1.0, 0.0))
    click(window, px(window, -6.0, -3.5))
    assert window.selection.layer_id is None and window.canvas.outline is None


def test_alt_click_cycles_to_the_object_behind(window) -> None:
    pos = px(window, 1.0, 0.0)
    click(window, pos)
    click(window, pos, modifiers=Qt.KeyboardModifier.AltModifier)
    assert window.selection.layer_id == "big"
    click(window, pos, modifiers=Qt.KeyboardModifier.AltModifier)
    assert window.selection.layer_id == "dot"  # wraps around


def test_a_press_inside_the_selected_box_keeps_the_selection(window, qt_app) -> None:
    window.selection.set("big")
    drag(window, px(window, 1.0, 0.0), px(window, 1.5, 0.0), qt_app)
    assert window.selection.layer_id == "big"  # not the dot in front
    assert base(window, "big") == pytest.approx((0.5, 0.0), abs=0.02)


# -- moving ------------------------------------------------------------------------


def test_drag_moves_the_base_position_as_one_undo_step(window, qt_app) -> None:
    drag(window, px(window, 1.0, 0.0), px(window, 2.0, 0.5), qt_app)
    assert base(window, "dot") == pytest.approx((2.0, 0.5), abs=0.02)
    stack = window.document.undo_stack
    assert stack.count() == 1 and stack.undoText() == "Move layer"
    stack.undo()
    assert base(window, "dot") == (1.0, 0.0)
    stack.redo()
    assert base(window, "dot") == pytest.approx((2.0, 0.5), abs=0.02)


def test_shift_locks_the_dominant_axis(window, qt_app) -> None:
    drag(window, px(window, 1.0, 0.0), px(window, 2.0, 0.3), qt_app, Qt.KeyboardModifier.ShiftModifier)
    assert base(window, "dot") == pytest.approx((2.0, 0.0), abs=0.02)


def test_escape_cancels_a_drag(window, qt_app) -> None:
    mouse(window, QEvent.Type.MouseButtonPress, px(window, 1.0, 0.0))
    mouse(window, QEvent.Type.MouseMove, px(window, 2.0, 0.0))
    qt_app.processEvents()
    key(window, Qt.Key.Key_Escape)
    mouse(window, QEvent.Type.MouseButtonRelease, px(window, 2.0, 0.0))
    assert base(window, "dot") == (1.0, 0.0)
    assert window.document.undo_stack.count() == 0


def test_a_keyframed_layer_gets_a_key_at_the_playhead_frame(window, qt_app) -> None:
    window.seek(1.01)  # between frames 30 and 31
    at = layer_transform(window.project.layer("keyed"), 1.0).position  # (-4, 2)
    drag(window, px(window, *at), px(window, at[0], at[1] - 1.0), qt_app)
    assert window.t == pytest.approx(1.0)  # snapped onto the frame first
    keys = window.project.layer("keyed").tracks["position"]
    assert [k.t for k in keys] == [0, pytest.approx(1.0), 2]
    assert keys[1].value == pytest.approx((-4.0, 1.0), abs=0.02)
    assert base(window, "keyed") == (0.0, 0.0)  # the base is untouched
    # the object is drawn where it was dropped
    assert layer_transform(window.project.layer("keyed"), window.t).position == pytest.approx(
        (-4, 1), abs=0.02
    )


def test_a_morphing_layer_cannot_be_dragged(window, qt_app) -> None:
    window.seek(1.5)  # src morphs into dst over 1-2 s
    drag(window, px(window, 5.0, -2.0), px(window, 4.0, -2.0), qt_app)
    assert window.selection.layer_id == "src"  # it is selected, but not moved
    assert base(window, "src") == (5.0, -2.0)
    assert window.document.undo_stack.count() == 0
    assert window.messages and "morph" in window.messages[-1]


# -- nudging -----------------------------------------------------------------------


def test_arrow_keys_nudge_by_pixels(window) -> None:
    window.selection.set("dot")
    ppu = window.canvas.px_per_unit()
    key(window, Qt.Key.Key_Right)
    key(window, Qt.Key.Key_Up, Qt.KeyboardModifier.ShiftModifier)
    assert base(window, "dot") == pytest.approx((1.0 + 1 / ppu, 10 / ppu))
    assert window.document.undo_stack.count() == 2


def test_holding_an_arrow_is_one_undo_step(window) -> None:
    window.selection.set("dot")
    key(window, Qt.Key.Key_Left)
    for _ in range(5):
        key(window, Qt.Key.Key_Left, repeat=True)
    assert window.document.undo_stack.count() == 1
    key(window, Qt.Key.Key_Left)  # a new tap
    assert window.document.undo_stack.count() == 2
    window.document.undo_stack.undo()
    window.document.undo_stack.undo()
    assert base(window, "dot") == (1.0, 0.0)


def test_arrows_are_only_claimed_with_a_selection(window) -> None:
    event = QKeyEvent(QEvent.Type.ShortcutOverride, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier)
    assert not window.move_tool.wants_key(event)  # Left/Right step frames as before
    window.selection.set("dot")
    assert window.move_tool.wants_key(event)


# -- scale and rotate handles (P2a.2) ------------------------------------------------


def handles(window):
    """The selected layer's handle positions in canvas pixels: (corners, knob)."""
    from manim_studio.ui.canvas.gizmo import KNOB_OFFSET_PX

    box = window.canvas.outline.box
    to_px = window.canvas.units_transform()
    corners = [to_px.map(QPointF(*c)) for c in box.corners]
    knob = to_px.map(QPointF(*box.knob(KNOB_OFFSET_PX / window.canvas.px_per_unit())))
    return corners, knob


def test_dragging_a_corner_scales_about_the_layer_position(window, qt_app) -> None:
    window.selection.set("dot")  # circle radius 0.5 at (1, 0)
    corners, _ = handles(window)
    top_right = corners[2]
    pivot = px(window, 1.0, 0.0)
    target = pivot + (top_right - pivot) * 2  # twice as far from the pivot
    drag(window, top_right, target, qt_app)
    layer = window.project.layer("dot")
    assert layer.base.scale == pytest.approx(2.0, abs=0.02)
    assert layer.base.position == (1.0, 0.0)  # the pivot did not move
    assert window.document.undo_stack.undoText() == "Scale layer"


def test_dragging_the_knob_rotates_and_shift_snaps(window, qt_app) -> None:
    window.selection.set("big")  # square at the origin
    _, knob = handles(window)
    pivot = px(window, 0.0, 0.0)
    radius = (knob - pivot).manhattanLength()
    left = QPointF(pivot.x() - radius, pivot.y())  # a quarter turn counter-clockwise
    drag(window, knob, left, qt_app)
    assert window.project.layer("big").base.rotation == pytest.approx(90, abs=1)
    assert window.document.undo_stack.undoText() == "Rotate layer"
    window.document.undo_stack.undo()
    _, knob = handles(window)
    near = QPointF(pivot.x() - radius * 0.38, pivot.y() - radius * 0.92)  # about 22 degrees
    drag(window, knob, near, qt_app, Qt.KeyboardModifier.ShiftModifier)
    assert window.project.layer("big").base.rotation == pytest.approx(15)  # 22 degrees -> 15


def test_handles_follow_a_rotated_object(window, qt_app) -> None:
    from manim_studio.core.editing import edits

    window.document.apply(edits.update_layer(window.project, "big", base={"rotation": 45}), "Rotate")
    window.selection.set("big")
    corners, _ = handles(window)
    centre = px(window, 0.0, 0.0)
    # a 4x4 square turned 45 degrees: its corners are 2*sqrt(2) from the centre along the axes
    distances = sorted(
        round((c - centre).manhattanLength() / window.canvas.px_per_unit(), 1) for c in corners
    )
    assert distances == [pytest.approx(2.8, abs=0.1)] * 4


def test_rotating_a_keyed_rotation_sets_a_key(window, qt_app) -> None:
    from manim_studio.core.editing import edits

    window.document.apply(edits.set_key(window.project, "big", "rotation", 0.0, 0.0), "Key")
    window.seek(1.0)
    window.selection.set("big")
    _, knob = handles(window)
    pivot = px(window, 0.0, 0.0)
    radius = (knob - pivot).manhattanLength()
    drag(window, knob, QPointF(pivot.x() - radius, pivot.y()), qt_app)
    keys = window.project.layer("big").tracks["rotation"]
    assert [k.t for k in keys] == [0.0, 1.0]
    assert keys[1].value == pytest.approx(90, abs=1)
    assert window.project.layer("big").base.rotation == 0.0


def test_auto_key_turns_a_drag_into_an_animation(window, qt_app) -> None:
    window.move_tool.auto_key = lambda: True
    appears(window, "dot")
    window.seek(2.0)
    drag(window, px(window, 1.0, 0.0), px(window, 2.0, 0.0), qt_app)
    keys = window.project.layer("dot").tracks["position"]
    assert [(k.t, k.value) for k in keys] == [
        (0.0, (1.0, 0.0)),
        (2.0, pytest.approx((2.0, 0.0), abs=0.02)),
    ]


def test_keyed_fields_follow_the_playhead(window) -> None:
    window.selection.set("keyed")  # position keyed (-5, 2) at 0 s -> (-3, 2) at 2 s
    window.seek(0.0)
    assert window.properties.fields["base.position"].x.value() == pytest.approx(-5.0)
    window.seek(2.0)
    assert window.properties.fields["base.position"].x.value() == pytest.approx(-3.0)


def test_the_auto_key_menu_drives_canvas_edits(window, qt_app) -> None:
    assert not window.auto_key_action.isChecked()
    window.auto_key_action.setChecked(True)
    appears(window, "dot")
    window.seek(1.0)
    drag(window, px(window, 1.0, 0.0), px(window, 1.0, 1.0), qt_app)
    assert [k.t for k in window.project.layer("dot").tracks["position"]] == [0.0, 1.0]


def test_auto_key_only_places_a_new_object(window, qt_app) -> None:
    """Moving an object that has no entrance yet, with auto-key on, sets its place - no keys at
    its start that every later move would be tied to (the user's report)."""
    window.auto_key_action.setChecked(True)
    window.seek(2.0)
    drag(window, px(window, 1.0, 0.0), px(window, 2.0, 1.0), qt_app)
    layer = window.project.layer("dot")
    assert layer.tracks == {}
    assert layer.base.position == pytest.approx((2.0, 1.0), abs=0.05)
    assert "placed" in window.statusBar().currentMessage()
    window.seek(0.5)
    drag(window, px(window, 2.0, 1.0), px(window, 0.0, 0.0), qt_app)  # and moves freely at any time
    assert window.project.layer("dot").tracks == {}


def appears(window, layer_id: str) -> None:
    from manim_studio.core.editing import edits
    from manim_studio.core.model.schema import Lifetime

    edit = edits.update_layer(window.project, layer_id, lifetime=Lifetime(in_=0.0))
    window.document.apply(edit, "Appears at")


# -- the pivot cross (P2f.2, ADR 0021) ------------------------------------------------


def drawn_points(window, layer_id: str):
    import numpy as np

    mob = dict(window.canvas.evaluator.frame_layers(window.t))[layer_id]
    return np.concatenate([sub.points[:, :2] for sub in mob.family_members_with_points()])


def turn(window, layer_id: str, degrees: float) -> None:
    from manim_studio.core.editing import edits

    window.document.apply(edits.update_layer(window.project, layer_id, base={"rotation": degrees}), "Rotate")


def test_dragging_the_pivot_cross_moves_the_anchor_and_not_the_object(window, qt_app) -> None:
    import numpy as np

    turn(window, "big", 30.0)
    window.selection.set("big")
    before = drawn_points(window, "big")
    count = window.document.undo_stack.count()
    drag(window, px(window, 0.0, 0.0), px(window, 1.0, 1.5), qt_app, Qt.KeyboardModifier.ControlModifier)
    layer = window.project.layer("big")
    pivot, _, _ = window.canvas.evaluator.layer_frame(layer, window.t)
    assert pivot == pytest.approx((1.0, 1.5), abs=0.03)
    assert layer.base.anchor != (0.0, 0.0)
    assert np.allclose(drawn_points(window, "big"), before, atol=1e-6)  # the object stayed put
    assert window.document.undo_stack.count() == count + 1
    assert window.document.undo_stack.undoText() == "Move anchor"
    window.document.undo_stack.undo()
    assert window.project.layer("big").base.anchor == (0.0, 0.0)


def test_shift_snaps_the_pivot_to_a_corner_of_the_box(window, qt_app) -> None:
    turn(window, "big", 30.0)
    window.selection.set("big")
    corner = window.canvas.outline.box.corners[2]  # top-right of the turned 4x4 square
    near = px(window, corner[0] - 0.2, corner[1] + 0.15)
    drag(
        window,
        px(window, 0.0, 0.0),
        near,
        qt_app,
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
    )
    assert window.project.layer("big").base.anchor == pytest.approx((2.0, 2.0), abs=1e-6)


def test_without_ctrl_a_press_on_the_cross_moves_the_object(window, qt_app) -> None:
    window.move_tool.snapping = False  # exact moves; snapping is tested in test_snap_guides_ui
    for layer_id, (x, y) in (("tiny", (-5.0, -3.0)), ("big", (0.0, 0.0))):
        window.selection.set(layer_id)
        drag(window, px(window, x, y), px(window, x + 1.0, y), qt_app)
        layer = window.project.layer(layer_id)
        assert layer.base.anchor == (0.0, 0.0)
        assert layer.base.position == pytest.approx((x + 1.0, y), abs=0.02)


def test_double_clicking_the_cross_centres_the_anchor(window, qt_app) -> None:
    from manim_studio.core.editing import edits

    window.document.apply(edits.set_anchor(window.project, "big", (1.0, 1.0), 0.0), "Anchor")
    window.selection.set("big")
    mouse(window, QEvent.Type.MouseButtonDblClick, px(window, 1.0, 1.0), Qt.KeyboardModifier.ControlModifier)
    layer = window.project.layer("big")
    assert layer.base.anchor == pytest.approx((0.0, 0.0), abs=1e-6)
    assert window.document.undo_stack.undoText() == "Centre anchor"
    assert window.selection.layer_id == "big"  # not a drill-in


def test_the_knob_turns_the_object_about_its_anchor(window, qt_app) -> None:
    from manim_studio.core.editing import edits

    window.document.apply(edits.set_anchor(window.project, "big", (2.0, 2.0), 0.0), "Anchor")
    window.selection.set("big")
    _, knob = handles(window)
    pivot = px(window, 2.0, 2.0)
    offset = knob - pivot
    quarter = pivot + QPointF(offset.y(), -offset.x())  # a quarter turn counter-clockwise (y down)
    drag(window, knob, quarter, qt_app)
    layer = window.project.layer("big")
    assert layer.base.rotation == pytest.approx(90, abs=1)
    pivot_after, _, _ = window.canvas.evaluator.layer_frame(layer, window.t)
    assert pivot_after == pytest.approx((2.0, 2.0))


def test_moving_the_anchor_with_rotation_keyed_warns(window, qt_app) -> None:
    from manim_studio.core.editing import edits
    from manim_studio.ui.canvas.canvas_tools import SHIFTS_ELSEWHERE

    window.document.apply(edits.set_key(window.project, "big", "rotation", 2.0, 90.0), "Key")
    window.selection.set("big")
    drag(window, px(window, 0.0, 0.0), px(window, 0.5, 0.5), qt_app, Qt.KeyboardModifier.ControlModifier)
    assert window.messages[-1] == SHIFTS_ELSEWHERE
    assert "rotation" in window.project.layer("big").tracks


def test_clicking_on_nothing_and_escape_both_deselect_everything(window, qt_app) -> None:
    window.selection.set("dot")
    qt_app.processEvents()
    click(window, px(window, 5.0, -3.0))  # empty canvas
    qt_app.processEvents()
    assert window.selection.layer_id is None and not window.selection.layer_ids
    window.selection.set("dot")
    key(window, Qt.Key.Key_Escape)
    assert window.selection.layer_id is None and not window.selection.layer_ids
