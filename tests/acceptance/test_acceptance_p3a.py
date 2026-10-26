"""P3a acceptance: zoom into a small term, scale it there, fit back (ADR 0023).

An equation written and split into terms through the UI. At Fit the handles of
one term sit close together; Ctrl+wheel over the term zooms in about it until it
is shown at 400 % and more, where its handles are far apart; a corner drag
scales it; the View menu's Fit returns. The export shows what the editor shows,
whatever the view was.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import math
import uuid

import av
import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QApplication

from acceptance.test_acceptance_p2e import add_equation
from acceptance.test_acceptance_v1 import menu_action, wait_until
from manim_studio.render.cairo_export import frame_times, make_camera, render_frame
from manim_studio.ui.main_window import MainWindow

pytestmark = [pytest.mark.ui, pytest.mark.latex, pytest.mark.slow]  # starts real processes


@pytest.fixture
def window(qt_app, monkeypatch):
    monkeypatch.setenv("MANIM_STUDIO_WORKER", "1")
    win = MainWindow()
    win.resize(1280, 820)
    win.show()
    yield win
    win.close()


def corners_px(window) -> list[QPointF]:
    to_px = window.canvas.units_transform()
    return [to_px.map(QPointF(*c)) for c in window.canvas.outline.box.corners]


def ctrl_wheel(window, pos: QPointF) -> None:
    canvas = window.canvas
    QApplication.sendEvent(
        canvas,
        QWheelEvent(
            pos,
            QPointF(canvas.mapToGlobal(pos.toPoint())),
            QPoint(0, 0),
            QPoint(0, 120),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.ControlModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        ),
    )


def drag(window, qt_app, a: QPointF, b: QPointF) -> None:
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
        QApplication.sendEvent(
            canvas, QMouseEvent(kind, pos, global_pos, button, buttons, Qt.KeyboardModifier.NoModifier)
        )
        qt_app.processEvents()


def test_zoom_into_a_term_scale_it_and_fit_back(window, qt_app, tmp_path) -> None:
    tag = uuid.uuid4().hex[:4]  # fresh LaTeX: the worker really builds it
    menu_action(window.menuBar(), "File", "New").trigger()
    eq = add_equation(window, qt_app, rf"a^2 + b^2 = c^2 + \text{{{tag}}}")
    b2 = next(layer.id for layer in window.project.children(eq) if layer.part.tex == "b^2")
    window.selection.select_layer(b2)
    qt_app.processEvents()
    canvas = window.canvas
    assert canvas.view.fit
    at_fit = corners_px(window)
    width_at_fit = math.dist(at_fit[0].toTuple(), at_fit[1].toTuple())

    # Ctrl+wheel over the term until it is shown at 400 % or more; the term stays under the cursor
    term = canvas.units_transform().map(QPointF(*canvas.outline.box.centre))
    under = canvas.to_units(term)
    while canvas.geometry_now().scale < 4.0:
        ctrl_wheel(window, term)
        qt_app.processEvents()
    assert canvas.to_units(term) == pytest.approx(under)
    assert int(canvas.zoom_label().rstrip(" %")) >= 400
    zoomed = corners_px(window)
    width_zoomed = math.dist(zoomed[0].toTuple(), zoomed[1].toTuple())
    assert width_zoomed > 6 * width_at_fit  # the handles are well apart now

    # scale the term with its top-right corner, 1.5x from its pivot
    pivot = canvas.units_transform().map(QPointF(*canvas.outline.anchor))
    corner = zoomed[2]
    drag(window, qt_app, corner, pivot + (corner - pivot) * 1.5)
    assert window.project.layer(b2).base.scale == pytest.approx(1.5, abs=0.02)
    assert window.document.undo_stack.undoText() == "Scale layer"

    menu_action(window.menuBar(), "View", "Fit").trigger()
    qt_app.processEvents()
    assert canvas.view.fit and canvas.zoom_label().startswith("Fit")

    # the export shows exactly what the editor shows
    window.show_export_dialog()
    dialog = window.export_dialog
    out = tmp_path / "p3a.mp4"
    dialog.path.setText(str(out))
    dialog.start()
    wait_until(qt_app, lambda: not dialog.running, timeout=180)
    assert dialog.status.text().startswith("Exported to"), dialog.status.text()
    with av.open(str(out)) as container:
        frames = [f.to_ndarray(format="rgb24") for f in container.decode(video=0)]
    project = window.project
    camera = make_camera(project.canvas)
    times = frame_times(project.canvas)
    for i in (0, len(times) // 2):
        expected = render_frame(camera, window.evaluator.frame(times[i]))[:, :, :3].astype(int)
        assert np.abs(frames[i].astype(int) - expected).mean() < 3, times[i]
