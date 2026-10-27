"""Helpers are started through ``children`` so that none of them outlives the editor."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import subprocess
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QProcess

from manim_studio import lifeline
from manim_studio.ui.services import children

pytestmark = pytest.mark.ui

SLEEP = "import time; time.sleep(120)"
READ_UNTIL_CLOSED = "import sys\nsys.stdin.read()\n"  # ends when its input does
PARENT_OF_A_SLEEPER = (
    "import subprocess, sys, time\n"
    f"child = subprocess.Popen([sys.executable, '-c', {SLEEP!r}])\n"
    "print(child.pid, flush=True)\n"
    "time.sleep(120)\n"
)


def wait_until(qt_app, condition, timeout: float = 20.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        qt_app.processEvents()
        if condition():
            return True
        time.sleep(0.02)
    return condition()


def helper(script: str) -> QProcess:
    process = QProcess()
    process.setProgram(sys.executable)
    process.setArguments(["-c", script])
    process.setProcessEnvironment(children.environment())
    return process


@pytest.fixture(autouse=True)
def nothing_left_behind():
    yield
    children.stop_all(grace_ms=0)


def test_a_helper_is_told_which_editor_started_it() -> None:
    env = children.environment(EXTRA="1")
    assert env.value(lifeline.EDITOR_PID) == str(os.getpid())
    assert env.value("PYTHONUTF8") == "1" and env.value("EXTRA") == "1"
    assert env.value("PATH") or env.value("Path")  # the rest of the environment comes along


def test_a_started_helper_is_remembered_until_it_ends(qt_app) -> None:
    process = helper(READ_UNTIL_CLOSED)
    children.start(process)
    assert process in children.running()
    process.closeWriteChannel()
    assert wait_until(qt_app, lambda: process.state() == QProcess.ProcessState.NotRunning)
    assert process not in children.running()


def test_a_helper_that_cannot_start_is_not_remembered(qt_app) -> None:
    process = QProcess()
    process.setProgram("no-such-program-for-manim-studio-tests")
    children.start(process)
    assert process not in children.running()


def test_asking_all_to_stop_closes_their_input_so_those_that_read_it_end(qt_app) -> None:
    readers = [helper(READ_UNTIL_CLOSED) for _ in range(3)]
    for process in readers:
        children.start(process)
    children.ask_all_to_stop()
    assert wait_until(qt_app, lambda: all(p.state() == QProcess.ProcessState.NotRunning for p in readers))


def test_stop_all_ends_a_helper_that_ignores_its_input_with_what_it_started(qt_app) -> None:
    process = helper(PARENT_OF_A_SLEEPER)
    children.start(process)
    # (what arrives while events are processed is already in the buffer: waiting for more would never end)
    assert wait_until(qt_app, lambda: process.bytesAvailable() > 0 or process.waitForReadyRead(50))
    child = int(bytes(process.readAllStandardOutput().data()).split()[0])
    below = [child, *lifeline.descendants(int(process.processId()))]
    children.stop_all(grace_ms=300)
    assert process.state() == QProcess.ProcessState.NotRunning or wait_until(
        qt_app, lambda: process.state() == QProcess.ProcessState.NotRunning
    )
    assert wait_until(qt_app, lambda: not any(lifeline.process_alive(p) for p in below)), "a helper was left"
    assert children.running() == []


def test_stop_all_waits_for_all_together_not_one_after_the_other(qt_app) -> None:
    """Three helpers that take 0.6 s to end after their input closes: stopping them takes about 0.6 s."""
    slow = "import sys, time\nsys.stdin.read()\ntime.sleep(0.6)\n"
    processes = [helper(slow) for _ in range(3)]
    for process in processes:
        children.start(process)
    start = time.monotonic()
    children.stop_all(grace_ms=5000)
    took = time.monotonic() - start
    assert all(p.state() == QProcess.ProcessState.NotRunning for p in processes)
    assert took < 1.6, f"{took:.1f} s: they were stopped one after another"


def test_quitting_the_application_stops_the_helpers(qt_app) -> None:
    process = helper(READ_UNTIL_CLOSED)
    children.start(process)
    children.install(qt_app)
    try:
        qt_app.aboutToQuit.emit()  # what quitting does
        assert wait_until(qt_app, lambda: process.state() == QProcess.ProcessState.NotRunning)
    finally:
        qt_app.aboutToQuit.disconnect(children.stop_all)


def test_every_module_that_runs_a_helper_starts_it_through_children() -> None:
    """A QProcess started on its own is outside the editor's job and not told which editor started it: it
    would outlive the editor, so a new service that starts one fails here until it uses ``children``."""
    root = Path(__file__).resolve().parents[3] / "src" / "manim_studio"
    users = [p for p in root.rglob("*.py") if p.name != "children.py" and "QProcess(" in p.read_text("utf-8")]
    # (the build worker, the renderers, exports, voices and imports: the search finds what it is about)
    assert len(users) >= 7, [p.name for p in users]
    for path in users:
        text = path.read_text("utf-8")
        assert "children.start(" in text and "children.environment(" in text, path.name


def test_a_helper_started_without_children_is_not_touched(qt_app) -> None:
    other = subprocess.Popen([sys.executable, "-c", SLEEP])
    try:
        children.stop_all(grace_ms=0)
        assert other.poll() is None  # only what was started through ``start`` is ended
    finally:
        lifeline.kill_tree(other.pid)
        other.wait(timeout=10)
