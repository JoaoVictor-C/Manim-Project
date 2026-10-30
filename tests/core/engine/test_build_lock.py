"""The lock between processes that build into one Manim cache (ADR 0065)."""

from __future__ import annotations

import subprocess
import sys
import time

from manim_studio.core.engine.build_lock import BuildLock

# A process that takes the lock, writes "in", holds it a moment, writes "out" and lets go.
HOLDER = """
import sys, time
from manim_studio.core.engine.build_lock import BuildLock
lock, log, hold = sys.argv[1], sys.argv[2], float(sys.argv[3])
with BuildLock(lock):
    with open(log, "a") as f: f.write("in\\n")
    time.sleep(hold)
    with open(log, "a") as f: f.write("out\\n")
"""


def spawn(lock, log, hold: float = 0.4, wait_for: float = 0.0) -> subprocess.Popen:
    process = subprocess.Popen([sys.executable, "-c", HOLDER, str(lock), str(log), str(hold)])
    time.sleep(wait_for)
    return process


def test_two_processes_never_hold_it_together(tmp_path) -> None:
    lock, log = tmp_path / "build.lock", tmp_path / "log.txt"
    first = spawn(lock, log, wait_for=0.0)
    second = spawn(lock, log)
    for process in (first, second):
        assert process.wait(timeout=60) == 0
    # in/out pairs never interleave (in, in, out, out would mean both held it at once)
    assert log.read_text().split() == ["in", "out", "in", "out"]


def test_it_is_reentrant_in_one_process(tmp_path) -> None:
    lock = BuildLock(tmp_path / "build.lock")
    with lock:
        with lock:  # a build inside a build (an Axes builds its labels)
            pass
        # still held: another process cannot take it
        other = BuildLock(tmp_path / "build.lock")
        assert not _can_take(other)
    assert _can_take(BuildLock(tmp_path / "build.lock"))


def _can_take(lock: BuildLock) -> bool:
    """Whether ``lock`` can be taken right now by another handle (tried without waiting)."""
    import os

    from manim_studio.core.engine import build_lock

    file = os.open(lock.path, os.O_RDWR | os.O_CREAT)
    try:
        if sys.platform == "win32":
            import msvcrt

            try:
                msvcrt.locking(file, msvcrt.LK_NBLCK, 1)
            except OSError:
                return False
            os.lseek(file, 0, os.SEEK_SET)
            msvcrt.locking(file, msvcrt.LK_UNLCK, 1)
            return True
        import fcntl

        try:
            fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        build_lock._release(file)
        return True
    finally:
        os.close(file)


def test_a_killed_holder_lets_go_of_it(tmp_path) -> None:
    """The system holds the lock, not a file's existence: a process that dies does not leave it locked."""
    lock, log = tmp_path / "build.lock", tmp_path / "log.txt"
    holder = spawn(lock, log, hold=60, wait_for=0.0)
    deadline = time.monotonic() + 30
    while not log.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert log.exists(), "the holder never took the lock"
    holder.kill()
    holder.wait(timeout=10)
    taker = BuildLock(lock)
    started = time.monotonic()
    with taker:
        pass
    assert time.monotonic() - started < 10


def test_the_lock_file_is_made_where_asked(tmp_path) -> None:
    path = tmp_path / "deep" / "er" / "build.lock"
    with BuildLock(path):
        assert path.exists()
