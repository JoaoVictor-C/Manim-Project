"""The camera layer in the window (ADR 0072): adding it, and the canvas guard while it moves the view."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from manim_studio.core.model.schema import Canvas, Layer, Project, Spec, Transform2D
from manim_studio.ui.main_window import MainWindow

pytestmark = pytest.mark.ui


def scene() -> Project:
    square = Layer(id="a", spec=Spec(type="Square", params={"side_length": 1.0}))
    return Project(canvas=Canvas(width_px=640, height_px=360, fps=30, duration=4.0), layers=[square])


@pytest.fixture
def window(qt_app, tmp_path):
    path = tmp_path / "scene.json"
    path.write_text(scene().model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.resize(1100, 800)
    win.show()
    win.load(path)
    qt_app.processEvents()
    yield win
    win.close()


def test_adding_the_camera_from_the_layers_panel_is_one_undo_step(window, qt_app) -> None:
    window.layers.add_camera()
    qt_app.processEvents()
    assert [layer.is_camera for layer in window.document.project.layers] == [False, True]
    window.layers.add_camera()  # a second one is refused, nothing changes
    qt_app.processEvents()
    assert len(window.document.project.layers) == 2
    window.document.undo_stack.undo()
    qt_app.processEvents()
    assert len(window.document.project.layers) == 1


def test_the_canvas_stops_editing_by_hand_while_the_camera_moves_the_view(window, qt_app) -> None:
    window.layers.add_camera()
    qt_app.processEvents()
    assert not window.canvas.camera_turned  # at rest
    layers = window.document.project.layers
    moved = layers[1].model_copy(update={"base": Transform2D(position=(1.0, 0.0))})
    window.document.replace(window.document.project.model_copy(update={"layers": [layers[0], moved]}))
    qt_app.processEvents()
    assert window.canvas.camera_turned  # outlines and handles would be drawn in the wrong place
