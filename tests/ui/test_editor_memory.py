"""What the editor holds in memory, and when: nothing runs for the welcome page, and a project that was
closed is given back.

Every helper process is a Python with Manim loaded (over 100 MB), and a project's panels are tied in
reference cycles through Qt objects, so both are measured by what they leave behind, not by a stopwatch."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import gc
import weakref
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from manim_studio.ui.main_window import MainWindow
from manim_studio.ui.services.worker_process import WorkerProcess

pytestmark = pytest.mark.ui

DEMO = Path(__file__).resolve().parents[2] / "examples" / "euler.json"


@pytest.fixture
def window(qt_app, tmp_path):
    win = MainWindow()
    win.resize(640, 400)
    win.show()
    yield win
    win.close()
    qt_app.processEvents()


def test_garbage_an_earlier_project_left_is_collected_when_the_next_one_opens(window) -> None:
    """``gc.freeze()`` after opening a project (it removes collection pauses while playing) keeps what it
    froze for good, cyclic garbage included: the scrub boxes of a closed project's properties panel, 3 MB for
    every project opened. Opening a project thaws everything, collects, and freezes what is alive."""

    class Ring:  # a reference cycle, as a panel's widgets and their closures make
        pass

    ring = Ring()
    ring.itself = ring
    gone = weakref.ref(ring)
    gc.freeze()  # what the opening of the previous project did, with this ring alive
    del ring
    assert gone() is not None, "frozen garbage is never collected by itself (the premise of this test)"
    window.load(DEMO)
    assert gone() is None


def test_the_welcome_page_runs_no_build_worker_and_the_first_project_starts_it(qt_app, monkeypatch) -> None:
    started = []
    monkeypatch.setenv("MANIM_STUDIO_WORKER", "1")
    monkeypatch.setattr(WorkerProcess, "start", lambda self: started.append(self))
    win = MainWindow()
    try:
        win.show()
        qt_app.processEvents()
        assert started == [] and win.builds.client.asleep, "the welcome page started the build worker"
        win.new_project()  # a project: the library's text objects are warmed, which needs the worker
        assert started == [win.builds.client]
    finally:
        win.close()
        qt_app.processEvents()
