"""S2 acceptance: a new MathTex layer with a Write clip, built without editing JSON.

Driven the way a user would, through the editor's own actions and widgets,
with the real build worker (ADR 0015):

File > New -> Layers: Add > MathTex -> Properties: type the equation, Ctrl+Enter
-> Timeline: right-click the row > Add clip > Write -> Save -> render.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json
import time
import uuid

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from manim_studio.core import adapter
from manim_studio.core.evaluator import Evaluator
from manim_studio.core.schema import Project
from manim_studio.render.cairo_export import make_camera, render_frame
from manim_studio.ui.main_window import MainWindow
from manim_studio.ui.timeline.view import ROW_HEIGHT, RULER_HEIGHT
from manim_studio.ui.worker_process import WorkerProcess
from support import max_diff

pytestmark = [pytest.mark.ui, pytest.mark.latex, pytest.mark.slow]  # starts real processes


def wait_until(qt_app, condition, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("timed out waiting")
        qt_app.processEvents()
        time.sleep(0.01)


def menu_action(menu, *path: str):
    for title in path:
        found = next(a for a in menu.actions() if a.text().replace("&", "") == title)
        menu = found.menu() or found
    return found


@pytest.fixture
def window(qt_app, monkeypatch):
    monkeypatch.setenv("MANIM_STUDIO_WORKER", "1")  # the real worker, unlike other UI tests
    win = MainWindow()
    win.resize(1280, 820)
    win.show()
    yield win
    win.close()


def test_mathtex_with_a_write_clip_without_json(window, qt_app, tmp_path) -> None:
    assert isinstance(window.builds.client, WorkerProcess)

    # File > New
    menu_action(window.menuBar(), "File", "New").trigger()
    assert window.project is not None and window.project.layers == []

    # Layers: Add > MathTex (waits for the worker if the default is not warm yet)
    menu_action(window.layers.library_menu, "MathTex").trigger()
    wait_until(qt_app, lambda: len(window.project.layers) == 1)
    layer_id = window.project.layers[0].id
    assert window.layers.selected_id() == layer_id
    assert window.properties.layer_id == layer_id

    # Properties: a new equation (never built before, so the worker must build it)
    equation = rf"\sum_{{k=1}}^{{{uuid.uuid4().int % 10**6}}} k^2"
    field = window.properties.fields["params.text"]
    field.widget.setFocus()
    field.widget.setPlainText(equation)
    QApplication.sendEvent(
        field.widget, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    )
    assert window.builds.busy  # building in the worker; the UI is not blocked
    wait_until(qt_app, lambda: window.project.layers[0].spec.params["text"] == equation)

    # Timeline: right-click the row at 0.5 s > Add clip > Appear / disappear > Write
    timeline = window.timeline
    scene_point = QPointF(timeline.scale.x(0.5), RULER_HEIGHT + timeline.row_of(layer_id) * ROW_HEIGHT + 10)
    menu = timeline.context_menu(QPointF(timeline.mapFromScene(scene_point)))
    menu_action(menu, "Add clip", "Appear / disappear", "Write").trigger()
    clip = window.project.layers[0].clips[0]
    assert (clip.kind, clip.start, clip.duration) == (
        "Write",
        pytest.approx(0.5, abs=1 / 30),
        pytest.approx(1.0),
    )
    assert window.properties.clip_id == clip.id  # the new clip is selected

    # Three undo steps, all named
    stack = window.document.undo_stack
    assert [stack.text(i) for i in range(stack.count())] == [
        "Add MathTex",
        "Change latex (math)",
        "Add Write clip",
    ]

    # Save, reload, and render: the saved file is a valid project that animates
    path = tmp_path / "scene.json"
    window.path = path
    window.save()
    saved = Project.model_validate(json.loads(path.read_text(encoding="utf-8")))
    assert saved == window.project
    camera = make_camera(saved.canvas.model_copy(update={"width_px": 320, "height_px": 180}))
    evaluator = Evaluator(saved)
    before, middle, after = (render_frame(camera, evaluator.frame(t)) for t in (0.2, 1.0, 2.0))
    assert max_diff(before, middle) > 0 and max_diff(middle, after) > 0  # invisible, writing, written
    assert adapter.build_mobject(saved.layers[0].spec) is not None
