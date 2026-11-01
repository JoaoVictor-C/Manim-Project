"""The Stage's tool rail (ADR 0087): groups, last-used variants, flyouts, keys, folding for a short window."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMenu

from manim_studio.core.model.schema import Canvas, Layer, Project, Spec
from manim_studio.ui.canvas import tool_rail
from manim_studio.ui.main_window import MainWindow
from manim_studio.ui.session import insert_catalogue as catalogue

pytestmark = pytest.mark.ui

GROUPS = ["shape", "line", "text", "math", "media", "graph", "solid"]


@pytest.fixture
def window(qt_app, tmp_path):
    path = tmp_path / "scene.json"
    scene = Project(
        canvas=Canvas(width_px=640, height_px=360, duration=4.0),
        layers=[Layer(id="sq", spec=Spec(type="Square", params={"side_length": 2}))],
    )
    path.write_text(scene.model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.resize(1200, 900)
    win.show()
    win.load(path)
    qt_app.processEvents()
    yield win
    win.close()


def click_stage(window, x: float, y: float) -> None:
    point = window.canvas.units_transform().map(QPointF(x, y))
    QTest.mouseClick(window.canvas, Qt.MouseButton.LeftButton, pos=point.toPoint())


def label_of(action) -> str:
    return action.text().split("\t")[0]


def test_the_rail_groups_move_insert_and_anchor_with_the_key_in_each_tooltip(window) -> None:
    buttons = window.stage_tool_buttons
    assert list(buttons) == ["select", "hand", *GROUPS, "anchor"]
    keys = [("select", "V"), ("hand", "H"), ("anchor", "P")]
    keys += [(g.key, g.keys) for g in catalogue.INSERT_GROUPS]
    for mode, key in keys:
        assert f"({key})" in buttons[mode].toolTip() and buttons[mode].accessibleName()
    assert buttons["select"].isChecked()
    assert [b.has_flyout for b in buttons.values()] == [False, False, *[True] * 7, False]


def test_an_insert_tool_shows_the_glyph_of_its_last_variant_and_a_flyout_lists_the_group(window) -> None:
    rail = window.stage_tools
    assert rail.variant("shape") == "Circle" and rail.buttons["shape"].glyph_type == "Circle"
    menu = rail.flyout("shape")
    labels = [label_of(a) for a in menu.actions()]
    assert labels[0] == "Circle" and "Rounded rectangle" in labels and "Connector" not in labels
    keys = {label_of(a): a.text().split("\t")[1] for a in menu.actions() if "\t" in a.text()}
    assert keys == {"Circle": "O", "Rectangle": "Shift+R"}
    assert [label_of(a) for a in menu.actions() if a.isChecked()] == ["Circle"]
    next(a for a in menu.actions() if a.text().startswith("Rectangle")).trigger()
    assert rail.variant("shape") == "Rectangle" and rail.buttons["shape"].glyph_type == "Rectangle"
    assert "Rectangle" in rail.buttons["shape"].toolTip()
    assert window.canvas.interaction_mode == "shape"  # choosing a variant arms the tool
    assert [label_of(a) for a in rail.flyout("shape").actions() if a.isChecked()] == ["Rectangle"]


def test_a_click_on_the_stage_places_the_last_variant_and_returns_to_select(window) -> None:
    window.stage_tools.choose_variant("line", "Arrow")
    assert window.stage_tool_buttons["line"].isChecked()
    click_stage(window, 2.0, 1.0)
    placed = window.project.layers[-1]
    assert placed.spec.type == "Arrow" and placed.base.position == pytest.approx((2.0, 1.0), abs=0.05)
    assert window.canvas.interaction_mode == "select" and window.stage_tool_buttons["select"].isChecked()
    assert window.layers.recent_keys()[0] == "obj:Arrow"


def test_the_variants_are_remembered_across_windows(qt_app, window) -> None:
    window.stage_tools.choose_variant("solid", "Sphere")
    second = MainWindow()
    try:
        assert second.stage_tools.variant("solid") == "Sphere"
        assert second.stage_tools.buttons["solid"].glyph_type == "Sphere"
    finally:
        second.close()


def test_a_variant_that_is_gone_falls_back_to_the_default(qt_app) -> None:
    rail = tool_rail.ToolRail({"shape": "NoSuchThing", "line": "Arrow"})
    assert rail.variant("shape") == "Circle" and rail.variant("line") == "Arrow"


def test_the_corner_triangle_a_right_click_and_a_long_press_ask_for_the_flyout(window, qt_app) -> None:
    button = window.stage_tool_buttons["shape"]
    asked = []
    button.flyoutRequested.connect(lambda: asked.append("flyout"))
    QTest.mouseClick(button, Qt.MouseButton.LeftButton, pos=QPoint(button.width() - 5, button.height() - 5))
    assert asked == ["flyout"] and window.canvas.interaction_mode == "select"  # the triangle does not arm
    QTest.mouseClick(button, Qt.MouseButton.RightButton)
    assert asked == ["flyout", "flyout"]
    QTest.mouseClick(button, Qt.MouseButton.LeftButton, pos=QPoint(8, 8))
    assert asked == ["flyout", "flyout"] and window.canvas.interaction_mode == "shape"  # the body arms it
    hand = window.stage_tool_buttons["hand"]
    hand.flyoutRequested.connect(lambda: asked.append("hand"))
    QTest.mouseClick(hand, Qt.MouseButton.RightButton)
    assert "hand" not in asked  # a tool without variants has no flyout
    text = window.stage_tool_buttons["text"]
    text.flyoutRequested.connect(lambda: asked.append("long"))
    QTest.mousePress(text, Qt.MouseButton.LeftButton, pos=QPoint(8, 8))
    QTest.qWait(tool_rail.LONG_PRESS_MS + 150)
    QTest.mouseRelease(text, Qt.MouseButton.LeftButton, pos=QPoint(8, 8))
    assert asked[-1] == "long" and window.canvas.interaction_mode == "shape"  # a long press does not arm
    for menu in window.stage_tools.findChildren(QMenu):
        menu.close()


def test_the_keys_arm_the_tools_when_the_canvas_has_the_keyboard(window) -> None:
    rail = window.stage_tools
    seen = []
    rail.modeRequested.connect(seen.append)
    for shortcut in rail._shortcuts:  # what the keys do, without a real keyboard focus in a headless run
        shortcut.activated.emit()
    assert seen[:3] == ["select", "hand", "anchor"] and set(seen) >= set(GROUPS)
    assert rail.variant("line") == "Arrow" and rail.variant("math") == "Tex"  # the variants' own keys
    assert rail.variant("media") == "SVGMobject" and rail.variant("shape") == "Rectangle"


def test_no_key_of_the_rail_is_one_the_window_already_uses_and_none_takes_ctrl(window) -> None:
    taken = {
        seq.toString()
        for action in window.findChildren(QAction)
        for seq in action.shortcuts()
        if not seq.isEmpty()
    }
    mine = [s.key().toString() for s in window.stage_tools._shortcuts]
    assert len(set(mine)) == len(mine) and not set(mine) & taken
    assert all("Ctrl" not in key and "Alt" not in key for key in mine)
    assert QKeySequence("Shift+A").toString() in taken  # the Add object card has its own


def test_escape_cancels_an_armed_tool(window) -> None:
    window.stage_tool_buttons["text"].click()
    assert window.canvas.interaction_mode == "text"
    window.canvas.setFocus()
    QTest.keyClick(window.canvas, Qt.Key.Key_Escape)
    assert window.canvas.interaction_mode == "select" and window.stage_tool_buttons["select"].isChecked()


def test_a_short_stage_folds_the_insert_tools_into_one_button(window, qt_app) -> None:
    rail, column = window.stage_tools, window.stage_tool_column
    assert not rail.folded and all(not b.isHidden() for b in rail.insert_buttons)
    column.fit_to(rail.folded_height() + 2 * column.MARGIN_VERTICAL)
    assert rail.folded and not rail.fold_button.isHidden() and all(b.isHidden() for b in rail.insert_buttons)
    assert rail.height() == rail.folded_height()
    rail.fold_button.click()  # arms the group used last
    assert window.canvas.interaction_mode == "shape" and rail.fold_button.isChecked()
    menu = rail.flyout(tool_rail.INSERT)
    assert [a.text() for a in menu.actions()] == [g.title for g in catalogue.INSERT_GROUPS]
    column.fit_to(rail.full_height() + 2 * column.MARGIN_VERTICAL + 4)
    assert not rail.folded and rail.buttons["shape"].isChecked()


def test_the_rail_fits_the_smallest_window_without_covering_the_stage(window, qt_app) -> None:
    window.resize(1024, 640)
    qt_app.processEvents()
    rail, column = window.stage_tools, window.stage_tool_column
    assert rail.folded or rail.height() <= column.height() - 2 * column.MARGIN_VERTICAL
    assert rail.height() <= column.height()
    assert window.canvas.geometry().left() >= column.geometry().width() - 1
