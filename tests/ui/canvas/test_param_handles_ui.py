"""Parameter handles and snapping guides on the canvas (P6c.1, ADR 0043), with real input events."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication

from manim_studio.core.model.schema import Canvas, Layer, Project, Spec, Transform2D
from manim_studio.ui.main_window import MainWindow

pytestmark = pytest.mark.ui

FILLED = {"fill": "#3b82f6", "fill_opacity": 0.8}
NONE = Qt.KeyboardModifier.NoModifier
SHIFT = Qt.KeyboardModifier.ShiftModifier
ALT = Qt.KeyboardModifier.AltModifier


def scene() -> Project:
    return Project(
        canvas=Canvas(width_px=640, height_px=360, fps=30, duration=4.0),
        layers=[
            Layer(
                id="rect",
                spec=Spec(type="Rectangle", params={"width": 3.0, "height": 1.0}, style=FILLED),
                base=Transform2D(position=(-4.0, 0.0), rotation=90.0, scale=1.5),
            ),
            Layer(
                id="line",
                spec=Spec(type="Line", params={"start": [0.0, 0.0], "end": [2.0, 0.0]}),
                base=Transform2D(position=(2.0, -2.5)),
            ),
            Layer(
                id="text",
                spec=Spec(type="Text", params={"text": "Handles", "font_size": 48}),
                base=Transform2D(position=(3.0, 2.0)),
            ),
            Layer(
                id="circ",
                spec=Spec(type="Circle", params={"radius": 0.5}, style=FILLED),
                base=Transform2D(position=(0.0, 2.0)),
            ),
            Layer(id="tri", spec=Spec(type="Triangle", style=FILLED), base=Transform2D(position=(0.0, -1.0))),
        ],
    )


def open_window(qt_app, tmp_path, project: Project) -> MainWindow:
    path = tmp_path / "scene.json"
    path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.resize(1100, 800)
    win.show()
    win.load(path)
    qt_app.processEvents()
    return win


@pytest.fixture
def window(qt_app, tmp_path):
    win = open_window(qt_app, tmp_path, scene())
    win.move_tool.snapping = False  # exact drags; snapping has its own tests below
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


def press_and_move(window, start, end, qt_app, press=NONE, moving=NONE) -> None:
    mouse(window, QEvent.Type.MouseButtonPress, start, press)
    for f in (0.3, 0.7, 1.0):
        mouse(window, QEvent.Type.MouseMove, start + (end - start) * f, moving)
        qt_app.processEvents()


def drag(window, start, end, qt_app, press=NONE, moving=NONE) -> None:
    press_and_move(window, start, end, qt_app, press, moving)
    mouse(window, QEvent.Type.MouseButtonRelease, end, moving)
    qt_app.processEvents()


def handles(window) -> dict[str, np.ndarray]:
    return {h.param: h.world for h in window.canvas.param_handles}


def select(window, layer_id: str, qt_app) -> None:
    window.selection.set(layer_id)
    qt_app.processEvents()


def drawn_points(window, layer_id: str) -> np.ndarray:
    mob = dict(window.evaluator.frame_layers(window.t))[layer_id]
    return mob.family_members_with_points()[0].points[:, :2].copy()


# -- handles --------------------------------------------------------------------------


def test_a_turned_scaled_rectangle_shows_its_handles_in_its_own_frame(window, qt_app) -> None:
    select(window, "rect", qt_app)
    found = handles(window)
    assert found["width"] == pytest.approx((-4.0, 2.25), abs=1e-6)  # local (1.5, 0) turned up, x1.5
    assert found["height"] == pytest.approx((-4.75, 0.0), abs=1e-6)


def test_dragging_a_size_handle_changes_the_parameter_in_one_undo_step(window, qt_app) -> None:
    select(window, "rect", qt_app)
    drag(window, px(window, -4.0, 2.25), px(window, -4.0, 3.0), qt_app)
    layer = window.project.layer("rect")
    assert layer.spec.params["width"] == pytest.approx(4.0, abs=0.02)  # up 0.75 = local 0.5, both sides
    assert layer.base == scene().layer("rect").base  # no position, scale or key changes
    assert window.document.undo_stack.count() == 1
    assert window.document.undo_stack.undoText() == "Change width"
    assert window.canvas.readout is None
    window.document.undo_stack.undo()
    assert window.project.layer("rect").spec.params["width"] == 3.0


def test_escape_cancels_a_handle_drag(window, qt_app) -> None:
    select(window, "rect", qt_app)
    press_and_move(window, px(window, -4.0, 2.25), px(window, -4.0, 3.0), qt_app)
    assert window.project.layer("rect").spec.params["width"] != 3.0  # previewing
    assert "width" in window.canvas.readout[1]
    QApplication.sendEvent(window.canvas, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, NONE))
    mouse(window, QEvent.Type.MouseButtonRelease, px(window, -4.0, 3.0))
    assert window.project.layer("rect").spec.params["width"] == 3.0
    assert window.document.undo_stack.count() == 0


def test_dragging_a_line_end_keeps_the_other_end_in_place(window, qt_app) -> None:
    select(window, "line", qt_app)
    found = handles(window)
    assert found["start"] == pytest.approx((1.0, -2.5), abs=1e-6)
    assert found["end"] == pytest.approx((3.0, -2.5), abs=1e-6)
    drag(window, px(window, 3.0, -2.5), px(window, 3.5, -1.5), qt_app)
    layer = window.project.layer("line")
    assert tuple(layer.spec.params["end"]) == pytest.approx((2.5, 1.0), abs=0.03)
    assert layer.base.scale == 1.0  # the end handle won over the padded box's corner
    points = drawn_points(window, "line")
    assert points[0] == pytest.approx((1.0, -2.5), abs=1e-6)  # the start did not move
    assert points[-1] == pytest.approx((3.5, -1.5), abs=0.03)  # the end is under the cursor
    assert window.document.undo_stack.undoText() == "Change end"


def test_shift_steps_a_font_size_by_four_points(window, qt_app) -> None:
    select(window, "text", qt_app)
    x, y = handles(window)["font_size"]
    drag(window, px(window, x, y), px(window, 3.0 + (x - 3.0) * 1.3, y), qt_app)
    size = window.project.layer("text").spec.params["font_size"]
    assert size == pytest.approx(48 * 1.3, abs=1.0) and float(size).is_integer()
    window.document.undo_stack.undo()
    drag(window, px(window, x, y), px(window, 3.0 + (x - 3.0) * 1.3, y), qt_app, moving=SHIFT)
    assert window.project.layer("text").spec.params["font_size"] in (60.0, 64.0)


def test_a_circle_radius_follows_the_cursor(window, qt_app) -> None:
    select(window, "circ", qt_app)
    assert handles(window)["radius"] == pytest.approx((0.5, 2.0), abs=1e-6)
    drag(window, px(window, 0.5, 2.0), px(window, 1.25, 2.0), qt_app)
    assert window.project.layer("circ").spec.params["radius"] == pytest.approx(1.25, abs=0.02)


def test_objects_without_sizes_and_parts_show_no_handles(window, qt_app) -> None:
    select(window, "tri", qt_app)
    assert window.canvas.outline is not None
    assert window.canvas.param_handles == []
    window.selection.clear()
    qt_app.processEvents()
    assert window.canvas.param_handles == []


def test_a_connector_end_drags_its_offset_in_the_target_frame(qt_app, tmp_path) -> None:
    project = scene()
    connector = Layer(
        id="link",
        spec=Spec(type="Connector", params={"source": "circ", "target": "rect", "ends": "centres"}),
    )
    win = open_window(qt_app, tmp_path, project.model_copy(update={"layers": [*project.layers, connector]}))
    win.move_tool.snapping = False
    try:
        select(win, "link", qt_app)
        found = handles(win)
        assert found["source_offset"] == pytest.approx((0.0, 2.0), abs=1e-6)
        assert found["target_offset"] == pytest.approx((-4.0, 0.0), abs=1e-6)
        drag(win, px(win, -4.0, 0.0), px(win, -4.0, 0.75), qt_app)
        # the rectangle is turned 90 degrees and scaled 1.5: world up 0.75 is local +x 0.5
        offset = win.project.layer("link").spec.params["target_offset"]
        assert tuple(offset) == pytest.approx((0.5, 0.0), abs=0.03)
    finally:
        win.close()


# -- snapping guides --------------------------------------------------------------------


def two_squares() -> Project:
    return Project(
        canvas=Canvas(width_px=640, height_px=360, fps=30, duration=4.0),
        layers=[
            Layer(
                id="a",
                spec=Spec(type="Square", params={"side_length": 1.0}, style=FILLED),
                base=Transform2D(position=(-2.0, -2.0)),
            ),
            Layer(
                id="b",
                spec=Spec(type="Square", params={"side_length": 1.0}, style=FILLED),
                base=Transform2D(position=(1.3, -2.0)),
            ),
        ],
    )


@pytest.fixture
def squares(qt_app, tmp_path):
    win = open_window(qt_app, tmp_path, two_squares())
    yield win
    win.close()


def short_of_b(window) -> float:
    """A move that leaves a's right edge 3 px short of b's left edge (within the 6 px reach)."""
    return 2.3 - 3.0 / window.canvas.px_per_unit()


def test_a_moved_edge_snaps_to_another_object_and_shows_a_guide(squares, qt_app) -> None:
    dx = short_of_b(squares)
    select(squares, "a", qt_app)
    press_and_move(squares, px(squares, -2.0, -2.0), px(squares, -2.0 + dx, -2.0), qt_app)
    assert squares.canvas.guides  # drawn while dragging
    (x0, _y0), (x1, _y1) = squares.canvas.guides[0]
    assert x0 == x1 == pytest.approx(0.8)  # b's left edge
    mouse(squares, QEvent.Type.MouseButtonRelease, px(squares, -2.0 + dx, -2.0))
    assert squares.project.layer("a").base.position == pytest.approx((0.3, -2.0), abs=1e-6)
    assert squares.canvas.guides == []


def test_alt_while_dragging_or_the_view_toggle_turn_snapping_off(squares, qt_app) -> None:
    dx = short_of_b(squares)
    select(squares, "a", qt_app)
    drag(squares, px(squares, -2.0, -2.0), px(squares, -2.0 + dx, -2.0), qt_app, moving=ALT)
    assert squares.project.layer("a").base.position[0] == pytest.approx(-2.0 + dx, abs=0.02)
    assert squares.project.layer("a").base.position[0] != pytest.approx(0.3, abs=1e-3)
    squares.document.undo_stack.undo()
    squares.snap_action.setChecked(False)
    drag(squares, px(squares, -2.0, -2.0), px(squares, -2.0 + dx, -2.0), qt_app)
    assert squares.project.layer("a").base.position[0] == pytest.approx(-2.0 + dx, abs=0.02)
    squares.snap_action.setChecked(True)
    assert squares.move_tool.snapping


def test_a_size_handle_snaps_to_another_object_edge(squares, qt_app) -> None:
    select(squares, "a", qt_app)
    (x, y) = handles(squares)["side_length"]
    assert (x, y) == pytest.approx((-1.5, -2.0), abs=1e-6)
    near = 0.8 - 3.0 / squares.canvas.px_per_unit()  # 3 px short of b's left edge
    drag(squares, px(squares, x, y), px(squares, near, y), qt_app)
    assert squares.project.layer("a").spec.params["side_length"] == pytest.approx(2 * 2.8, abs=1e-6)


def test_a_turned_scaled_line_end_keeps_the_other_end_in_place(qt_app, tmp_path) -> None:
    line = Layer(
        id="line",
        spec=Spec(type="Line", params={"start": [0.0, 0.0], "end": [2.0, 0.0]}),
        base=Transform2D(position=(0.0, 0.0), rotation=90.0, scale=1.5),
    )
    win = open_window(qt_app, tmp_path, Project(canvas=scene().canvas, layers=[line]))
    win.move_tool.snapping = False
    try:
        select(win, "line", qt_app)
        assert handles(win)["end"] == pytest.approx((0.0, 1.5), abs=1e-6)
        drag(win, px(win, 0.0, 1.5), px(win, -0.75, 1.5), qt_app)
        assert tuple(win.project.layer("line").spec.params["end"]) == pytest.approx((2.0, 0.5), abs=0.03)
        points = drawn_points(win, "line")
        assert points[0] == pytest.approx((0.0, -1.5), abs=1e-6)  # the start stayed
        assert points[-1] == pytest.approx((-0.75, 1.5), abs=0.03)
    finally:
        win.close()


def test_escape_clears_the_guides(squares, qt_app) -> None:
    dx = short_of_b(squares)
    select(squares, "a", qt_app)
    press_and_move(squares, px(squares, -2.0, -2.0), px(squares, -2.0 + dx, -2.0), qt_app)
    assert squares.canvas.guides
    QApplication.sendEvent(squares.canvas, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, NONE))
    assert squares.canvas.guides == []
    mouse(squares, QEvent.Type.MouseButtonRelease, px(squares, -2.0 + dx, -2.0))


def test_a_small_move_is_not_pulled_back_by_the_object_or_what_follows_it(qt_app, tmp_path) -> None:
    project = two_squares()
    link = Layer(
        id="link",
        spec=Spec(type="Connector", params={"source": "a", "target": "b", "ends": "centres", "gap": 0.0}),
    )
    win = open_window(qt_app, tmp_path, project.model_copy(update={"layers": [*project.layers, link]}))
    try:
        step = 3.0 / win.canvas.px_per_unit()  # 3 px: within reach of where a was, and of the link's end
        select(win, "a", qt_app)
        drag(win, px(win, -2.0, -2.0), px(win, -2.0 + step, -2.0), qt_app)
        assert win.project.layer("a").base.position[0] == pytest.approx(-2.0 + step, abs=0.01)
    finally:
        win.close()


def test_a_small_object_hides_handles_that_would_cover_its_middle(qt_app, tmp_path) -> None:
    tiny = Layer(id="tiny", spec=Spec(type="Circle", params={"radius": 0.15}), base=Transform2D())
    win = open_window(qt_app, tmp_path, Project(canvas=scene().canvas, layers=[tiny]))
    try:
        select(win, "tiny", qt_app)
        assert 0.15 * win.canvas.px_per_unit() < 14.0
        assert win.canvas.param_handles == []  # a press on its middle moves it (zoom in to resize)
        win.canvas.zoom(4.0)  # the view re-renders
        qt_app.processEvents()
        assert [h.param for h in win.canvas.param_handles] == ["radius"]
    finally:
        win.close()
