"""The roadmap's "smallest useful v1", end to end through the editor's own UI.

Write an equation, move it, morph it into a second equation, fade it out,
export MP4 — without touching code or JSON. Every step goes through a menu,
a panel field, a timeline context menu or a mouse drag on the canvas, with the
real build worker (LaTeX) and the real renderer process.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time
import uuid

import av
import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication

from manim_studio.core.engine.evaluator import layer_transform
from manim_studio.ui.main_window import MainWindow
from manim_studio.ui.timeline.view import ROW_HEIGHT, RULER_HEIGHT

pytestmark = [pytest.mark.ui, pytest.mark.latex, pytest.mark.slow]  # starts real processes


def wait_until(qt_app, condition, timeout: float = 90.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("timed out")
        qt_app.processEvents()
        time.sleep(0.01)


def menu_action(menu, *path: str):
    for title in path:
        found = next(  # skip section headers: the library has a "Text" section and a Text item
            a for a in menu.actions() if a.text().replace("&", "") == title and not a.isSeparator()
        )
        menu = found.menu() or found
    return found


def timeline_menu(window, layer_id: str, t: float):
    timeline = window.timeline
    row_y = RULER_HEIGHT + timeline.row_of(layer_id) * ROW_HEIGHT + ROW_HEIGHT / 2
    return timeline.context_menu(QPointF(timeline.mapFromScene(QPointF(timeline.scale.x(t), row_y))))


def type_latex(window, qt_app, latex: str) -> None:
    field = window.properties.fields["params.text"]
    field.widget.setFocus()
    field.widget.setPlainText(latex)
    QApplication.sendEvent(
        field.widget, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    )
    layer_id = window.properties.layer_id
    wait_until(qt_app, lambda: window.project.layer(layer_id).spec.params["text"] == latex)


def drag_on_canvas(window, qt_app, start, end) -> None:
    canvas = window.canvas
    a, b = (canvas.units_transform().map(QPointF(*p)) for p in (start, end))
    for kind, pos in (
        (QEvent.Type.MouseButtonPress, a),
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


@pytest.fixture
def window(qt_app, monkeypatch):
    monkeypatch.setenv("MANIM_STUDIO_WORKER", "1")
    win = MainWindow()
    win.resize(1280, 820)
    win.show()
    yield win
    win.close()


def test_smallest_useful_v1(window, qt_app, tmp_path) -> None:
    tag = uuid.uuid4().hex[:4]  # fresh LaTeX, so the worker really builds it
    menu_action(window.menuBar(), "File", "New").trigger()

    # 1. write an equation, and make it appear with Write
    menu_action(window.layers.library_menu, "MathTex").trigger()
    wait_until(qt_app, lambda: len(window.project.layers) == 1)
    first = window.project.layers[0].id
    type_latex(window, qt_app, rf"a^2 + b^2 = c^2 \;\, \text{{{tag}}}")
    menu_action(timeline_menu(window, first, 0.1), "Add clip", "Appear / disappear", "Write").trigger()

    # 2. move it (on the canvas, after the Write has finished)
    window.seek(1.5)
    drag_on_canvas(window, qt_app, (0.0, 0.0), (0.0, 1.5))
    assert window.project.layer(first).base.position == pytest.approx((0.0, 1.5), abs=0.05)

    # 3. a second equation to morph into
    menu_action(window.layers.library_menu, "MathTex").trigger()
    wait_until(qt_app, lambda: len(window.project.layers) == 2)
    second = window.project.layers[1].id
    type_latex(window, qt_app, rf"c = \sqrt{{a^2 + b^2}} \;\, \text{{{tag}}}")
    menu_action(
        timeline_menu(window, first, 2.0),
        "Add clip",
        "Turn into",
        "Transform",
        window.project.layer(second).label,
    ).trigger()

    # 4. fade it out
    menu_action(timeline_menu(window, second, 4.0), "Add clip", "Appear / disappear", "FadeOut").trigger()

    project = window.project
    morph = next(c for c in project.layer(first).clips if c.kind == "Transform")
    fade = project.layer(second).clips[0]
    assert (morph.to_layer, fade.kind) == (second, "FadeOut")
    assert project.lifetime(second)[0] == pytest.approx(morph.end)  # appears when the morph ends
    assert layer_transform(project.layer(first), 1.5).position == pytest.approx((0.0, 1.5), abs=0.05)

    # 5. export
    window.show_export_dialog()
    dialog = window.export_dialog
    out = tmp_path / "v1.mp4"
    dialog.path.setText(str(out))
    dialog.start()
    wait_until(qt_app, lambda: not dialog.running)
    assert dialog.status.text().startswith("Exported to"), dialog.status.text()
    with av.open(str(out)) as container:
        frames = [f.to_ndarray(format="rgb24") for f in container.decode(video=0)]
    canvas = project.canvas
    assert len(frames) == round(canvas.duration * canvas.fps)
    ink = [float(np.abs(f.astype(int) - frames[0][0, 0].astype(int)).sum()) for f in frames]
    second_of = int(canvas.fps)
    assert ink[0] < ink[int(1.5 * second_of)]  # written in
    assert ink[int(4.9 * second_of)] < ink[int(3.5 * second_of)]  # faded out at the end
