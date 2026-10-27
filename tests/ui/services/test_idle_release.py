"""Helper processes that nobody is using are released, and start again when they are needed.

A helper is a Python process with Manim loaded (over 100 MB each), so the build worker, the frame renderer
and the code renderer's ready spare give theirs back after ``idle_s`` without work. Stand-in programs speak
the protocols, so each test is a second."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys
import time

import pytest

pytest.importorskip("PySide6")

from manim_studio.core.code.trust import TrustStore
from manim_studio.core.model.schema import Canvas, Layer, Project, Spec
from manim_studio.ui.services import worker_process
from manim_studio.ui.services.code_render import CodeRenderService
from manim_studio.ui.services.preview_client import PreviewProcess
from manim_studio.ui.services.worker_process import WorkerProcess

pytestmark = pytest.mark.ui

ECHO = (
    "import json,sys\n"
    "print(json.dumps({'ready': True}), flush=True)\n"
    "for line in sys.stdin:\n"
    "    print(json.dumps({'id': json.loads(line)['id'], 'ok': True}), flush=True)\n"
)
SILENT = "import json,sys,time\nprint(json.dumps({'ready': True}), flush=True)\ntime.sleep(60)\n"
# A preview process that says ready, and answers every "want" with one failed frame per index asked.
PREVIEW = (
    "import json,sys\n"
    "print(json.dumps({'ready': True}), flush=True)\n"
    "for line in sys.stdin:\n"
    "    message = json.loads(line)\n"
    "    for index in message.get('want', []):\n"
    "        print(json.dumps({'failed': index, 'error': 'stand-in'}), flush=True)\n"
)
# A code renderer spare: ready, one job, done.
SPARE = (
    "import json,sys\n"
    "print(json.dumps({'ready': True}), flush=True)\n"
    "sys.stdin.readline()\n"
    "print(json.dumps({'done': True, 'frames': 1}), flush=True)\n"
)
IDLE = 0.5


def wait_until(qt_app, condition, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("timed out waiting")
        qt_app.processEvents()
        time.sleep(0.01)


def stays(qt_app, condition, seconds: float) -> bool:
    """Whether ``condition`` holds for all of ``seconds``."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        qt_app.processEvents()
        if not condition():
            return False
        time.sleep(0.01)
    return True


# -- the build worker -------------------------------------------------------------------------------


@pytest.fixture
def worker(qt_app, tmp_path):
    made = []

    def make(script: str, **kwargs) -> WorkerProcess:
        process = WorkerProcess(tmp_path, program=sys.executable, args=["-c", script], **kwargs)
        process.replies = []
        process.replied.connect(lambda *reply: process.replies.append(reply))
        made.append(process)
        return process

    yield make
    for process in made:
        process.stop()


def test_an_idle_worker_is_released_and_the_next_request_starts_it_again(worker, qt_app) -> None:
    process = worker(ECHO, idle_s=IDLE)
    wait_until(qt_app, lambda: process.ready)
    first = process.pid
    process.request(1, '{"type": "Circle"}')
    wait_until(qt_app, lambda: process.replies == [(1, True, "")])
    assert not process.asleep
    wait_until(qt_app, lambda: process.asleep)  # nothing to do for IDLE seconds
    assert process.pid is None and not process.ready and process.available
    process.request(2, '{"type": "Square"}')  # a request wakes it, and waits until it is ready
    assert not process.asleep
    wait_until(qt_app, lambda: len(process.replies) == 2)
    assert process.replies[1] == (2, True, "") and process.pid not in (None, first)


def test_a_lazy_worker_runs_no_process_until_the_first_request(worker, qt_app) -> None:
    process = worker(ECHO, idle_s=IDLE, lazy=True)
    assert process.asleep and process.pid is None and process.available
    assert stays(qt_app, lambda: process.pid is None, IDLE * 2)  # it is not "idle" before it ever ran
    process.request(1, '{"type": "Circle"}')
    assert not process.asleep
    wait_until(qt_app, lambda: process.replies == [(1, True, "")])
    assert process.pid is not None


def test_a_worker_with_a_request_on_its_hands_is_not_released(worker, qt_app) -> None:
    process = worker(SILENT, idle_s=IDLE, timeout_s=60)  # never answers
    wait_until(qt_app, lambda: process.ready)
    process.request(1, '{"type": "Circle"}')
    assert stays(qt_app, lambda: not process.asleep, IDLE * 3)


def test_a_worker_that_is_used_often_enough_is_never_released(worker, qt_app) -> None:
    process = worker(ECHO, idle_s=IDLE * 2)
    wait_until(qt_app, lambda: process.ready)
    for request_id in range(1, 6):
        process.request(request_id, '{"type": "Circle"}')
        assert stays(qt_app, lambda: not process.asleep, IDLE)  # each reply starts the countdown again
    assert len(process.replies) == 5


def test_without_idle_seconds_the_worker_stays_for_good(worker, qt_app) -> None:
    process = worker(ECHO)
    wait_until(qt_app, lambda: process.ready)
    assert stays(qt_app, lambda: process.ready and not process.asleep, IDLE * 3)


