"""B68 - P7.3: a timeline rebuild with every object's property rows expanded.

Builds the explainer-like projects of ``tests/ui/test_long_scene_scaling.py`` (nine layers a slide,
with clips, morphs and parts) at 45, 99 and 297 layers, gives every object an opacity fade (two
keys), and times ``TimelineView.sync`` plus the deletion of what it replaced, on a new snapshot
each time (the layer index rebuilt), with every row collapsed and then every row expanded. Minimum
of 15 runs; offscreen.

Run::

    python benchmarks/bench_property_rows.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))  # the test helpers
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests" / "ui"))  # the test projects

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication
from test_long_scene_scaling import long_project

from manim_studio.core.schema import Keyframe, Project
from manim_studio.ui.document import Document
from manim_studio.ui.timeline.view import TimelineView

REPEATS = 15


def project(slides: int) -> Project:
    built = long_project(slides)
    for i, layer in enumerate(built.layers):
        if layer.parent_id is None:
            t0 = 10.0 * (i // 9)
            layer.tracks["opacity"] = [Keyframe(t=t0, value=0.0), Keyframe(t=t0 + 1, value=1.0)]
    return Project.model_validate(built.model_dump())


def best_sync(view: TimelineView) -> float:
    best = float("inf")
    for _ in range(REPEATS):
        view._index = None  # as after an edit: a new snapshot
        start = time.perf_counter()
        view.sync()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)  # the old scene goes
        best = min(best, time.perf_counter() - start)
    return best * 1000


def main() -> None:
    app = QApplication.instance() or QApplication([])
    for slides in (5, 11, 33):
        scene = project(slides)
        view = TimelineView()
        view.resize(1200, 600)
        view.set_document(Document(scene))
        view.show()
        app.processEvents()
        collapsed = best_sync(view)
        for layer in scene.layers:
            view.set_expanded(layer.id, True)
        expanded = best_sync(view)
        print(
            f"{len(scene.layers):4d} layers: sync collapsed {collapsed:6.1f} ms, every row expanded "
            f"{expanded:6.1f} ms ({len(view.scene().items())} items)"
        )
        view.close()


if __name__ == "__main__":
    main()
