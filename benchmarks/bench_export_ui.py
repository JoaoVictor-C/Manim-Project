"""S4 acceptance (B26): the editor stays responsive while a video is exported.

Opens ``examples/euler.json`` in ``MainWindow`` (offscreen), starts an export
through the dialog, and measures how late a 16 ms ``QTimer`` fires on the UI
thread until the export finishes (the event-loop latency a user would feel).
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

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from manim_studio.core import adapter
from manim_studio.ui.main_window import MainWindow

ROOT = Path(__file__).resolve().parent.parent
adapter.configure(ROOT / ".cache" / "manim")


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    window.load(ROOT / "examples" / "euler.json")
    window.show_export_dialog()
    dialog = window.export_dialog
    dialog.path.setText(str(Path(tempfile.mkdtemp()) / "euler.mp4"))

    lateness: list[float] = []
    last = [time.perf_counter()]

    def tick() -> None:
        now = time.perf_counter()
        lateness.append(max(0.0, (now - last[0]) * 1000 - 16))
        last[0] = now

    timer = QTimer()
    timer.setInterval(16)
    timer.timeout.connect(tick)
    started = time.perf_counter()
    dialog.start()
    timer.start()
    while dialog.running:
        app.processEvents()
        time.sleep(0.001)
    timer.stop()
    total = time.perf_counter() - started
    print(f"export of euler.json (210 frames 1280x720) took {total:.1f} s; status: {dialog.status.text()!r}")
    print(
        f"UI timer lateness during export: median {statistics.median(lateness):.1f} ms, "
        f"p99 {sorted(lateness)[int(len(lateness) * 0.99)]:.1f} ms, max {max(lateness):.1f} ms "
        f"over {len(lateness)} ticks"
    )
    window.close()


if __name__ == "__main__":
    main()
