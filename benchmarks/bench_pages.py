"""B55 - workspace pages: what switching pages costs.

The canvas, timeline, Layers and Properties panels exist once and move between pages
(re-parenting); a page switch must feel instant. With the showcase project open at
1600x1000:

1. switching between Compose and a page that shows only the viewer (``show_page``:
   parking, re-parenting, splitter sizes, repaint);
2. the alternative of a second canvas per page: building another ``CanvasWidget``.

(The first B55 run, before the pages existed, moved the views between two splitters
by hand: 13.6 ms per switch; hiding and showing the two docks took 18.7 ms.)

Run: ``python benchmarks/bench_pages.py``.
"""

from __future__ import annotations

import os
import statistics
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
for name in ("MANIM_STUDIO_PREVIEW", "MANIM_STUDIO_WORKER", "MANIM_STUDIO_AUDIO", "MANIM_STUDIO_CODE"):
    os.environ.setdefault(name, "0")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QSplitter  # noqa: E402

from manim_studio.core import adapter  # noqa: E402
from manim_studio.ui import theme  # noqa: E402
from manim_studio.ui.canvas import CanvasWidget  # noqa: E402
from manim_studio.ui.main_window import MainWindow  # noqa: E402
from manim_studio.ui.pages import Page  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


class ViewerOnly(Page):
    name = "viewer"
    title = "Viewer"
    icon = "animate"

    def build(self):
        self.split = QSplitter(Qt.Orientation.Horizontal)
        self.split.addWidget(QLabel("tools"))
        return self.split

    def place(self, shared):
        self.split.insertWidget(1, shared.viewer)


def main() -> None:
    app = QApplication(sys.argv)
    theme.apply(app)
    adapter.configure(ROOT / ".cache" / "manim")
    window = MainWindow()
    window.resize(1600, 1000)
    window.show()
    window.load(ROOT / "examples" / "showcase.json")
    window.seek(2.0)
    window.pages.add(ViewerOnly(window))
    app.processEvents()

    samples = []
    for _ in range(40):
        start = time.perf_counter()
        window.show_page("viewer")
        app.processEvents()
        window.show_page("compose")
        app.processEvents()
        samples.append((time.perf_counter() - start) * 1000 / 2)
    print(f"page switch (park, re-parent, sizes, repaint): {statistics.median(samples):.1f} ms")

    start = time.perf_counter()
    second = CanvasWidget()
    second.resize(800, 450)
    second.show()
    app.processEvents()
    print(f"a second CanvasWidget, built and shown: {(time.perf_counter() - start) * 1000:.1f} ms")
    window.close()


if __name__ == "__main__":
    main()
