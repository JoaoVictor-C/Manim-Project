"""Scene view and Game view (ADR 0083): the camera gizmo dragged with the mouse, the Properties rows."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication
from tests.ui.services.test_render_ahead import FakePreview, shown

from manim_studio.core.engine.evaluator import Evaluator, camera_size
from manim_studio.core.model.schema import Canvas, Keyframe, Layer, Project, Spec, Transform2D
from manim_studio.render.cairo_export import render_frame
from manim_studio.render.preview import preview_camera
from manim_studio.ui import main_window as mw
from manim_studio.ui.canvas import viewport
from manim_studio.ui.canvas.camera_gizmo import ICON_PX, icon_point
from manim_studio.ui.canvas.canvas import MOVED_NOTICE
from manim_studio.ui.main_window import MainWindow

pytestmark = pytest.mark.ui

NONE = Qt.KeyboardModifier.NoModifier
FILLED = {"fill": "#3b82f6", "fill_opacity": 1.0}


def scene() -> Project:
    return Project(
        canvas=Canvas(width_px=640, height_px=360, fps=10, duration=4.0),
        layers=[
            Layer(id="sq", spec=Spec(type="Square", params={"side_length": 1.0}, style=FILLED)),
            Layer(
                id="camera",
                name="Camera",
                spec=Spec(type="Camera"),
                base=Transform2D(position=(1.0, 0.0)),
            ),
        ],
    )


@pytest.fixture
def window(qt_app, tmp_path, monkeypatch):
    monkeypatch.setattr(mw, "make_preview", lambda cache_dir, parent: FakePreview())
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


def mouse(window, kind, pos: QPointF) -> None:
    canvas = window.canvas
    button = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseMove else Qt.MouseButton.LeftButton
    buttons = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease else Qt.MouseButton.LeftButton
    global_pos = QPointF(canvas.mapToGlobal(pos.toPoint()))
    QApplication.sendEvent(canvas, QMouseEvent(kind, pos, global_pos, button, buttons, NONE))


def drag(window, qt_app, start, end, steps=(0.3, 0.7, 1.0)) -> None:
    a, b = px(window, *start), px(window, *end)
    mouse(window, QEvent.Type.MouseButtonPress, a)
    for f in steps:
        mouse(window, QEvent.Type.MouseMove, a + (b - a) * f)
        qt_app.processEvents()
    mouse(window, QEvent.Type.MouseButtonRelease, b)
    qt_app.processEvents()


def scene_view(window, qt_app) -> None:
    window.game_view_action.setChecked(False)
    window.canvas.set_view(viewport.View(fit=False, scale=0.3, centre=(0.0, 0.0)))  # the gizmo fits
    window.seek(window.t)
    qt_app.processEvents()


def camera(window) -> Layer:
    return window.project.layer("camera")


def test_the_view_menu_toggle_is_there_and_remembered(window) -> None:
    assert window.game_view_action.isChecked() and not window.canvas.scene_view
    assert ("game_view", window.game_view_action, True) in window._toggles()
    window.game_view_action.setChecked(False)
    assert window.canvas.scene_view


def test_game_view_hides_handles_and_points_to_the_scene_view(window, qt_app) -> None:
    window.selection.set("sq")
    window.seek(0.0)
    assert window.canvas.camera_turned and window.canvas.outline is None
    assert "Scene view" in MOVED_NOTICE
    window.canvas.grab()


def test_scene_view_draws_the_flat_scene_with_handles(window, qt_app) -> None:
    scene_view(window, qt_app)
    window.selection.set("sq")
    window.seek(0.0)
    canvas = window.canvas
    assert not canvas.camera_turned and canvas.outline is not None
    flat = Project(canvas=window.project.canvas, layers=[window.project.layer("sq")])
    evaluator = Evaluator(flat)
    expected = render_frame(
        preview_camera(canvas.preview_view(), flat.camera), [m for _, m in evaluator.frame_layers(0.0)]
    )
    assert np.array_equal(shown(window), expected)
    window.game_view_action.setChecked(True)
    qt_app.processEvents()
    assert canvas.camera_turned and not np.array_equal(shown(window), expected)
    window.canvas.grab()


def test_the_camera_icon_selects_it_and_the_gizmo_shows_handles(window, qt_app) -> None:
    scene_view(window, qt_app)
    window.selection.clear()
    qt_app.processEvents()
    box = window.canvas.camera_box()
    assert box is not None and np.allclose(box.centre, (1.0, 0.0))
    icon = icon_point(box, ICON_PX / window.canvas.px_per_unit())
    mouse(window, QEvent.Type.MouseButtonPress, px(window, *icon))
    mouse(window, QEvent.Type.MouseButtonRelease, px(window, *icon))
    qt_app.processEvents()
    assert window.selection.layer_id == "camera" and window.canvas.camera_selected()
    window.canvas.grab()  # paints the handles


def test_dragging_the_gizmo_moves_the_camera_in_one_undo_step(window, qt_app) -> None:
    scene_view(window, qt_app)
    window.selection.set("camera")
    qt_app.processEvents()
    steps = window.document.undo_stack.count()
    drag(window, qt_app, (-2.0, 2.0), (-1.0, 1.5))
    assert camera(window).base.position == pytest.approx((2.0, -0.5), abs=1e-6)
    assert window.document.undo_stack.count() == steps + 1
    window.document.undo_stack.undo()
    assert camera(window).base.position == (1.0, 0.0)


def test_dragging_a_keyed_camera_sets_a_key_at_the_playhead(window, qt_app) -> None:
    keyed = camera(window).model_copy(
        update={
            "tracks": {"position": [Keyframe(t=0.0, value=(0.0, 0.0)), Keyframe(t=2.0, value=(2.0, 0.0))]}
        }
    )
    window.document.replace(window.project.model_copy(update={"layers": [window.project.layer("sq"), keyed]}))
    scene_view(window, qt_app)
    window.seek(3.0)  # after the last key: the camera rests at (2, 0)
    window.selection.set("camera")
    qt_app.processEvents()
    drag(window, qt_app, (0.0, 2.0), (1.0, 2.0))
    keys = camera(window).tracks["position"]
    assert [k.t for k in keys] == [0.0, 2.0, 3.0]
    assert keys[-1].value == pytest.approx((3.0, 0.0), abs=1e-6)


def test_a_corner_changes_the_size_and_the_knob_rolls_it(window, qt_app) -> None:
    scene_view(window, qt_app)
    window.selection.set("camera")
    qt_app.processEvents()
    box = window.canvas.camera_box()
    corner = box.corners[2]
    centre = box.centre
    drag(window, qt_app, tuple(corner), tuple(centre + (corner - centre) * 1.5))
    size = camera_size(camera(window).base.scale, window.project.canvas.frame_height)
    assert size == pytest.approx(6.0, rel=0.02)  # 4 -> 6: it sees more
    box = window.canvas.camera_box()
    knob = box.knob(24.0 / window.canvas.px_per_unit())
    radius = float(np.linalg.norm(knob - box.centre))
    left = box.centre + np.array([-radius, 0.0])
    steps = window.document.undo_stack.count()
    drag(window, qt_app, tuple(knob), tuple(left), steps=(0.25, 0.5, 0.75, 1.0))
    assert camera(window).base.rotation == pytest.approx(90.0, abs=1.0)
    assert window.document.undo_stack.count() == steps + 1


def test_properties_shows_the_camera_like_a_2d_camera(window, qt_app) -> None:
    window.selection.set("camera")
    qt_app.processEvents()
    fields = window.properties.fields
    assert {"base.position", "base.scale", "base.rotation", "params.background", "params.follow"} <= set(
        fields
    )
    assert "base.opacity" not in fields and "base.anchor" not in fields and "lifetime.in" not in fields
    assert "Style" not in window.properties.sections
    assert fields["base.scale"].widget.value() == pytest.approx(4.0)  # the size, not the scale
    fields["base.scale"].commit(2.0)
    qt_app.processEvents()
    assert camera(window).base.scale == pytest.approx(2.0)
    fields = window.properties.fields
    fields["params.background"].commit("#ff0000")
    qt_app.processEvents()
    assert window.project.view_background == "#ff0000"
    window.properties.fields["params.follow"].commit("sq")
    qt_app.processEvents()
    assert camera(window).spec.params["follow"] == "sq"
    window.properties.fields["params.follow"].commit(None)
    qt_app.processEvents()
    assert "follow" not in camera(window).spec.params
