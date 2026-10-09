"""Test session setup: Manim cache location, LaTeX discovery, marker handling."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

from manim_studio.core import adapter

ROOT = Path(__file__).resolve().parent.parent

# Tests that run the CLI or editor must not write into the user's real log folder.
os.environ["MANIM_STUDIO_LOG_DIR"] = str(Path(tempfile.mkdtemp(prefix="manim-studio-test-logs-")))

# Must run before any test builds a mobject: sets the cache dir and finds MiKTeX.
adapter.configure(ROOT / ".cache" / "manim")


@pytest.fixture(scope="session")
def qt_app():
    """One QApplication for the whole session.

    Qt allows a single application object per process, and widgets need a
    QApplication (not QGuiApplication), so every Qt test must share this one.
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    widgets = pytest.importorskip("PySide6.QtWidgets")
    return widgets.QApplication.instance() or widgets.QApplication([])


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if shutil.which("latex") is None:
        skip = pytest.mark.skip(reason="LaTeX not found (install MiKTeX or TeX Live)")
        for item in items:
            if "latex" in item.keywords:
                item.add_marker(skip)
