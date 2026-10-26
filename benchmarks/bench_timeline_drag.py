"""S1 acceptance (B16): drag a clip in the real editor window, mouse event -> canvas.

Opens the stress scene plus a MathTex morph in ``MainWindow`` (offscreen), lets
idle checkpoints finish, then drags clip bars with synthetic mouse events. Each
step is timed from the mouse-move event to the end of the event-loop turn that
applied it: edit + validation + evaluator + Cairo render of the canvas + timeline.
"""

from __future__ import annotations

import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from bench_edits import scene
from manim_studio.core.engine import adapter
from manim_studio.ui.main_window import MainWindow
from manim_studio.ui.timeline.view import ROW_HEIGHT, RULER_HEIGHT

ROOT = Path(__file__).resolve().parent.parent
adapter.configure(ROOT / ".cache" / "manim")


def mouse(view, kind, pos):
    buttons = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease else Qt.MouseButton.LeftButton
    button = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseMove else Qt.MouseButton.LeftButton
    event = QMouseEvent(
        kind,
        pos,
        QPointF(view.viewport().mapToGlobal(pos.toPoint())),
        button,
        buttons,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(view.viewport(), event)


def drag(app, window, layer_id: str, clip_id: str, playhead: float, steps: int = 20) -> list[float]:
    view = window.timeline
    window.seek(playhead)
    row = view.row_of(layer_id)
    clip = next(c for c in window.project.layer(layer_id).clips if c.id == clip_id)
    scene_point = QPointF(
        view.scale.x(clip.start + clip.duration / 2), RULER_HEIGHT + row * ROW_HEIGHT + ROW_HEIGHT / 2
    )
    view.centerOn(scene_point)
    start = QPointF(view.mapFromScene(scene_point))
    mouse(view, QEvent.Type.MouseButtonPress, start)
    samples = []
    for i in range(1, steps + 1):
        pos = QPointF(start.x() + 3 * i, start.y())
        t0 = time.perf_counter()
        mouse(view, QEvent.Type.MouseMove, pos)
        app.processEvents()
        samples.append((time.perf_counter() - t0) * 1000)
    mouse(view, QEvent.Type.MouseButtonRelease, pos)
    window.document.undo_stack.undo()
    return samples[1:]


def main() -> None:
    app = QApplication(sys.argv)
    for keyframed in (False, True):
        path = Path(tempfile.mkdtemp()) / "scene.json"
        path.write_text(scene(keyframed).model_dump_json(by_alias=True), encoding="utf-8")
        window = MainWindow()
        window.resize(1280, 820)
        window.show()
        window.load(path)
        while window.evaluator.missing_checkpoints():
            window._on_idle()
        app.processEvents()
        size = window.canvas._camera_size
        label = "keyframed source" if keyframed else "static partners"
        for name, layer_id, clip_id, playhead in (
            ("Write clip", "l1", "w1", 1.5),
            ("morph clip", "ma", "m", 2.5),
        ):
            samples = drag(app, window, layer_id, clip_id, playhead)
            p90 = sorted(samples)[int(len(samples) * 0.9)]
            print(
                f"{name:<11} ({label:<16}) canvas {size[0]}x{size[1]}: "
                f"median {statistics.median(samples):5.1f} ms, p90 {p90:5.1f} ms"
            )
        window.close()


if __name__ == "__main__":
    main()
