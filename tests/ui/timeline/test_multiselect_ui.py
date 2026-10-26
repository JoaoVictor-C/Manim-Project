"""Several selected objects (P6c.2, ADR 0043): Shift+click, the marquee, the Layers panel,
moving and nudging together, Delete, the clipboard, presets, themes and Arrange."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QItemSelectionModel, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication

from manim_studio.core.model.schema import Canvas, Keyframe, Layer, PartKey, Project, Spec, Transform2D
from manim_studio.ui.main_window import MainWindow
from manim_studio.ui.panels.layers_panel import ID_ROLE

pytestmark = pytest.mark.ui

FILLED = {"fill": "#3b82f6", "fill_opacity": 0.8}
NONE = Qt.KeyboardModifier.NoModifier
SHIFT = Qt.KeyboardModifier.ShiftModifier


def square(layer_id: str, x: float, y: float, side: float = 1.0, **kw) -> Layer:
    return Layer(
        id=layer_id,
        spec=Spec(type="Square", params={"side_length": side}, style=FILLED),
        base=Transform2D(position=(x, y)),
        **kw,
    )


def scene() -> Project:
    return Project(
        canvas=Canvas(width_px=640, height_px=360, fps=30, duration=4.0),
        layers=[
            square("a", -4.0, 0.0),
            square("b", 0.0, 1.0, side=2.0),
            square(  # keyed: its base (unused while keyed) differs from its keys
                "c",
                0.0,
                0.0,
                tracks={"position": [Keyframe(t=0, value=(3.0, -2.0)), Keyframe(t=2, value=(5.0, -2.0))]},
            ),
        ],
    )


@pytest.fixture
def window(qt_app, tmp_path):
    path = tmp_path / "scene.json"
    path.write_text(scene().model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.resize(1100, 800)
    win.show()
    win.load(path)
    qt_app.processEvents()
    win.move_tool.snapping = False
    yield win
    win.close()


def px(window, x: float, y: float) -> QPointF:
    return window.canvas.units_transform().map(QPointF(float(x), float(y)))


def mouse(window, kind, pos: QPointF, modifiers=NONE) -> None:
    canvas = window.canvas
    button = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseMove else Qt.MouseButton.LeftButton
    buttons = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease else Qt.MouseButton.LeftButton
    global_pos = QPointF(canvas.mapToGlobal(pos.toPoint()))
    QApplication.sendEvent(canvas, QMouseEvent(kind, pos, global_pos, button, buttons, modifiers))


def click(window, x, y, qt_app, modifiers=NONE) -> None:
    mouse(window, QEvent.Type.MouseButtonPress, px(window, x, y), modifiers)
    mouse(window, QEvent.Type.MouseButtonRelease, px(window, x, y), modifiers)
    qt_app.processEvents()


def drag(window, start, end, qt_app, modifiers=NONE) -> None:
    a, b = px(window, *start), px(window, *end)
    mouse(window, QEvent.Type.MouseButtonPress, a, modifiers)
    for f in (0.3, 0.7, 1.0):
        mouse(window, QEvent.Type.MouseMove, a + (b - a) * f, modifiers)
        qt_app.processEvents()
    mouse(window, QEvent.Type.MouseButtonRelease, b, modifiers)
    qt_app.processEvents()


def key(window, k, modifiers=NONE) -> None:
    QApplication.sendEvent(window.canvas, QKeyEvent(QEvent.Type.KeyPress, k, modifiers, ""))


def position(window, layer_id: str):
    return window.project.layer(layer_id).base.position


# -- choosing ------------------------------------------------------------------------


def test_shift_click_adds_and_takes_out(window, qt_app) -> None:
    click(window, -4.0, 0.0, qt_app)
    click(window, 0.0, 1.0, qt_app, SHIFT)
    assert window.selection.layer_ids == ("a", "b") and window.selection.layer_id == "b"
    assert sorted(window.layers.selected_ids()) == ["a", "b"]
    assert [i for i, _ in window.canvas.other_outlines] == ["a"]
    assert window.canvas.param_handles == []  # several: no handles
    click(window, -4.0, 0.0, qt_app, SHIFT)  # a Shift+click on a selected one takes it out
    assert window.selection.layer_ids == ("b",)
    assert window.canvas.other_outlines == []
    assert window.document.undo_stack.count() == 0


def test_a_plain_click_on_one_of_several_selects_only_it(window, qt_app) -> None:
    window.selection.set_layers(["a", "b"])
    qt_app.processEvents()
    click(window, -4.0, 0.0, qt_app)
    assert window.selection.layer_ids == ("a",)


def test_a_marquee_selects_what_it_touches(window, qt_app) -> None:
    drag(window, (-6.0, 2.5), (0.5, -0.2), qt_app)  # touches a and b (b spans y 0..2), not c
    assert set(window.selection.layer_ids) == {"a", "b"}
    assert window.canvas.marquee is None
    assert window.document.undo_stack.count() == 0
    drag(window, (2.0, -1.0), (6.5, -3.0), qt_app, SHIFT)  # Shift adds
    assert set(window.selection.layer_ids) == {"a", "b", "c"}
    drag(window, (6.0, 3.5), (6.5, 3.0), qt_app)  # nothing there: clears
    assert window.selection.layer_ids == ()


def test_the_marquee_shows_while_dragging_and_escape_drops_it(window, qt_app) -> None:
    mouse(window, QEvent.Type.MouseButtonPress, px(window, -6.0, 2.5))
    mouse(window, QEvent.Type.MouseMove, px(window, 0.5, -0.2))
    qt_app.processEvents()
    assert window.canvas.marquee is not None
    key(window, Qt.Key.Key_Escape)
    assert window.canvas.marquee is None
    mouse(window, QEvent.Type.MouseButtonRelease, px(window, 0.5, -0.2))
    assert window.selection.layer_ids == ()


def test_ctrl_click_in_layers_selects_several(window, qt_app) -> None:
    window.selection.set("a")
    qt_app.processEvents()
    item = next(i for i in window.layers.items() if i.data(0, ID_ROLE) == "c")
    window.layers.list.setCurrentItem(item, 0, QItemSelectionModel.SelectionFlag.Select)  # Ctrl+click
    qt_app.processEvents()
    assert set(window.selection.layer_ids) == {"a", "c"} and window.selection.layer_id == "c"
    assert "1 more selected" in window.properties.title.text()


# -- acting on all of them ---------------------------------------------------------------


def test_dragging_one_moves_them_all_in_one_undo_step(window, qt_app) -> None:
    window.selection.set_layers(["a", "b"])
    qt_app.processEvents()
    drag(window, (-4.0, 0.0), (-3.0, 0.5), qt_app)
    assert position(window, "a") == pytest.approx((-3.0, 0.5), abs=0.02)
    assert position(window, "b") == pytest.approx((1.0, 1.5), abs=0.02)
    assert set(window.selection.layer_ids) == {"a", "b"} and window.selection.layer_id == "a"
    assert window.document.undo_stack.count() == 1
    assert window.document.undo_stack.undoText() == "Move layers"
    window.document.undo_stack.undo()
    assert position(window, "a") == (-4.0, 0.0) and position(window, "b") == (0.0, 1.0)


def test_a_keyed_object_moves_by_a_key_in_a_group(window, qt_app) -> None:
    window.selection.set_layers(["a", "c"])
    qt_app.processEvents()
    drag(window, (-4.0, 0.0), (-4.0, 1.0), qt_app)
    keys = window.project.layer("c").tracks["position"]
    assert keys[0].value == pytest.approx((3.0, -1.0), abs=0.02)  # the key at the playhead (t = 0)
    assert keys[1].value == (5.0, -2.0)
    assert window.project.layer("c").base.position == scene().layer("c").base.position


def test_shift_drag_from_a_new_object_adds_it_and_moves_all_on_one_axis(window, qt_app) -> None:
    window.selection.set("a")
    qt_app.processEvents()
    drag(window, (0.0, 1.0), (1.0, 1.2), qt_app, SHIFT)
    assert set(window.selection.layer_ids) == {"a", "b"}
    assert position(window, "a") == pytest.approx((-3.0, 0.0), abs=0.02)
    assert position(window, "b") == pytest.approx((1.0, 1.0), abs=0.02)


def test_arrow_keys_nudge_them_all(window, qt_app) -> None:
    window.selection.set_layers(["a", "b"])
    qt_app.processEvents()
    key(window, Qt.Key.Key_Right)
    step = 1.0 / window.canvas.px_per_unit()
    assert position(window, "a")[0] == pytest.approx(-4.0 + step)
    assert position(window, "b")[0] == pytest.approx(0.0 + step)
    assert window.document.undo_stack.undoText() == "Nudge layers"


def test_delete_in_layers_removes_them_all(window, qt_app) -> None:
    window.selection.set_layers(["a", "c"])
    qt_app.processEvents()
    window.layers.delete_selected()
    qt_app.processEvents()
    assert [x.id for x in window.project.layers] == ["b"]
    assert window.document.undo_stack.undoText() == "Delete layers"
    window.document.undo_stack.undo()
    assert len(window.project.layers) == 3


def test_copy_paste_and_duplicate_several(window, qt_app) -> None:
    window.selection.set_layers(["a", "b"])
    qt_app.processEvents()
    window.clipboard.duplicate()
    qt_app.processEvents()
    assert len(window.project.layers) == 5
    new = set(window.selection.layer_ids)
    assert len(new) == 2 and not new & {"a", "b", "c"}  # the copies are selected
    window.selection.set_layers(["a", "c"])
    window.clipboard.cut()
    qt_app.processEvents()
    assert {x.id for x in window.project.layers} == {"b", *new}
    window.clipboard.paste()
    qt_app.processEvents()
    assert len(window.project.layers) == 5
    assert len(window.selection.layer_ids) == 2


def test_a_preset_and_a_theme_apply_to_all(window, qt_app) -> None:
    window.selection.set_layers(["a", "b"])
    qt_app.processEvents()
    preset = next(p for p in window.library.presets if p.category == "entrance")
    assert window.apply_preset(preset)
    assert window.project.layer("a").clips and window.project.layer("b").clips
    assert not window.project.layer("c").clips
    assert window.document.undo_stack.count() == 1
    theme = window.library.themes[0]
    window.apply_theme(theme)
    assert window.project.layer("c").spec.style == scene().layer("c").spec.style
    assert window.project.layer("a").spec.style != scene().layer("a").spec.style


# -- arrange -------------------------------------------------------------------------------


def test_align_and_distribute(window, qt_app) -> None:
    window.selection.set_layers(["a", "b", "c"])
    qt_app.processEvents()
    window.align("top")  # b's top (y 2) is highest
    assert position(window, "a")[1] == pytest.approx(1.5, abs=1e-6)
    assert position(window, "b")[1] == pytest.approx(1.0, abs=1e-6)
    assert window.project.layer("c").tracks["position"][0].value[1] == pytest.approx(1.5, abs=1e-6)
    assert window.document.undo_stack.undoText() == "Align top"
    window.document.undo_stack.undo()
    window.distribute(0)  # a -4.5..-3.5, b -1..1, c 2.5..3.5: gaps 2.5 and 1.5 become 2 and 2
    assert position(window, "b")[0] == pytest.approx(-0.5, abs=1e-6)
    assert position(window, "a")[0] == -4.0
    assert window.project.layer("c").tracks["position"][0].value == (3.0, -2.0)
    assert window.document.undo_stack.undoText() == "Distribute"


def test_one_object_aligns_to_the_frame_and_too_few_do_not_distribute(window, qt_app) -> None:
    window.selection.set("a")
    qt_app.processEvents()
    window.align("left")
    half_width = window.project.canvas.frame_width / 2
    assert position(window, "a")[0] == pytest.approx(-half_width + 0.5, abs=1e-6)
    count = window.document.undo_stack.count()
    window.distribute(0)
    assert window.document.undo_stack.count() == count
    assert "three or more" in window.statusBar().currentMessage()
    window.selection.set_layers(["a", "b"])
    window.align("left")
    window.align("left")
    assert window.statusBar().currentMessage() == "Already lined up"
    assert np.isfinite(position(window, "b")[0])


def test_with_several_selected_a_corner_press_moves_them_rather_than_scaling(window, qt_app) -> None:
    window.selection.set_layers(["a", "b"])
    qt_app.processEvents()
    drag(window, (0.98, 1.98), (1.48, 2.48), qt_app)  # b's top-right corner
    assert window.project.layer("b").base.scale == 1.0
    assert position(window, "b") == pytest.approx((0.5, 1.5), abs=0.02)
    assert position(window, "a") == pytest.approx((-3.5, 0.5), abs=0.02)


def test_a_part_selected_with_its_object_moves_once(qt_app, tmp_path) -> None:
    project = Project(
        canvas=scene().canvas,
        layers=[
            Layer(id="ax", spec=Spec(type="MathTex", params={"text": "a^2 + b^2", "font_size": 96})),
            Layer(id="pt", parent_id="ax", part=PartKey(tex="b^2")),
        ],
    )
    path = tmp_path / "parts.json"
    path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.resize(1100, 800)
    win.show()
    win.load(path)
    qt_app.processEvents()
    try:
        win.selection.set_layers(["ax", "pt"])
        qt_app.processEvents()
        key(win, Qt.Key.Key_Right)
        assert win.project.layer("ax").base.position[0] > 0
        assert win.project.layer("pt").base.position == (0.0, 0.0)  # carried by its object, not moved twice
    finally:
        win.close()
