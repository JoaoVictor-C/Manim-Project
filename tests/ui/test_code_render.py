"""Rendering code layers from the editor (P2d.3, ADR 0019).

Lifecycle rules run against a stand-in runner that speaks the protocol and
writes a tiny cache without importing Manim (a second per test); the real
runner is checked once end to end, including the warm-spare latency.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys
import time

import pytest

pytest.importorskip("PySide6")

from manim_studio.core.evaluator import code_key
from manim_studio.core.schema import Canvas, Layer, Project, Spec
from manim_studio.core.trust import TrustStore
from manim_studio.ui.code_render import CodeRenderService

pytestmark = [pytest.mark.ui, pytest.mark.slow]  # starts real processes

STAND_IN = r"""
import json, sys, time
from pathlib import Path
import numpy as np
from manim_studio.core.code_cache import CodeCache
print("some stray output", flush=True)
print(json.dumps({"ready": True}), flush=True)
line = sys.stdin.readline()
if not line.strip():
    sys.exit(0)
job = json.loads(line)
code = job["code"]
if "SLEEP" in code:
    time.sleep(60)
if "FAIL" in code:
    print(json.dumps({"error": "ValueError: nope", "line": 2}), flush=True)
    sys.exit(1)
if "STRUCT" in code:
    print(json.dumps({"error": "NameError: name 'x' is not defined", "line": 3, "type": "NameError",
                      "where": "helper:geo", "traceback": "Traceback\n  line 3"}), flush=True)
    sys.exit(1)
if "CRASH" in code:
    sys.exit(3)
writer = CodeCache(Path(sys.argv[1]) / "code").writer(job["key"], job["width"], job["height"], job["fps"])
for i in range(3):
    frame = np.zeros((job["height"], job["width"], 4), np.uint8)
    frame[i, i] = 255
    writer.add(frame)
    print(json.dumps({"frame": i + 1}), flush=True)
