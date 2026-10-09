"""Parts on the canvas (P2c.4, ADR 0012): root-first clicks, drill-in, part gizmos, warnings."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPointF, Qt

from manim_studio.core import edits
from manim_studio.core.schema import Canvas, Layer, PartKey, Project, Spec, Transform2D
from manim_studio.ui.main_window import MainWindow
from ui.test_canvas_tools import click, drag, key, mouse, px

pytestmark = [pytest.mark.ui, pytest.mark.latex]

TEXT = r"a^2 + b^2 = c^2"


def project(root_base: Transform2D | None = None) -> Project:
    eq = Layer(
        id="eq",
        spec=Spec(type="MathTex", params={"text": TEXT, "font_size": 144}),
        base=root_base or Transform2D(),
    )
    parts = [
        Layer(id="b", name="b^2", parent_id="eq", part=PartKey(tex="b^2")),
        Layer(id="c", name="c^2", parent_id="eq", part=PartKey(tex="c^2")),
    ]
    return Project(canvas=Canvas(width_px=640, height_px=360, fps=30, duration=4.0), layers=[eq, *parts])


def open_window(qt_app, tmp_path, p: Project) -> MainWindow:
    path = tmp_path / "parts.json"
    path.write_text(p.model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.resize(1100, 800)
    win.show()
    win.load(path)
    qt_app.processEvents()
    return win


@pytest.fixture
def window(qt_app, tmp_path):
    win = open_window(qt_app, tmp_path, project())
    yield win
    win.close()


def centre(window, layer_id: str) -> tuple[float, float]:
    mob = dict(window.evaluator.frame_layers(window.t))[layer_id]
    x, y, _ = mob.get_center()
    return float(x), float(y)


def glyph(window, layer_id: str) -> tuple[float, float]:
    """The point on the ink of the layer's first glyph nearest its centre.

    The centre itself may be a hole (as in "b"); points near the edge of a small
    part may fall on a gizmo handle instead.
    """
    from manim_studio.render.hit_test import hit_layers

    layers = window.evaluator.frame_layers(window.t)
    leaf = dict(layers)[layer_id].family_members_with_points()[0]
    (x0, y0, _), (x1, y1, _) = leaf.get_corner((-1, -1, 0)), leaf.get_corner((1, 1, 0))
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    ppu = window.canvas.px_per_unit()
    grid = [(x0 + (x1 - x0) * i / 20, y0 + (y1 - y0) * j / 20) for i in range(1, 20) for j in range(1, 20)]
    for point in sorted(grid, key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2):
        if hit_layers(layers, point, ppu)[:1] == [layer_id]:
            return point
    raise AssertionError(f"no ink found for {layer_id}")


def double_click(window, pos: QPointF) -> None:
    mouse(window, QEvent.Type.MouseButtonPress, pos)
    mouse(window, QEvent.Type.MouseButtonRelease, pos)
    mouse(window, QEvent.Type.MouseButtonDblClick, pos)
    mouse(window, QEvent.Type.MouseButtonRelease, pos)


def test_a_click_on_a_part_selects_the_whole_object(window) -> None:
    click(window, px(window, *glyph(window, "b")))
    assert window.selection.layer_id == "eq"
    whole = window.canvas.outline.bounds
    assert (
        whole.left()
        < centre(window, "eq")[0]
        < centre(window, "b")[0]
        < centre(window, "c")[0]
        < whole.right()
    )


def test_double_click_drills_in_then_clicks_pick_parts_and_escape_backs_out(window) -> None:
    double_click(window, px(window, *glyph(window, "b")))
    assert window.selection.layer_id == "b"
    assert window.canvas.outline.anchor == pytest.approx(
        centre(window, "b"), abs=0.02
    )  # the part pivots on itself
    click(window, px(window, *glyph(window, "c")))
    assert window.selection.layer_id == "c"
    key(window, Qt.Key.Key_Escape)
    assert window.selection.layer_id == "eq"


def test_dragging_a_part_moves_only_it_in_its_parents_frame(qt_app, tmp_path) -> None:
    win = open_window(qt_app, tmp_path, project(Transform2D(scale=2.0, rotation=90.0)))
    try:
        start, grab = centre(win, "b"), glyph(win, "b")
        double_click(win, px(win, *grab))
        assert win.selection.layer_id == "b"
        drag(win, px(win, *grab), px(win, grab[0], grab[1] + 1.0), qt_app)
        # The object is rotated 90 degrees and doubled: world up 1 is local +x 0.5.
        x, y = win.project.layer("b").base.position
        assert (x, y) == pytest.approx((0.5, 0.0), abs=0.02)
        assert win.project.layer("eq").base.position == (0.0, 0.0)
        assert centre(win, "b") == pytest.approx((start[0], start[1] + 1.0), abs=0.02)
    finally:
        win.close()


def test_a_text_edit_that_moves_a_match_is_reported(window) -> None:
    retyped = Spec(type="MathTex", params={"text": r"c^2 + b^2 = a^2", "font_size": 144})
    window.builds.submit(lambda p: edits.update_layer(p, "eq", spec=retyped), "Edit text")
    assert "Check parts:" in window.statusBar().currentMessage()
    assert "c^2 (may now match another place)" in window.statusBar().currentMessage()
