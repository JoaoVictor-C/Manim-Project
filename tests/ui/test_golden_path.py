"""The golden path (GP): create a typical animation, save, close, reopen and export it - the
way a user does, through menu actions, buttons, typing and the mouse.

What "excellent" means here, checked:
* every step works and needs few actions (counted);
* the reopened project equals the saved one;
* the exported video has every frame, and its frames are the editor's;
* the exported Python compiles;
* nothing is logged as a warning or an error on the way.
"""

from __future__ import annotations

import logging
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import av
import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog

from manim_studio.core.engine import python_export
from manim_studio.core.engine.evaluator import Evaluator
from manim_studio.core.model.schema import Project
from manim_studio.render.cairo_export import frame_times, make_camera, render_frame
from manim_studio.ui.main_window import MainWindow

pytestmark = [pytest.mark.ui, pytest.mark.slow]


class Recorder(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.records: list[str] = []

    def emit(self, record) -> None:
        self.records.append(f"{record.name}: {record.getMessage()}")


def pump(qt_app, n: int = 5) -> None:
    for _ in range(n):
        qt_app.processEvents()


def wait(qt_app, condition, timeout: float = 60.0) -> None:
    start = time.perf_counter()
    while not condition() and time.perf_counter() - start < timeout:
        qt_app.processEvents()
        time.sleep(0.01)
    assert condition(), "timed out"


def menu(window, *path):
    actions = window.menuBar().actions()
    found = None
    for part in path:
        found = next(a for a in actions if a.text().replace("&", "") == part and not a.isSeparator())
        if found.menu() is not None:
            actions = found.menu().actions()
    return found


def add(window, qt_app, label: str) -> str:
    """Layers > Add > ``label``: the new object's id once it exists (text waits for its build)."""
    count = len(window.project.layers)
    next(
        a for a in window.layers.library_menu.actions() if a.text() == label and not a.isSeparator()
    ).trigger()
    wait(qt_app, lambda: len(window.project.layers) > count)
    pump(qt_app)
    return window.project.layers[-1].id


def type_text(window, qt_app, text: str) -> None:
    """Type into the selected object's text field in Properties and press Return."""
    field = window.properties.fields["params.text"]
    edit = field.widget
    if hasattr(edit, "selectAll") and hasattr(edit, "returnPressed"):
        edit.setFocus()
        edit.selectAll()
        QTest.keyClicks(edit, text)
        QTest.keyClick(edit, Qt.Key.Key_Return)
    else:  # a multi-line LaTeX box
        field.commit(text)
    wait(qt_app, lambda: not window.builds.busy)
    pump(qt_app)


def browse_preset(window, qt_app, name: str) -> None:
    browser = window.show_presets_browser()
    pump(qt_app)
    browser.grid.setCurrentItem(browser.item(name))
    browser.apply_button.click()
    pump(qt_app)
    browser.close()


def marquee_everything(window, qt_app) -> None:
    canvas = window.canvas
    rect = canvas.frame_rect()
    start = QPointF(rect.left() + 2, rect.top() + 2)
    end = QPointF(rect.right() - 2, rect.bottom() - 2)
    for kind, pos, buttons in (
        (QEvent.Type.MouseButtonPress, start, Qt.MouseButton.LeftButton),
        (QEvent.Type.MouseMove, (start + end) / 2, Qt.MouseButton.LeftButton),
        (QEvent.Type.MouseMove, end, Qt.MouseButton.LeftButton),
        (QEvent.Type.MouseButtonRelease, end, Qt.MouseButton.NoButton),
    ):
        button = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseMove else Qt.MouseButton.LeftButton
        event = QMouseEvent(
            kind,
            pos,
            QPointF(canvas.mapToGlobal(pos.toPoint())),
            button,
            buttons,
            Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(canvas, event)
        pump(qt_app, 2)


def test_create_save_reopen_and_export_a_typical_animation(qt_app, tmp_path, monkeypatch) -> None:
    recorder = Recorder()
    logging.getLogger().addHandler(recorder)
    actions = 0
    project_path = tmp_path / "pythagoras.json"
    window = MainWindow()
    window.resize(1400, 900)
    window.show()
    pump(qt_app)
    try:
        # 1. the welcome, then New
        assert window.welcome.isVisible()
        window.welcome.new_button.click()
        actions += 1
        pump(qt_app)
        # 2. a title, an equation, two shapes - each where it covers nothing
        title = add(window, qt_app, "Text")
        type_text(window, qt_app, "The Pythagorean theorem")
        equation = add(window, qt_app, "MathTex")
        type_text(window, qt_app, "a^2 + b^2 = c^2")
        circle = add(window, qt_app, "Circle")
        square = add(window, qt_app, "Square")
        actions += 2 * 4 + 2
        labels = [item.text(0) for item in window.layers.items()]
        assert "The Pythagorean theorem" in labels and "a^2 + b^2 = c^2" in labels
        positions = {window.project.layer(i).base.position for i in (title, equation, circle, square)}
        assert len(positions) == 4  # no two objects on the same spot
        # 3. presets: the title writes on at 0 s, the rest enter at 1 s (one keyframed)
        window.selection.set(title)
        browse_preset(window, qt_app, "Write")
        window.seek(1.0)
        window.selection.set_layers([equation, square])
        browse_preset(window, qt_app, "Fade in")
        window.selection.set(circle)
        browse_preset(window, qt_app, "Pop in")
        actions += 3 * 4
        assert [c.kind for c in window.project.layer(title).clips] == ["Write"]
        assert window.project.layer(circle).tracks  # Pop in keys the scale
        # 4. Arrange: everything selected with a rectangle, spaced evenly top to bottom
        marquee_everything(window, qt_app)
        assert set(window.selection.layer_ids) == {title, equation, circle, square}
        menu(window, "Arrange", "Distribute Vertically").trigger()
        actions += 2
        # 5. save (a name chosen in the dialog), close, reopen from Open Recent
        monkeypatch.setattr(
            QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(project_path), "*.json"))
        )
        menu(window, "File", "Save").trigger()
        actions += 2
        saved = Project.model_validate_json(project_path.read_text(encoding="utf-8"))
        assert saved == window.project
        window.close()
        pump(qt_app)
        window = MainWindow()
        window.resize(1400, 900)
        window.show()
        pump(qt_app)
        recent = menu(window, "File", "Open Recent").menu()
        recent.aboutToShow.emit()
        next(a for a in recent.actions() if a.text() == "pythagoras.json").trigger()
        actions += 3
        pump(qt_app)
        assert window.project == saved and window.path == project_path
        # 6. export the Python scene and the video
        python_path = tmp_path / "pythagoras.py"
        monkeypatch.setattr(window, "ask_python_path", lambda start: str(python_path))
        menu(window, "File", "Export Python...").trigger()
        actions += 2
        source = python_path.read_text(encoding="utf-8")
        compile(source, str(python_path), "exec")
        menu(window, "File", "Export Video...").trigger()
        dialog = window.export_dialog
        video = tmp_path / "pythagoras.mp4"
        dialog.path.setText(str(video))
        dialog.export_button.click()
        actions += 3
        wait(qt_app, lambda: not dialog.running, timeout=600)
        assert video.is_file(), dialog.status.text()
        with av.open(str(video)) as container:
            frames = [f.to_ndarray(format="rgb24") for f in container.decode(video=0)]
        times = frame_times(saved.canvas)
        assert len(frames) == len(times)
        camera, evaluator = make_camera(saved.canvas), Evaluator(saved)
        for index in range(0, len(times), 15):
            expected = render_frame(camera, evaluator.frame(times[index]))[:, :, :3].astype(int)
            assert np.abs(frames[index].astype(int) - expected).mean() < 4, f"frame {index}"
        assert actions <= 40, actions  # the whole path, counted
        assert recorder.records == []  # no warning, no error on the way
    finally:
        logging.getLogger().removeHandler(recorder)
        window.document.undo_stack.setClean()
        window.close()


def test_the_golden_path_project_exports_readable_python() -> None:
    from manim_studio.core.editing import library
    from manim_studio.core.model.schema import Canvas, Layer, Spec

    project = Project(
        canvas=Canvas(width_px=640, height_px=360),
        layers=[Layer(id="circle", spec=Spec(type="Circle"))],
    )
    pop_in = next(p for p in library.load_library().presets if p.name == "Pop in")
    project = library.apply_preset(project, "circle", pop_in, 1.0).project
    assert python_export.readable_problems(project) == []
