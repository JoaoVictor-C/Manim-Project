"""The motion path on the canvas (P3d.2, ADR 0026): keys, handles, smooth/straight."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPointF, Qt

from manim_studio.core.schema import Canvas, Keyframe, Layer, Project, Spec
from manim_studio.ui.main_window import MainWindow
from ui.test_canvas_tools import drag, mouse, px

pytestmark = pytest.mark.ui

KEYS = [Keyframe(t=0, value=(-4.0, -1.0)), Keyframe(t=1, value=(0.0, 1.5)), Keyframe(t=2, value=(4.0, -1.0))]


@pytest.fixture
def window(qt_app, tmp_path):
    project = Project(
        canvas=Canvas(width_px=640, height_px=360, fps=30, duration=4.0),
        layers=[Layer(id="dot", spec=Spec(type="Dot", params={"radius": 0.15}), tracks={"position": KEYS})],
    )
    path = tmp_path / "motion.json"
    path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.resize(1100, 800)
    win.show()
    win.load(path)
    win.seek(3.0)  # the dot rests at the last key; the squares of the first two are free
    win.selection.set("dot")
    qt_app.processEvents()
    yield win
    win.close()


def key(window, index: int):
    return window.project.layer("dot").tracks["position"][index]


def test_the_motion_path_shows_for_the_selected_keyed_layer(window, qt_app) -> None:
    motion = window.canvas.motion
    assert motion is not None and len(motion.keys) == 3
    assert motion.keys[1].point == pytest.approx((0.0, 1.5))
    window.play()
    qt_app.processEvents()
    window.refresh()
    assert window.canvas.motion is None  # hidden while playing
    window.pause()
    assert window.canvas.motion is not None


def test_dragging_a_key_square_moves_that_key(window, qt_app) -> None:
    start = px(window, 0.0, 1.5)
    drag(window, start, start + QPointF(0, -40), qt_app)
    assert key(window, 1).value[1] > 1.5 + 0.3
    assert key(window, 1).value[0] == pytest.approx(0.0, abs=1e-6)
    assert window.document.undo_stack.undoText() == "Move key"
    assert window.selection.layer_id == "dot"


def test_double_click_makes_a_key_smooth_then_straight(window, qt_app) -> None:
    mouse(window, QEvent.Type.MouseButtonDblClick, px(window, 0.0, 1.5))
    middle = key(window, 1)
    assert np.allclose(middle.out_tangent, (8 / 6, -0.0)) and np.allclose(middle.in_tangent, (-8 / 6, 0.0))
    assert window.document.undo_stack.undoText() == "Smooth key"
    mouse(window, QEvent.Type.MouseButtonDblClick, px(window, 0.0, 1.5))
    assert not key(window, 1).curved
    assert window.document.undo_stack.undoText() == "Straighten key"


def test_bending_keeps_a_smooth_key_aligned_unless_alt(window, qt_app) -> None:
    mouse(window, QEvent.Type.MouseButtonDblClick, px(window, 0.0, 1.5))  # smooth
    qt_app.processEvents()
    handle = window.canvas.motion.keys[1].out_handle
    start = px(window, *handle)
    drag(window, start, start + QPointF(0, -60), qt_app)  # pull the out handle up
    bent = key(window, 1)
    out, inn = np.array(bent.out_tangent), np.array(bent.in_tangent)
    assert out[1] > 0.5  # it now points up and right
    assert np.allclose(inn / np.linalg.norm(inn), -out / np.linalg.norm(out))  # still opposite
    assert np.linalg.norm(inn) == pytest.approx(8 / 6)  # with its own length
    assert window.document.undo_stack.undoText() == "Bend path"
    handle = window.canvas.motion.keys[1].in_handle
    start = px(window, *handle)
    drag(window, start, start + QPointF(0, 50), qt_app, Qt.KeyboardModifier.AltModifier)
    broken = key(window, 1)
    assert np.allclose(broken.out_tangent, out)  # Alt moved only the dragged handle
    assert not np.allclose(broken.in_tangent, inn)
