"""B54 - the design system: what icons and an app-wide stylesheet cost.

1. QtAwesome (icon fonts): import time, the first icon (loads the font), more icons, and
   rendering one to a 20 px pixmap.
2. Applying a ~300-rule application stylesheet to a running app with the main window open,
   and the time to show the window afterwards.
3. Which icon sets QtAwesome ships and whether names the editor needs exist in Phosphor.

Run: ``python benchmarks/bench_design.py``.
"""

from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MANIM_STUDIO_PREVIEW", "0")
os.environ.setdefault("MANIM_STUDIO_WORKER", "0")
os.environ.setdefault("MANIM_STUDIO_AUDIO", "0")
os.environ.setdefault("MANIM_STUDIO_CODE", "0")

from PySide6.QtWidgets import QApplication

NEEDED = [
    "play",
    "pause",
    "skip-back",
    "skip-forward",
    "plus",
    "trash",
    "arrow-up",
    "arrow-down",
    "eye",
    "eye-slash",
    "lock",
    "lock-open",
    "diamond",
    "flag",
    "magnet",
    "film-strip",
    "code",
    "speaker-high",
    "text-t",
    "export",
    "folder-open",
    "floppy-disk",
    "magnifying-glass-plus",
]


def ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000


def main() -> None:
    app = QApplication(sys.argv)
    start = time.perf_counter()
    import qtawesome as qta

    print(f"import qtawesome: {ms(start):.0f} ms")
    start = time.perf_counter()
    qta.icon("ph.play")
    print(f"first icon (font load): {ms(start):.1f} ms")
    start = time.perf_counter()
    icons = [qta.icon(f"ph.{name}") for name in NEEDED]
    print(f"{len(icons)} more icons: {ms(start):.2f} ms")
    start = time.perf_counter()
    for icon in icons:
        icon.pixmap(20, 20)
    print(f"render {len(icons)} at 20 px: {ms(start):.2f} ms")
    missing = []
    for name in NEEDED:
        try:
            qta.icon(f"ph.{name}")
        except Exception:
            missing.append(name)
    print(f"Phosphor names missing: {missing or 'none'}")

    from manim_studio.ui.main_window import MainWindow

    window = MainWindow()
    window.show()
    app.processEvents()
    rules = []
    for i in range(300):
        rules.append(f"QWidget#w{i} {{ background: #1e1f22; color: #d4d4d8; border: 1px solid #333; }}")
    sheet = "\n".join(rules) + "\nQWidget { background: #1e1f22; color: #d4d4d8; }"
    start = time.perf_counter()
    app.setStyleSheet(sheet)
    app.processEvents()
    print(f"apply a 300-rule stylesheet with the window open: {ms(start):.0f} ms")
    window.close()
    start = time.perf_counter()
    again = MainWindow()
    again.show()
    app.processEvents()
    print(f"open a main window under the stylesheet: {ms(start):.0f} ms")
    again.close()


if __name__ == "__main__":
    main()
