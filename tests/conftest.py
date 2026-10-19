"""Test session setup: Manim cache location, LaTeX discovery, marker handling."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

# Tests never load the developer's own plugins (ADR 0032); set before the adapter loads them.
os.environ["MANIM_STUDIO_PLUGINS"] = str(Path(tempfile.mkdtemp(prefix="manim-studio-test-plugins-")))

from manim_studio.core import adapter

ROOT = Path(__file__).resolve().parent.parent

# Tests that run the CLI or editor must not write into the user's real log folder.
os.environ["MANIM_STUDIO_LOG_DIR"] = str(Path(tempfile.mkdtemp(prefix="manim-studio-test-logs-")))
# Tests never read or write the user's trusted-code store (ADR 0019).
os.environ["MANIM_STUDIO_TRUST_FILE"] = str(
    Path(tempfile.mkdtemp(prefix="manim-studio-test-trust-")) / "trusted.json"
)
# ... nor the user's recovery copies of unsaved work (ADR 0038).
os.environ["MANIM_STUDIO_RECOVERY"] = str(Path(tempfile.mkdtemp(prefix="manim-studio-test-recovery-")))
# Editor windows in tests render no code layers unless a test opts in (ADR 0019).
os.environ["MANIM_STUDIO_CODE"] = "0"
# Editor windows in tests build synchronously; the worker has its own tests (ADR 0015).
os.environ["MANIM_STUDIO_WORKER"] = "0"
# ... and render no frames ahead unless a test opts in (ADR 0028).
os.environ["MANIM_STUDIO_PREVIEW"] = "0"
# ... and never read or write the user's own presets, themes and templates (ADR 0039).
os.environ["MANIM_STUDIO_LIBRARY"] = str(Path(tempfile.mkdtemp(prefix="manim-studio-test-library-")))
# ... and play no sound: playback keeps the wall clock unless a test gives it a player (ADR 0034).
os.environ["MANIM_STUDIO_AUDIO"] = "0"

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
    app = widgets.QApplication.instance() or widgets.QApplication([])
    from manim_studio.ui import theme

    theme.apply(app)  # the tests drive the widgets the user sees (ADR 0040)
    return app


@pytest.fixture(autouse=True)
def _fresh_settings(tmp_path_factory, monkeypatch):
    """Every test gets its own, empty settings file (ADR 0044): windows start at today's
    defaults (Compose first, no remembered geometry, no recent files) and never touch the
    user's real preferences."""
    monkeypatch.setenv(
        "MANIM_STUDIO_SETTINGS", str(tmp_path_factory.mktemp("manim-studio-settings") / "manim-studio.ini")
    )


@pytest.fixture(autouse=True)
def _no_unsaved_changes_dialog(request, monkeypatch):
    """Editor windows closed with unsaved edits must not block on a modal question."""
    if "ui" not in request.keywords:
        return
    from manim_studio.ui.main_window import MainWindow

    monkeypatch.setattr(MainWindow, "ask_unsaved", lambda self: "discard")
    monkeypatch.setattr(MainWindow, "ask_stop_export", lambda self: "stop")
    monkeypatch.setattr(MainWindow, "ask_trust", lambda self, names: "skip")
    monkeypatch.setattr(MainWindow, "ask_recover", lambda self, entries: "later")
    monkeypatch.setattr(MainWindow, "ask_new_project", lambda self, remembered: remembered)  # no dialog


@pytest.fixture(autouse=True)
def _no_exceptions_in_qt_slots(request, monkeypatch):
    """An exception raised in a Qt slot (a menu action, a timer, a signal) is printed and
    swallowed by Qt, so the test would pass: collect them and fail the test instead."""
    if "ui" not in request.keywords:
        yield
        return
    import sys
    import traceback

    raised: list[str] = []
    monkeypatch.setattr(
        sys, "excepthook", lambda *info: raised.append("".join(traceback.format_exception(*info)))
    )
    yield
    if raised:
        pytest.fail("exception in a Qt slot:\n" + "\n".join(raised), pytrace=False)


_MOVED: list[str] = []  # where an imported module moved Manim's cache, if one did


def pytest_collection_finish(session: pytest.Session) -> None:
    """Importing a module must not move Manim's cache: parallel workers would share one folder
    and collide on LaTeX files and export snapshots (a benchmark imported by a test once did).
    Raising here would only kill the xdist workers silently, so every test fails instead."""
    if Path(adapter.cache_dir()) != CACHE:
        _MOVED.append(str(adapter.cache_dir()))
        adapter.configure(CACHE)


@pytest.fixture(autouse=True)
def _cache_not_moved():
    if _MOVED:
        pytest.fail(f"a module imported by the tests moved Manim's cache to {_MOVED[0]}", pytrace=False)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if shutil.which("latex") is None:
        skip = pytest.mark.skip(reason="LaTeX not found (install MiKTeX or TeX Live)")
        for item in items:
            if "latex" in item.keywords:
                item.add_marker(skip)
