"""The camera in the window (P7.5, ADR 0048): Properties' Camera rows, the canvas seen from the
camera (no handles while it is turned), render-ahead frames equal to live ones, the preview
process's renderer."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import base64
import io
import json
import zlib

import numpy as np
import pytest

pytest.importorskip("PySide6")

from tests.ui.test_multiselect_ui import click
from tests.ui.test_render_ahead import FakePreview, shown, wait

from manim_studio.core.schema import Camera, Canvas, Clip, Cue, Layer, Project, Spec, Transform2D
from manim_studio.preview import Renderer
from manim_studio.render.cairo_export import render_frame
from manim_studio.render.preview import PreviewView, StudioThreeDCamera, preview_camera
from manim_studio.ui import main_window as mw
from manim_studio.ui.canvas import TURNED_NOTICE
from manim_studio.ui.main_window import MainWindow

pytestmark = pytest.mark.ui

FILLED = {"fill": "#3b82f6", "fill_opacity": 1.0}


def scene() -> Project:
    return Project(
        canvas=Canvas(width_px=320, height_px=180, fps=10, duration=2.0),
        layers=[
            Layer(id="sq", spec=Spec(type="Square", params={"side_length": 2.0}, style=FILLED)),
            Layer(
                id="ring",
                spec=Spec(type="Circle", params={"radius": 0.5}),
                base=Transform2D(position=(4.0, 1.0)),
                clips=[Clip(id="in", kind="Create", start=0.0, duration=1.0)],
            ),
        ],
        subtitles=[Cue(id="cue", start=0.0, end=2.0, text="Hello")],
    )


@pytest.fixture
def window(qt_app, tmp_path, monkeypatch):
    fakes: list[FakePreview] = []
    monkeypatch.setattr(
        mw, "make_preview", lambda cache_dir, parent: fakes.append(FakePreview()) or fakes[-1]
    )
    path = tmp_path / "camera.json"
    path.write_text(scene().model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.resize(1000, 700)
    win.show()
    win.load(path)
    qt_app.processEvents()
    win.move_tool.snapping = False
    win.fakes = fakes
    yield win
    win.close()


def live(window, t: float) -> np.ndarray:
    evaluator = window.evaluator
    camera = preview_camera(window.canvas.preview_view(), window.project.camera)
    return render_frame(camera, [mob for _, mob in evaluator.frame_layers(t)], evaluator.overlay(t))


def turn(window, qt_app, phi: float = 60.0) -> None:
    window.selection.clear()
    window.properties.show_nothing()
    window.properties.fields["camera.phi"].commit(phi)
    qt_app.processEvents()


def test_properties_shows_the_camera_and_edits_it_in_one_undo_step(window, qt_app) -> None:
    window.selection.clear()
    fields = window.properties.fields
    assert {"camera.phi", "camera.theta", "camera.gamma"} <= set(fields)
    assert fields["camera.theta"].widget.value() == -90.0
    assert fields["camera.phi"].widget.toolTip()
    steps = window.document.undo_stack.count()
    turn(window, qt_app, 45.0)
    assert window.project.camera == Camera(phi=45.0)
    assert window.document.undo_stack.count() == steps + 1
    window.document.undo_stack.undo()
    qt_app.processEvents()
    assert window.project.camera.is_default
    assert window.properties.fields["camera.phi"].widget.value() == 0.0
    window.document.undo_stack.redo()
    window.properties.camera_reset.click()
    qt_app.processEvents()
    assert window.project.camera.is_default


def test_the_canvas_draws_the_turned_camera(window, qt_app) -> None:
    window.seek(0.5)
    flat = shown(window).copy()
    assert np.array_equal(flat, live(window, 0.5))
    turn(window, qt_app)
    window.seek(0.5)
    assert isinstance(window.canvas._camera, StudioThreeDCamera)
    assert np.array_equal(shown(window), live(window, 0.5))
    assert np.abs(shown(window).astype(int) - flat.astype(int)).mean() > 1.0
    window.properties.camera_reset.click()
    qt_app.processEvents()
    window.seek(0.5)
    assert type(window.canvas._camera).__name__ == "Camera"
    assert np.array_equal(shown(window), flat)  # back to the 2D camera, bit for bit


def test_a_turned_camera_hides_handles_and_ignores_clicks(window, qt_app) -> None:
    window.selection.set("sq")
    window.seek(0.5)
    assert window.canvas.outline is not None
    turn(window, qt_app)
    window.selection.set("sq")
    window.seek(0.5)
    assert window.canvas.camera_turned
    assert (
        window.canvas.outline is None and window.canvas.param_handles == [] and window.canvas.motion is None
    )
    window.selection.clear()
    click(window, 0.0, 0.0, qt_app)  # where the square is in flat units
    assert window.selection.layer_id is None
    before = window.canvas.view
    window.canvas.frame_selection()  # F: the whole frame, not the flat bounds
    assert window.canvas.view == before or window.canvas.view.scale is None
    window.canvas.grab()  # paints the notice without error
    assert "Camera turned" in TURNED_NOTICE
    window.properties.camera_reset.click()
    qt_app.processEvents()
    click(window, 0.0, 0.0, qt_app)
    assert window.selection.layer_id == "sq"
    assert window.canvas.outline is not None


def test_render_ahead_frames_follow_the_camera(window, qt_app) -> None:
    fake = window.fakes[0]
    fake.deliver()
    store = window.render_ahead.store
    assert len(store) == 20
    turn(window, qt_app)
    assert len(store) == 0  # a camera change changes every frame
    wait(qt_app, 0.3)
    assert fake.project.camera == Camera(phi=60.0)
    fake.deliver()
    window.seek(1.0)
    assert window.canvas.from_cache
    assert np.array_equal(shown(window), live(window, 1.0))


def renderer_frame(project: Project, view: PreviewView, index: int, renderer: Renderer | None = None):
    out = io.StringIO()
    renderer = renderer or Renderer(out)
    renderer.protocol = out
    renderer.apply({"project": json.loads(project.model_dump_json(by_alias=True)), "generation": 1})
    renderer.apply({"view": view.to_json(), "view_id": 1})
    renderer.apply({"want": [index]})
    renderer.render_next()
    message = json.loads(out.getvalue().splitlines()[-1])
    pixels = np.frombuffer(zlib.decompress(base64.b64decode(message["data"])), np.uint8)
    return pixels.reshape(message["height"], message["width"], 4), renderer


def test_the_preview_processs_renderer_draws_the_canvas_frames(window, qt_app) -> None:
    """The process's own code, in this process: its frames are the canvas's, flat and turned."""
    window.seek(0.5)
    view = window.canvas.preview_view()
    pixels, renderer = renderer_frame(window.project, view, 5)
    assert np.array_equal(pixels, live(window, 0.5))
    turn(window, qt_app)
    window.seek(0.5)
    turned, renderer = renderer_frame(window.project, view, 5, renderer)  # the camera follows the project
    assert np.array_equal(turned, live(window, 0.5))
    assert not np.array_equal(turned, pixels)
