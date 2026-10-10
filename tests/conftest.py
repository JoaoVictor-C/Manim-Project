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
# Tests never read or write the user's trusted-code store (ADR 0019).
os.environ["MANIM_STUDIO_TRUST_FILE"] = str(
    Path(tempfile.mkdtemp(prefix="manim-studio-test-trust-")) / "trusted.json"
)
# Editor windows in tests render no code layers unless a test opts in (ADR 0019).
os.environ["MANIM_STUDIO_CODE"] = "0"
# Editor windows in tests build synchronously; the worker has its own tests (ADR 0015).
os.environ["MANIM_STUDIO_WORKER"] = "0"

# Must run before any test builds a mobject: sets the cache dir and finds MiKTeX.
SHARED_CACHE = ROOT / ".cache" / "manim"
# Parallel runs (pytest -n): each worker gets its own Manim cache, seeded with the
# shared one's compiled LaTeX and text, so workers never write the same file at
# once. It lives in the project: LaTeX fails under the 8.3 temp path (setup notes).
WORKER = os.environ.get("PYTEST_XDIST_WORKER")
CACHE = ROOT / ".cache" / "test-workers" / WORKER if WORKER else SHARED_CACHE
if WORKER:
    for folder in ("Tex", "texts"):
        if (SHARED_CACHE / folder).is_dir():
            shutil.copytree(SHARED_CACHE / folder, CACHE / folder, dirs_exist_ok=True)
adapter.configure(CACHE)


@pytest.fixture(autouse=True)
def _shared_manim_cache():
    """Every test sees the shared cache, where LaTeX is already compiled.

    CLI tests point Manim at their own cache (``--cache-dir``); left that way,
    every later LaTeX build compiled from scratch (~3 s each, minutes overall).
    """
    yield
    if Path(adapter.cache_dir()) != CACHE:
        adapter.configure(CACHE)


@pytest.fixture(scope="session")
def qt_app():
    """One QApplication for the whole session.

    Qt allows a single application object per process, and widgets need a
    QApplication (not QGuiApplication), so every Qt test must share this one.
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    widgets = pytest.importorskip("PySide6.QtWidgets")
    return widgets.QApplication.instance() or widgets.QApplication([])


@pytest.fixture(autouse=True)
def _no_unsaved_changes_dialog(request, monkeypatch):
    """Editor windows closed with unsaved edits must not block on a modal question."""
    if "ui" not in request.keywords:
        return
    from manim_studio.ui.main_window import MainWindow

    monkeypatch.setattr(MainWindow, "ask_unsaved", lambda self: "discard")
    monkeypatch.setattr(MainWindow, "ask_stop_export", lambda self: "stop")
    monkeypatch.setattr(MainWindow, "ask_trust", lambda self, names: "skip")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if shutil.which("latex") is None:
        skip = pytest.mark.skip(reason="LaTeX not found (install MiKTeX or TeX Live)")
        for item in items:
            if "latex" in item.keywords:
                item.add_marker(skip)
