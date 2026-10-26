"""B63 - the presets browser: what opening it, reopening it, typing in its search and playing a
card cost (offscreen, the built-in presets).

1. the first Animate > Browse Presets...: the dialog built and shown, every thumbnail drawn;
2. showing it again (the frames are kept);
3. one search keystroke (the cards rebuilt) and one tab switch;
4. one frame of a hovered card.

Run: ``python benchmarks/bench_presets_browser.py``.
"""

from __future__ import annotations

import os
import statistics
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
for name in ("MANIM_STUDIO_PREVIEW", "MANIM_STUDIO_WORKER", "MANIM_STUDIO_AUDIO", "MANIM_STUDIO_CODE"):
    os.environ.setdefault(name, "0")

from PySide6.QtWidgets import QApplication  # noqa: E402

from manim_studio.core.engine import adapter  # noqa: E402
from manim_studio.ui.style import theme  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000


def main() -> None:
    adapter.configure(ROOT / ".cache" / "manim")
    from manim_studio.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    theme.apply(app)
    window = MainWindow()
    window.resize(1100, 760)
    window.show()
    app.processEvents()

    start = time.perf_counter()
    browser = window.show_presets_browser()
    app.processEvents()
    print(f"first open ({len(browser.names())} presets): {ms(start):.0f} ms")
    browser.close()
    warm = []
    for _ in range(10):
        start = time.perf_counter()
        window.show_presets_browser()
        app.processEvents()
        warm.append(ms(start))
        browser.close()
    print(f"reopen: median {statistics.median(warm):.1f} ms")
    window.show_presets_browser()
    keys = []
    for text in ("f", "fa", "fad", "fade", "fad", "fa", "f", ""):
        start = time.perf_counter()
        browser.search.setText(text)
        app.processEvents()
        keys.append(ms(start))
    print(f"search keystroke: median {statistics.median(keys):.1f} ms, worst {max(keys):.1f} ms")
    tabs = []
    for index in (1, 2, 3, 4, 0):
        start = time.perf_counter()
        browser.tabs.setCurrentIndex(index)
        app.processEvents()
        tabs.append(ms(start))
    print(f"tab switch: median {statistics.median(tabs):.1f} ms, worst {max(tabs):.1f} ms")
    browser.playing = "Fade in"
    browser.frame = 0
    ticks = []
    for _ in range(40):
        start = time.perf_counter()
        browser._tick()
        app.processEvents()
        ticks.append(ms(start))
    print(f"hover frame: median {statistics.median(ticks):.2f} ms, worst {max(ticks):.2f} ms")
    window.document.undo_stack.setClean()
    window.close()


if __name__ == "__main__":
    main()