writer.finish()
print(json.dumps({"done": True, "frames": 3}), flush=True)
"""

CANVAS = Canvas(width_px=32, height_px=18, fps=10, duration=1.0)


def wait_until(qt_app, condition, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("timed out waiting")
        qt_app.processEvents()
        time.sleep(0.01)


def project(**codes: str) -> Project:
    layers = [Layer(id=i, spec=Spec(type="Code", params={"code": c})) for i, c in codes.items()]
    return Project(canvas=CANVAS, layers=[*layers, Layer(id="sq", spec=Spec(type="Square"))])


@pytest.fixture
def service(qt_app, tmp_path):
    trust = TrustStore(tmp_path / "trust.json")
    svc = CodeRenderService(
        tmp_path / "cache", trust, program=sys.executable, args=["-c", STAND_IN, str(tmp_path / "cache")]
    )
    svc.events = []
    svc.statusChanged.connect(lambda i: svc.events.append((i, svc.status(i).state)))
    svc.rendered.connect(lambda i: svc.events.append((i, "rendered")))
    yield svc
    svc.stop()


def trusted(service, p: Project) -> Project:
    service.trust.trust([str(layer.spec.params["code"]) for layer in p.layers if layer.spec.type == "Code"])
    return p


def test_trusted_code_layers_render_through_a_spare(service, qt_app) -> None:
    assert service.spare_count == 0  # nothing started for a project without code
    p = trusted(service, project(orbit="class A(Scene): pass"))
    service.sync(p)
    assert service.status("orbit").state == "queued" and service.spare_count == 1
    wait_until(qt_app, lambda: service.status("orbit").state == "ready")
    assert ("orbit", "rendered") in service.events
    assert [s for i, s in service.events if i == "orbit"][:2] == ["queued", "rendering"]
    assert service.cache.open(code_key(p, p.layer("orbit"))).frame_count == 3
    assert service.status("orbit").text == "Ready - 3 frames"
    wait_until(qt_app, lambda: service.spare_count == 1)  # a fresh spare waits for the next edit
    service.sync(p)  # nothing to do: already cached
    assert service.status("orbit").state == "ready"


def test_untrusted_code_never_runs(service, qt_app) -> None:
    p = project(theirs="class A(Scene): pass")
    service.sync(p)
    assert service.status("theirs").state == "untrusted"
    assert service.spare_count == 0  # not even a spare
    service.trust_layers(p, ["theirs"])
    wait_until(qt_app, lambda: service.status("theirs").state == "ready")


def test_new_code_replaces_a_running_render(service, qt_app) -> None:
    slow = trusted(service, project(c="SLEEP"))
    service.sync(slow)
    wait_until(qt_app, lambda: service.status("c").state == "rendering")
    fast = trusted(service, project(c="class B(Scene): pass"))
    service.sync(fast)
    wait_until(qt_app, lambda: service.status("c").state == "ready", timeout=40)
    assert ("c", "error") not in service.events  # the killed render is not an error


def test_cancel_stops_a_running_render_and_a_retry_renders_again(service, qt_app) -> None:
    p = trusted(service, project(c="SLEEP"))
    service.sync(p)
    wait_until(qt_app, lambda: service.status("c").state == "rendering")
    assert service.cancel("c") and service.status("c").state == "cancelled"
    assert service.status("c").text.startswith("Cancelled")
    service.sync(p)  # the same code does not start again by itself
    assert service.status("c").state == "cancelled"
    wait_until(qt_app, lambda: service.spare_count == 1)  # a warm spare replaced the killed process
    assert not service.cancel("c")  # nothing left to stop
    service.retry("c")
    wait_until(qt_app, lambda: service.status("c").state == "rendering")


def test_cancel_drops_a_queued_render(service, qt_app) -> None:
    service.max_spares = 1
    p = trusted(service, project(a="SLEEP", b="class B(Scene): pass"))
    service.sync(p)
    wait_until(qt_app, lambda: service.status("a").state == "rendering")
    assert service.status("b").state == "queued"
    assert service.cancel("b") and service.status("b").state == "cancelled"


def test_errors_keep_their_line_until_the_code_changes_or_a_retry(service, qt_app) -> None:
    p = trusted(service, project(c="FAIL"))
    service.sync(p)
    wait_until(qt_app, lambda: service.status("c").state == "error")
    assert (service.status("c").error, service.status("c").line) == ("ValueError: nope", 2)
    assert service.status("c").text == "Error - line 2: ValueError: nope"
    service.sync(p)  # same code: not run again
    assert service.status("c").state == "error"
    service.retry("c")
    assert service.status("c").state == "queued"


def test_structured_errors_keep_type_where_and_traceback(service, qt_app) -> None:
    service.sync(trusted(service, project(c="STRUCT")))
    wait_until(qt_app, lambda: service.status("c").state == "error")
    status = service.status("c")
    assert (status.error_type, status.where, status.traceback) == (
        "NameError",
        "helper:geo",
        "Traceback\n  line 3",
    )
    assert status.line == 3


def test_an_old_message_without_a_type_is_read_from_its_text(service, qt_app) -> None:
    service.sync(trusted(service, project(c="FAIL")))  # the stand-in sends only error and line
    wait_until(qt_app, lambda: service.status("c").state == "error")
    status = service.status("c")
    assert (status.error_type, status.where, status.traceback) == ("ValueError", "code", "")


def test_a_crash_and_a_timeout_are_errors(service, qt_app) -> None:
    service.sync(trusted(service, project(c="CRASH")))
    wait_until(qt_app, lambda: service.status("c").state == "error")
    assert "stopped unexpectedly" in service.status("c").error
    service.timeout_s = 0.5
    service.sync(trusted(service, project(c="SLEEP again")))
    wait_until(qt_app, lambda: service.status("c").state == "error")
    assert "longer than 0.5 s" in service.status("c").error
    assert service.status("c").error_type == "TimeoutError"


def test_spares_stop_when_no_code_layer_remains(service, qt_app) -> None:
    service.sync(trusted(service, project(c="class A(Scene): pass")))
    wait_until(qt_app, lambda: service.status("c").state == "ready")
    service.sync(Project(canvas=CANVAS, layers=[Layer(id="sq", spec=Spec(type="Square"))]))
    wait_until(qt_app, lambda: service.spare_count == 0)
    assert service.status("c") is None


def test_a_runner_that_cannot_start_is_reported_once(qt_app, tmp_path) -> None:
    svc = CodeRenderService(
        tmp_path, TrustStore(tmp_path / "t.json"), program=sys.executable, args=["-c", "raise SystemExit(2)"]
    )
    try:
        p = trusted(svc, project(c="class A(Scene): pass"))
        svc.sync(p)
        wait_until(qt_app, lambda: svc.status("c").state == "error")
        assert "could not start" in svc.status("c").error
        wait_until(qt_app, lambda: svc.spare_count == 0)
    finally:
        svc.stop()


@pytest.mark.latex
def test_a_warm_spare_renders_real_code_in_about_a_second(qt_app, tmp_path) -> None:
    """B31: once the spare has imported Manim, a short scene's first frames arrive quickly."""
    svc = CodeRenderService(tmp_path / "cache", TrustStore(tmp_path / "t.json"))
    try:
        warm = trusted(
            svc, project(c="class S(Scene):\n    def construct(self):\n        self.add(Circle())\n")
        )
        svc.sync(warm)
        wait_until(qt_app, lambda: svc.status("c").state == "ready", timeout=120)  # pays the import
        wait_until(qt_app, lambda: any(s.ready and s.job is None for s in svc._spares), timeout=120)
        code = "class T(Scene):\n    def construct(self):\n        self.play(Create(Square()), run_time=1)\n"
        edited = trusted(svc, project(c=code))
        started = time.monotonic()
        svc.sync(edited)
        wait_until(qt_app, lambda: svc.status("c").state == "ready", timeout=60)
        elapsed = time.monotonic() - started
        print(f"warm render of a 1 s scene: {elapsed:.2f} s")
        assert elapsed < 5.0  # a cold process needs 6-8 s before its first frame (B30)
        assert svc.cache.open(code_key(edited, edited.layer("c"))).frame_count == CANVAS.fps
    finally:
        svc.stop()
