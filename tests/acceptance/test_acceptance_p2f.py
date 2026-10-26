"""P2f acceptance: a pendulum swings about its top end (ADR 0021).

A line made through the library, its pivot cross Ctrl+dragged to the line's top
end (Shift snaps it there) without the line moving, rotation keyed -30 -> 30 ->
-30 through the Properties panel: the top end stays put in every frame, the
line swings, and the export shows exactly what the editor shows.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import av
import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from acceptance.test_acceptance_v1 import menu_action, wait_until
from manim_studio.render.cairo_export import frame_times, make_camera, render_frame
from manim_studio.ui.main_window import MainWindow

pytestmark = [pytest.mark.ui, pytest.mark.slow]  # the export starts a real process

CTRL_SHIFT = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier


@pytest.fixture
def window(qt_app):
    win = MainWindow()
    win.resize(1280, 820)
    win.show()
    yield win
    win.close()


def px(window, x: float, y: float) -> QPointF:
    return window.canvas.units_transform().map(QPointF(x, y))


def drag(window, qt_app, a: QPointF, b: QPointF, modifiers) -> None:
    canvas = window.canvas
    for kind, pos in (
        (QEvent.Type.MouseButtonPress, a),
        (QEvent.Type.MouseMove, (a + b) / 2),
        (QEvent.Type.MouseMove, b),
        (QEvent.Type.MouseButtonRelease, b),
    ):
        buttons = (
            Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease else Qt.MouseButton.LeftButton
        )
        button = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseMove else Qt.MouseButton.LeftButton
        global_pos = QPointF(canvas.mapToGlobal(pos.toPoint()))
        QApplication.sendEvent(canvas, QMouseEvent(kind, pos, global_pos, button, buttons, modifiers))
        qt_app.processEvents()


def ends(window, layer_id: str, t: float) -> np.ndarray:
    line = dict(window.evaluator.frame_layers(t))[layer_id]
    return np.array([line.get_start()[:2], line.get_end()[:2]])


def test_a_pendulum_swings_about_its_top_end(window, qt_app, tmp_path) -> None:
    menu_action(window.menuBar(), "File", "New").trigger()
    menu_action(window.layers.library_menu, "Line").trigger()
    layer_id = window.project.layers[0].id
    fields = window.properties.fields
    fields["params.start"].commit((0.0, 0.0))
    fields["params.end"].commit((0.0, -3.0))
    fields["style.stroke_width"].commit(12.0)
    qt_app.processEvents()
    assert ends(window, layer_id, 0.0) == pytest.approx(np.array([[0.0, 1.5], [0.0, -1.5]]))  # built centred

    # Ctrl+drag the pivot cross toward the top; Shift snaps it onto the top end. The line stays put.
    window.selection.select_layer(layer_id)
    qt_app.processEvents()
    drag(window, qt_app, px(window, 0.0, 0.0), px(window, 0.15, 1.3), CTRL_SHIFT)
    layer = window.project.layer(layer_id)
    assert layer.base.anchor == pytest.approx((0.0, 1.5), abs=1e-9)
    assert ends(window, layer_id, 0.0) == pytest.approx(np.array([[0.0, 1.5], [0.0, -1.5]]))
    assert window.document.undo_stack.undoText() == "Move anchor"
    assert window.canvas.outline.anchor == pytest.approx((0.0, 1.5))  # the cross sits on the top end

    # rotation keys -30 -> 30 -> -30 through the Properties panel
    fields["keys.rotation"].commit(True)
    for t, degrees in ((0.0, -30.0), (1.0, 30.0), (2.0, -30.0)):
        window.seek(t)
        window.properties.fields["base.rotation"].commit(degrees)
    keys = window.project.layer(layer_id).tracks["rotation"]
    assert [(k.t, k.value) for k in keys] == [(0.0, -30.0), (1.0, 30.0), (2.0, -30.0)]

    # the top end stays put in every frame while the bottom end swings
    project = window.project
    fps = project.canvas.fps
    bottoms = []
    for i in range(int(2.5 * fps)):
        top, bottom = ends(window, layer_id, i / fps)
        assert top == pytest.approx((0.0, 1.5), abs=1e-9), i
        bottoms.append(bottom[0])
    assert min(bottoms) == pytest.approx(-1.5, abs=1e-6)  # 3 sin(30 deg) to either side
    assert max(bottoms) == pytest.approx(1.5, abs=1e-6)

    # the export shows exactly what the editor shows
    window.show_export_dialog()
    dialog = window.export_dialog
    out = tmp_path / "pendulum.mp4"
    dialog.path.setText(str(out))
    dialog.start()
    wait_until(qt_app, lambda: not dialog.running, timeout=180)
    assert dialog.status.text().startswith("Exported to"), dialog.status.text()
    with av.open(str(out)) as container:
        frames = [f.to_ndarray(format="rgb24") for f in container.decode(video=0)]
    camera = make_camera(project.canvas)
    times = frame_times(project.canvas)
    for t in (0.0, 0.5, 1.0, 1.6):
        i = min(range(len(times)), key=lambda k: abs(times[k] - t))
        expected = render_frame(camera, window.evaluator.frame(times[i]))[:, :, :3].astype(int)
        assert np.abs(frames[i].astype(int) - expected).mean() < 3, t