def test_a_released_worker_can_be_stopped_and_gives_nothing_back(worker, qt_app) -> None:
    process = worker(ECHO, idle_s=IDLE)
    wait_until(qt_app, lambda: process.asleep)
    process.stop()
    assert process.pid is None


def test_idle_seconds_come_from_the_environment_or_the_default(monkeypatch) -> None:
    monkeypatch.delenv("MANIM_STUDIO_IDLE_SECONDS", raising=False)
    assert worker_process.idle_seconds(600.0) == 600.0
    monkeypatch.setenv("MANIM_STUDIO_IDLE_SECONDS", "42")
    assert worker_process.idle_seconds(600.0) == 42.0
    monkeypatch.setenv("MANIM_STUDIO_IDLE_SECONDS", "0")
    assert worker_process.idle_seconds(600.0) is None  # never release
    monkeypatch.setenv("MANIM_STUDIO_IDLE_SECONDS", "soon")
    assert worker_process.idle_seconds(600.0) == 600.0


# -- the frame renderer -----------------------------------------------------------------------------


@pytest.fixture
def preview(qt_app, tmp_path):
    made = []

    def make(**kwargs) -> PreviewProcess:
        process = PreviewProcess(tmp_path, program=sys.executable, args=["-c", PREVIEW], **kwargs)
        process.failures = []
        process.failed.connect(process.failures.append)
        made.append(process)
        return process

    yield make
    for process in made:
        process.stop()


def test_an_idle_preview_process_is_released_and_a_wanted_frame_starts_it_again(preview, qt_app) -> None:
    process = preview(idle_s=IDLE)
    wait_until(qt_app, lambda: process.ready)
    first = process.pid
    wait_until(qt_app, lambda: process.asleep)
    assert process.pid is None and process.available
    process.want([4, 5])  # frames are wanted: it starts again and is told what it missed
    assert not process.asleep
    wait_until(qt_app, lambda: process.failures == [4, 5])
    assert process.pid not in (None, first)


def test_nothing_wanted_does_not_wake_a_released_preview_process(preview, qt_app) -> None:
    process = preview(idle_s=IDLE)
    wait_until(qt_app, lambda: process.asleep)
    process.want([])  # every frame is kept already
    process.media()
    assert stays(qt_app, lambda: process.asleep and process.pid is None, IDLE)


def test_a_preview_process_that_keeps_sending_frames_is_not_released(preview, qt_app) -> None:
    process = preview(idle_s=IDLE * 2)
    wait_until(qt_app, lambda: process.ready)
    for index in range(5):
        process.want([index])
        assert stays(qt_app, lambda: not process.asleep, IDLE)
    assert process.failures == [0, 1, 2, 3, 4]


# -- the code renderer's ready spare ----------------------------------------------------------------


CANVAS = Canvas(width_px=32, height_px=18, fps=10, duration=1.0)


def code_project() -> Project:
    layer = Layer(id="orbit", spec=Spec(type="Code", params={"code": "class A(Scene): pass"}))
    return Project(canvas=CANVAS, layers=[layer])


@pytest.fixture
def renderer(qt_app, tmp_path):
    made = []

    def make(**kwargs) -> CodeRenderService:
        service = CodeRenderService(
            tmp_path / "cache",
            TrustStore(tmp_path / "trust.json"),
            program=sys.executable,
            args=["-c", SPARE, str(tmp_path / "cache")],
            **kwargs,
        )
        made.append(service)
        return service

    yield make
    for service in made:
        service.stop()


def test_a_ready_spare_is_kept_for_a_while_after_code_work_and_then_released(renderer, qt_app) -> None:
    service = renderer(idle_s=IDLE)
    project = code_project()
    service.trust.trust(["class A(Scene): pass"])
    service.sync(project)  # a job: a spare starts and takes it
    wait_until(qt_app, lambda: service.status("orbit").state == "ready")
    wait_until(qt_app, lambda: service.spare_count == 1)  # the next one waits ready
    wait_until(qt_app, lambda: service.spare_count == 0)  # and goes when the work has been quiet for IDLE


def test_a_project_with_code_does_not_start_a_spare_until_code_is_worked_on(renderer, qt_app) -> None:
    service = renderer(idle_s=60)
    project = code_project()
    service.trust.trust(["class A(Scene): pass"])
    # the render is already cached (nothing to queue): an unrelated edit must not start a process
    service.cache.open = lambda key: type("Clip", (), {"frame_count": 3})()
    service.sync(project)
    assert service.status("orbit").state == "ready"
    assert stays(qt_app, lambda: service.spare_count == 0, 0.5)
    service.touch()  # the Code page is shown: someone is about to write code
    assert service.spare_count == 1


def test_without_idle_seconds_the_spare_is_kept_as_before(renderer, qt_app) -> None:
    service = renderer()
    service.trust.trust(["class A(Scene): pass"])
    service.cache.open = lambda key: type("Clip", (), {"frame_count": 3})()
    service.sync(code_project())
    assert service.spare_count == 1  # one ready, always
    assert stays(qt_app, lambda: service.spare_count == 1, IDLE * 2)
