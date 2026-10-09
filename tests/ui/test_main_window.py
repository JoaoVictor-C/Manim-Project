"""S0 previewer smoke test (ADR 0006, 0009).

The previewer loads the demo, scrubs, and precomputes checkpoints.
"""

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from manim_studio.ui.main_window import MainWindow

DEMO = Path(__file__).resolve().parents[2] / "examples" / "euler.json"


@pytest.mark.ui
def test_previewer_loads_scrubs_and_warms_checkpoints(qt_app) -> None:
    window = MainWindow()
    window.resize(960, 600)
    window.show()
    window.load(DEMO)
    for t in (0.0, 1.2, 5.0, 6.9, 3.0):
        window.seek(t)
        assert window.canvas._image is not None
        assert not window.canvas._image.isNull()
    while window.evaluator.missing_checkpoints():
        window._on_idle()
    window._on_idle()
    assert not window.idle_timer.isActive()
    window.close()
    qt_app.processEvents()
