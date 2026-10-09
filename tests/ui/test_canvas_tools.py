"""Selecting and moving objects on the canvas (S3.4-S3.5, ADR 0016), with real input events."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication

from manim_studio.core.evaluator import layer_transform
from manim_studio.core.schema import Canvas, Clip, Keyframe, Layer, Project, Spec, Transform2D
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
