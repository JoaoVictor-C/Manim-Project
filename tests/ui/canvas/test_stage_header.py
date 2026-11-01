"""The Stage card's header (ADR 0084): Scene | Game, Follow playhead, Fit / 75 % / 100 %, full screen, and no
prose over the picture."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QAction, QKeySequence

from manim_studio.core.model.schema import Canvas, Layer, Project, Spec, Transform2D
from manim_studio.ui.canvas import canvas as canvas_module
from manim_studio.ui.canvas.stage_header import ACTUAL, FIT, GAME, SCENE, THREE_QUARTERS
from manim_studio.ui.main_window import MainWindow

pytestmark = pytest.mark.ui


def scene() -> Project:
    return Project(
        canvas=Canvas(width_px=640, height_px=360, fps=10, duration=4.0),
        layers=[
            Layer(id="sq", spec=Spec(type="Square", params={"side_length": 1.0})),
            Layer(
                id="camera", name="Camera", spec=Spec(type="Camera"), base=Transform2D(position=(1.0, 0.0))
            ),
        ],
    )


@pytest.fixture
def window(qt_app, tmp_path):
    path = tmp_path / "scene.json"
    path.write_text(scene().model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.resize(1440, 900)
    win.show()
    win.load(path)
    qt_app.processEvents()
    yield win
    win.close()


def test_the_view_control_and_the_game_view_action_stay_in_step(window, qt_app) -> None:
    header = window.stage_header
    assert header.view_seg.currentIndex() == GAME and window.game_view_action.isChecked()
    header.view_seg.button(SCENE).click()  # the control drives the action, which drives the canvas
    assert not window.game_view_action.isChecked() and window.canvas.scene_view
    window.game_view_action.setChecked(True)  # the menu (or G) drives the control
    assert header.view_seg.currentIndex() == GAME and header.view_seg.button(GAME).isChecked()
    assert not window.canvas.scene_view


def test_the_view_has_a_g_shortcut_that_nothing_else_uses(window) -> None:
    assert window.game_view_action.shortcut() == QKeySequence("G")
    assert window.layout_guides_action.shortcut() == QKeySequence("Ctrl+'")
    owners: dict[str, list[str]] = {}
    for action in window.findChildren(QAction):
        for key in ("G", "Ctrl+'"):
            if action.shortcut() == QKeySequence(key):
                owners.setdefault(key, []).append(action.text())
    assert [len(v) for v in owners.values()] == [1, 1], owners


def test_the_explanation_is_a_tooltip_and_a_status_hint_never_over_the_picture(window, qt_app) -> None:
    assert "camera" in window.stage_header.view_seg.toolTip().lower()
    assert not hasattr(window.canvas, "_paint_turned_notice")  # no banner is painted over the video
    window.game_view_action.setChecked(False)
    assert "Scene view" in window.statusBar().currentMessage()
    window.game_view_action.setChecked(True)
    assert "Game view" in window.statusBar().currentMessage()


def test_a_moved_camera_says_why_in_a_chip_of_the_header(window, qt_app) -> None:
    window.seek(0.0)
    qt_app.processEvents()
    assert window.canvas.camera_turned
    assert window.canvas.notice() == canvas_module.MOVED_NOTICE
    assert window.stage_header.notice_chip.toolTip() == canvas_module.MOVED_NOTICE
    assert not window.stage_header.notice_chip.isHidden()
    window.game_view_action.setChecked(False)  # Scene view is flat: handles work, nothing to explain
    qt_app.processEvents()
    assert window.canvas.notice() == "" and window.stage_header.notice_chip.isHidden()


def test_fit_75_and_100_set_the_zoom_and_follow_it(window, qt_app) -> None:
    header, canvas = window.stage_header, window.canvas
    assert header.current_zoom() == FIT and header.zoom_seg.button(FIT).isChecked()
    header.zoom_seg.button(THREE_QUARTERS).click()
    assert not canvas.view.fit and canvas.view.scale == pytest.approx(0.75)
    header.zoom_seg.button(ACTUAL).click()
    assert canvas.view.scale == pytest.approx(1.0) and header.zoom_seg.button(ACTUAL).isChecked()
    canvas.zoom(1.2)  # the wheel: none of the three is current
    qt_app.processEvents()
    assert header.current_zoom() is None
    assert not any(header.zoom_seg.button(k).isChecked() for k in range(3))
    header.zoom_seg.button(ACTUAL).click()  # a preset can be picked again after a custom zoom
    assert canvas.view.scale == pytest.approx(1.0) and header.zoom_seg.button(ACTUAL).isChecked()
    header.zoom_seg.button(FIT).click()
    assert canvas.view.fit and header.zoom_seg.button(FIT).isChecked()
    assert "%" in header.zoom_seg.button(FIT).toolTip()


def test_follow_playhead_chip_toggles_the_action_both_ways(window) -> None:
    chip = window.stage_header.follow_chip
    assert chip.isChecked() and window.follow_action.isChecked()
    chip.click()
    assert not window.follow_action.isChecked() and not window.timeline.follow_playhead
    window.follow_action.setChecked(True)
    assert chip.isChecked()


def test_full_screen_is_a_stage_header_button(window) -> None:
    button = window.fullscreen_button
    assert button is window.stage_header.fullscreen_button
    assert window.viewer_card.isAncestorOf(button)


def test_a_narrow_stage_header_drops_the_readout_first_and_keeps_the_view_and_zoom(window, qt_app) -> None:
    header = window.stage_header
    header.setFixedWidth(2000)
    qt_app.processEvents()
    assert not header.readout.isHidden() and not header.follow_chip.isHidden()
    header.setFixedWidth(330)
    qt_app.processEvents()
    assert header.readout.isHidden()
    assert not header.view_seg.isHidden() and not header.zoom_seg.isHidden()
    assert not header.fullscreen_button.isHidden()
    header.setFixedWidth(2000)
    qt_app.processEvents()
    assert not header.readout.isHidden()  # and they come back


def test_the_readout_keeps_the_frame_and_zoom_text(window) -> None:
    text = window.time_label.text()
    assert "frame" in text and window.canvas.zoom_label() in text


def test_the_camera_rectangle_has_a_size_chip_and_a_follow_point(window, qt_app) -> None:
    window.game_view_action.setChecked(False)
    window.seek(0.0)
    qt_app.processEvents()
    view = window.canvas.evaluator.camera_view(0.0)
    assert window.canvas.camera_chip_text(view) == "Size 4.0 \u00b7 16:9"
    assert window.canvas.camera_follow_point() is None
    window.canvas.grab()  # paints the gizmo with halo, cross and chip without raising
    window.selection.set("camera")
    qt_app.processEvents()
    window.canvas.grab()
