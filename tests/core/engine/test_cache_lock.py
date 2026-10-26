"""One process at a time writes Manim's text and LaTeX cache (the editor, its build worker and
the render-ahead process share it; a reader once found a text SVG half-written)."""

from __future__ import annotations

import subprocess
import sys
import textwrap
import time
import uuid

import pytest

from manim_studio.core.engine import adapter
from manim_studio.core.model.schema import Spec

HOLDER = textwrap.dedent(
    """
    import sys, time
    path, seconds = sys.argv[1], float(sys.argv[2])
    with open(path, "a+b") as file:
        file.seek(0)
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(file.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(file.fileno(), fcntl.LOCK_EX)
        print("held", flush=True)
        time.sleep(seconds)
    """
)


def hold(seconds: float) -> subprocess.Popen:
    """Another process holding the cache's lock for ``seconds``."""
    folder = adapter.cache_dir()
    folder.mkdir(parents=True, exist_ok=True)
    process = subprocess.Popen(
        [sys.executable, "-c", HOLDER, str(folder / ".build.lock"), str(seconds)],
        stdout=subprocess.PIPE,
        text=True,
    )
    assert process.stdout.readline().strip() == "held"
    return process


def test_the_lock_waits_for_another_process() -> None:
    holder = hold(1.0)
    start = time.monotonic()
    with adapter.cache_lock():
        waited = time.monotonic() - start
    holder.wait()
    assert waited >= 0.7


def test_a_lock_held_too_long_is_given_up() -> None:
    holder = hold(5.0)
    start = time.monotonic()
    with adapter.cache_lock(timeout=0.3):
        waited = time.monotonic() - start
    holder.kill()
    holder.wait()
    assert 0.25 <= waited < 3.0


def test_the_lock_is_reentrant_in_a_thread() -> None:
    with adapter.cache_lock(timeout=1.0), adapter.cache_lock(timeout=1.0):
        pass


@pytest.mark.parametrize(
    "spec",
    [
        Spec(type="Text", params={"text": f"lock {uuid.uuid4().hex[:8]}"}),
        Spec(type="MathTex", params={"text": rf"x + \text{{{uuid.uuid4().hex[:8]}}}"}),
    ],
    ids=["text", "latex"],
)
def test_building_a_new_text_or_formula_takes_the_lock(spec: Spec, monkeypatch) -> None:
    taken = []
    real = adapter.cache_lock

    def spy(*args, **kwargs):
        taken.append(spec.type)
        return real(*args, **kwargs)

    monkeypatch.setattr(adapter, "cache_lock", spy)
    adapter.build_mobject(spec)
    assert taken  # a timing check passed without the lock: a first LaTeX compile is that slow
