"""S3 acceptance (B24): drag an object on the canvas in the real editor window.

Opens the stress scene plus a MathTex morph in ``MainWindow`` (offscreen), lets
idle checkpoints finish, then drags objects on the canvas with synthetic mouse
events. Each step is timed from the mouse-move event to the end of the
event-loop turn that applied it: edit + validation + evaluator + Cairo render +
outline + panels.
"""

from __future__ import annotations

import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MANIM_STUDIO_WORKER", "0")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from bench_edits import scene
from manim_studio.core import adapter, edits
from manim_studio.core.evaluator import layer_transform
from manim_studio.core.schema import Keyframe
from manim_studio.ui.main_window import MainWindow

ROOT = Path(__file__).resolve().parent.parent
adapter.configure(ROOT / ".cache" / "manim")


def mouse(canvas, kind, pos: QPointF) -> None:
    buttons = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease else Qt.MouseButton.LeftButton
    button = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseMove else Qt.MouseButton.LeftButton
    global_pos = QPointF(canvas.mapToGlobal(pos.toPoint()))
    QApplication.sendEvent(
        canvas, QMouseEvent(kind, pos, global_pos, button, buttons, Qt.KeyboardModifier.NoModifier)
    )


def drag(app, window, layer_id: str, steps: int = 20) -> list[float]:
    canvas = window.canvas
    window.selection.set(layer_id)
    app.processEvents()
    anchor = layer_transform(window.project.layer(layer_id), window.t).position
    start = canvas.units_transform().map(QPointF(*anchor))
    mouse(canvas, QEvent.Type.MouseButtonPress, start)
    samples = []
    for i in range(1, steps + 1):
        pos = QPointF(start.x() + 3 * i, start.y())
        t0 = time.perf_counter()
        mouse(canvas, QEvent.Type.MouseMove, pos)
        app.processEvents()
        samples.append((time.perf_counter() - t0) * 1000)
    mouse(canvas, QEvent.Type.MouseButtonRelease, pos)
    window.document.undo_stack.undo()
    return samples[1:]


def main() -> None:
    app = QApplication(sys.argv)
    project = scene(keyframed_source=False)
    track = {"position": [Keyframe(t=0, value=(-2.0, 1.0)), Keyframe(t=4, value=(2.0, 1.0))]}
    project = edits.update_layer(project, "l2", tracks=track).project
    path = Path(tempfile.mkdtemp()) / "scene.json"
    path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
    window = MainWindow()
    window.resize(1280, 820)
    window.show()
    window.load(path)
    while window.evaluator.missing_checkpoints():
        window._on_idle()
    window.seek(1.5)
    app.processEvents()
    size = window.canvas._camera_size
    for label, layer_id in (("static layer (base)", "l1"), ("keyframed layer (key)", "l2")):
        samples = drag(app, window, layer_id)
        p90 = sorted(samples)[int(len(samples) * 0.9)]
        print(
            f"{label:<22} canvas {size[0]}x{size[1]}: "
            f"median {statistics.median(samples):5.1f} ms, p90 {p90:5.1f} ms"
        )
    window.document.undo_stack.setClean()
    window.close()


if __name__ == "__main__":
    main()
