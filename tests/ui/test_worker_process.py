"""The build worker as a real subprocess (ADR 0015).

Lifecycle rules (startup queue, timeout, crash restart, giving up) are tested
with tiny stand-in programs so they run in a second; the real worker is tested
end to end: it warms the disk cache this process then reads, and it reports
LaTeX errors.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys
import time
import uuid
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from manim_studio.core import adapter
from manim_studio.core.schema import Spec
from manim_studio.core.warm import warm_key
from manim_studio.ui.worker_process import MAX_FAILED_STARTS, WorkerProcess

pytestmark = [pytest.mark.ui, pytest.mark.slow]  # starts real processes

ROOT = Path(__file__).resolve().parents[2]
CACHE = adapter.cache_dir()  # set by conftest; LaTeX fails under the 8.3 temp path on this machine

# Stand-ins speaking the protocol: echo every request back as ok, or never answer.
ECHO = (
    "import json,sys\n"
    "print(json.dumps({'ready': True}), flush=True)\n"
    "for line in sys.stdin:\n"
    "    print(json.dumps({'id': json.loads(line)['id'], 'ok': True}), flush=True)\n"
)
SILENT = "import json,sys,time\nprint(json.dumps({'ready': True}), flush=True)\ntime.sleep(60)\n"


def wait_until(qt_app, condition, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("timed out waiting")
        qt_app.processEvents()
        time.sleep(0.01)


@pytest.fixture
def make(qt_app):
    workers = []

    def factory(script: str | None = None, **kwargs) -> WorkerProcess:
        if script is not None:
            kwargs.update(program=sys.executable, args=["-c", script])
        worker = WorkerProcess(CACHE, **kwargs)
        worker.replies = []
        worker.replied.connect(lambda *reply: worker.replies.append(reply))
        workers.append(worker)
        return worker

    yield factory
    for worker in workers:
        worker.stop()


@pytest.fixture(scope="module")
def real_worker(qt_app):
    """One real worker shared by the end-to-end tests (starting one takes 3-4 s, B18)."""
    adapter.configure(CACHE)  # other tests (the CLI) point Manim elsewhere; share the worker's cache
    worker = WorkerProcess(CACHE)
    worker.replies = []
    worker.replied.connect(lambda *reply: worker.replies.append(reply))
    yield worker
    worker.stop()


def test_requests_queue_until_the_worker_is_ready(make, qt_app) -> None:
    worker = make(ECHO)
    worker.request(1, '{"type": "Circle"}')  # sent before the process has started
    worker.request(2, '{"type": "Square"}')
    wait_until(qt_app, lambda: len(worker.replies) == 2)
    assert worker.replies == [(1, True, ""), (2, True, "")]


def test_a_request_that_takes_too_long_fails_and_the_worker_restarts(make, qt_app) -> None:
    worker = make(SILENT, timeout_s=0.5)
    wait_until(qt_app, lambda: worker.ready)
    first_pid = worker.pid
    worker.request(1, '{"type": "Circle"}')
    wait_until(qt_app, lambda: worker.replies)
    assert worker.replies[0][:2] == (1, False) and "longer than" in worker.replies[0][2]
    wait_until(qt_app, lambda: worker.ready)
    assert worker.pid != first_pid


def test_a_worker_that_never_starts_makes_the_client_unavailable(make, qt_app) -> None:
    worker = make("import sys; sys.exit(3)")
    changes = []
    worker.availableChanged.connect(changes.append)
    worker.request(1, '{"type": "Circle"}')
    wait_until(qt_app, lambda: not worker.available)
    assert changes == [False]
    assert worker.replies == [(1, False, "build worker unavailable")]
    assert worker._failed_starts == MAX_FAILED_STARTS


def test_a_missing_python_makes_the_client_unavailable(make, qt_app) -> None:
    worker = make(program=str(ROOT / "no-such-python.exe"), args=[])
    wait_until(qt_app, lambda: not worker.available)


@pytest.mark.latex
def test_real_worker_warms_the_cache_for_this_process(real_worker, qt_app) -> None:
    """B18 end to end: the worker writes the disk-cache entries this process then reads."""
    worker = real_worker
    worker.replies.clear()
    specs = [
        Spec(type="Text", params={"text": f"warm {uuid.uuid4().hex[:8]}"}),
        Spec(type="MathTex", params={"text": rf"\sqrt{{{uuid.uuid4().int % 10**9}}}"}),
    ]
    before = {path for path in CACHE.rglob("*.svg")}
    for i, spec in enumerate(specs, 1):
        worker.request(i, warm_key(spec))
    wait_until(qt_app, lambda: len(worker.replies) == 2, timeout=60)
    assert [ok for _, ok, _ in worker.replies] == [True, True], worker.replies
    written = {path for path in CACHE.rglob("*.svg")} - before
    assert {path.parent.name for path in written} == {"texts", "Tex"}, written
    # Reading them back is a cache hit: for LaTeX (seconds cold) that is far faster.
    # Text is not timed: a cold Text can take as little as 0.2 s, close to a warm read.
    cold = Spec(type="MathTex", params={"text": rf"\sqrt[3]{{{uuid.uuid4().int % 10**9}}}"})
    warm_ms, cold_ms = build_ms(specs[1]), build_ms(cold)
    assert warm_ms < cold_ms / 3, f"MathTex: warm {warm_ms:.0f} ms vs cold {cold_ms:.0f} ms"
    # The warmed Text is read, not drawn again (counting files would also see other processes' writes).
    from manim.mobject.text import text_mobject

    drawn = []
    original = text_mobject.manimpango.text2svg
    text_mobject.manimpango.text2svg = lambda *a, **k: drawn.append(a) or original(*a, **k)
    try:
        build_ms(specs[0])
    finally:
        text_mobject.manimpango.text2svg = original
    assert drawn == []


def build_ms(spec: Spec) -> float:
    adapter._build_cached.cache_clear()  # only Manim's disk cache may help
    started = time.perf_counter()
    adapter.build_mobject(spec)
    return (time.perf_counter() - started) * 1000


@pytest.mark.latex
def test_real_worker_reports_latex_errors(real_worker, qt_app) -> None:
    worker = real_worker
    worker.replies.clear()
    bad = Spec(type="MathTex", params={"text": rf"\notamacro {uuid.uuid4().hex[:6]}"})
    worker.request(1, warm_key(bad))
    wait_until(qt_app, lambda: worker.replies, timeout=60)
    request_id, ok, error = worker.replies[0]
    assert (request_id, ok) == (1, False)
    assert error == "LaTeX error: Undefined control sequence.", error


@pytest.mark.latex
def test_real_worker_restarts_after_a_crash_and_finishes_the_request(real_worker, qt_app) -> None:
    worker = real_worker
    worker.replies.clear()
    wait_until(qt_app, lambda: worker.ready, timeout=60)
    first_pid = worker.pid
    # A fresh LaTeX build takes seconds, so the kill always lands while it is outstanding
    # (a Circle could be answered before the kill, and then nothing restarts).
    slow = Spec(type="MathTex", params={"text": rf"\sqrt{{{uuid.uuid4().int % 10**9}}}"})
    worker.request(3, warm_key(slow))
    worker._process.kill()  # the worker dies while the request is outstanding
    wait_until(qt_app, lambda: worker.replies, timeout=60)
    assert worker.replies == [(3, True, "")]
    assert worker.pid != first_pid


def test_a_worker_torn_down_with_the_application_does_not_restart(make, qt_app) -> None:
    """GP: when the application ends without closing the window, Qt deletes the worker's
    process first; its late ``finished`` must not try to restart it (it raised RuntimeError)."""
    import shiboken6

    worker = make("import time; time.sleep(30)")
    worker.start()
    process = worker._process
    restarts = []
    worker.start = lambda: restarts.append(1)  # a restart would call start() again
    shiboken6.delete(process)  # what the application's teardown does to the child QProcess
    worker._on_exit(process)  # its finished signal, arriving late
    assert restarts == []
    worker._process = None
