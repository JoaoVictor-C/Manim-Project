"""Helper processes end with the editor, and native thread pools stay small (``manim_studio.lifeline``).

These start real processes (a few Python interpreters that only sleep), so each test is a second or two."""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from manim_studio import lifeline

SLEEP = "import time; time.sleep(120)"
SRC = str(Path(__file__).resolve().parent.parent / "src")


def wait_until(condition, timeout: float = 15.0, step: float = 0.1) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(step)
    return condition()


def clean_env(**extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k != lifeline.EDITOR_PID}
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [SRC, env.get("PYTHONPATH", "")]))
    env.update(extra)
    return env


@pytest.fixture
def spawned():
    """Processes a test starts; whatever is left is ended afterwards."""
    started: list[subprocess.Popen] = []

    def spawn(code: str, **kwargs) -> subprocess.Popen:
        kwargs.setdefault("env", clean_env())
        process = subprocess.Popen([sys.executable, "-c", code], **kwargs)
        started.append(process)
        return process

    yield spawn
    for process in started:
        lifeline.kill_tree(process.pid)
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=10)


# -- native thread pools --------------------------------------------------------------------------


def test_the_native_thread_pools_are_capped_at_one_unless_told_otherwise(monkeypatch) -> None:
    for name in (*lifeline.POOLS, lifeline.NATIVE_THREADS):
        monkeypatch.delenv(name, raising=False)
    lifeline.limit_native_threads()
    assert {os.environ[name] for name in lifeline.POOLS} == {"1"}


def test_a_pool_variable_that_is_already_set_wins(monkeypatch) -> None:
    for name in lifeline.POOLS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENBLAS_NUM_THREADS", "6")
    monkeypatch.setenv(lifeline.NATIVE_THREADS, "3")
    lifeline.limit_native_threads()
    assert os.environ["OPENBLAS_NUM_THREADS"] == "6"  # the user's own choice
    assert os.environ["OMP_NUM_THREADS"] == "3"  # the editor's setting for the rest


@pytest.mark.parametrize("bad", ["0", "-2", "many", ""])
def test_a_nonsense_thread_count_means_one(monkeypatch, bad) -> None:
    for name in lifeline.POOLS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(lifeline.NATIVE_THREADS, bad)
    lifeline.limit_native_threads()
    assert os.environ["OMP_NUM_THREADS"] == "1"


def test_importing_the_package_caps_the_pools_before_numpy_can_read_them() -> None:
    env = clean_env()
    for name in (*lifeline.POOLS, lifeline.NATIVE_THREADS):
        env.pop(name, None)
    names = ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS")
    code = f"import os, manim_studio; print(*(os.environ.get(n) for n in {names!r}))"
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=60)
    assert out.stdout.split() == ["1", "1"], out.stderr


# -- process tables ---------------------------------------------------------------------------------


def test_the_tree_below_a_process_is_found_nearest_first() -> None:
    table = {1: 0, 10: 1, 11: 1, 20: 10, 21: 10, 30: 20, 99: 98}
    assert lifeline.tree_below(table, 1) == [10, 11, 20, 21, 30]
    assert lifeline.tree_below(table, 10) == [20, 21, 30]
    assert lifeline.tree_below(table, 30) == []
    assert lifeline.tree_below(table, 12345) == []


def test_a_process_that_is_its_own_parent_does_not_loop() -> None:
    assert lifeline.tree_below({5: 5, 6: 5}, 5) == [6]


def test_this_process_is_alive_and_a_missing_one_is_not(spawned) -> None:
    assert lifeline.process_alive(os.getpid())
    assert not lifeline.process_alive(0) and not lifeline.process_alive(-4)
    quick = spawned("pass")
    quick.wait(timeout=30)
    assert wait_until(lambda: not lifeline.process_alive(quick.pid))


def test_the_table_has_this_process_under_its_parent() -> None:
    table = lifeline.process_table()
    assert os.getpid() in table and table[os.getpid()] == os.getppid()


# -- ending a tree --------------------------------------------------------------------------------


PARENT_OF_A_SLEEPER = (
    "import subprocess, sys, time\n"
    f"child = subprocess.Popen([sys.executable, '-c', {SLEEP!r}])\n"
    "print(child.pid, flush=True)\n"
    "time.sleep(120)\n"
)


def test_kill_tree_ends_a_process_and_what_it_started(spawned) -> None:
    parent = spawned(PARENT_OF_A_SLEEPER, stdout=subprocess.PIPE, text=True)
    child = int(parent.stdout.readline())
    assert wait_until(lambda: len(lifeline.descendants(parent.pid)) >= 1)
    below = lifeline.descendants(parent.pid)
    assert child in below or any(lifeline.process_alive(p) for p in below)
    lifeline.kill_tree(parent.pid)
    assert wait_until(lambda: not lifeline.process_alive(parent.pid))
    assert wait_until(lambda: not any(lifeline.process_alive(p) for p in [child, *below]))


def test_wait_gone_waits_for_killed_processes_and_gives_up_on_running_ones(spawned) -> None:
    sleeper = spawned(SLEEP)
    started = time.monotonic()
    assert (
        lifeline.wait_gone([sleeper.pid], timeout=0.3) is False
    )  # still running: it gives up at the timeout
    assert 0.25 <= time.monotonic() - started < 5
    lifeline.kill_tree(sleeper.pid)
    assert lifeline.wait_gone([sleeper.pid, 0, -1]) is True  # (what is not a process is not waited for)
    assert lifeline.wait_gone([]) is True


def test_kill_tree_of_a_process_that_is_gone_is_not_an_error() -> None:
    lifeline.kill_tree(2**22 + 17)
    lifeline.kill_tree(0)
    lifeline.kill_tree(os.getpid())  # never itself
    assert lifeline.process_alive(os.getpid())


# -- a helper ends with its editor -------------------------------------------------------------------


WATCHED_HELPER = (
    "import time\n"
    "from manim_studio import lifeline\n"
    "print('watching' if lifeline.die_with_editor() else 'not watching', flush=True)\n"
    "time.sleep(120)\n"
)


def test_a_helper_with_no_editor_named_is_not_watched(spawned) -> None:
    helper = spawned(WATCHED_HELPER, stdout=subprocess.PIPE, text=True)
    assert helper.stdout.readline().strip() == "not watching"


def test_a_helper_ends_when_its_editor_is_gone(spawned) -> None:
    editor = spawned("import time; time.sleep(3)")
    helper = spawned(
        WATCHED_HELPER,
        stdout=subprocess.PIPE,
        text=True,
        env=clean_env(**{lifeline.EDITOR_PID: str(editor.pid)}),
    )
    assert helper.stdout.readline().strip() == "watching"
    assert helper.poll() is None  # the editor is still there
    editor.wait(timeout=30)
    assert wait_until(lambda: helper.poll() is not None, timeout=20), "the helper outlived its editor"


def test_a_helper_started_after_its_editor_died_ends_at_once(spawned) -> None:
    editor = spawned("pass")
    editor.wait(timeout=30)
    helper = spawned(
        WATCHED_HELPER,
        stdout=subprocess.PIPE,
        text=True,
        env=clean_env(**{lifeline.EDITOR_PID: str(editor.pid)}),
    )
    assert wait_until(lambda: helper.poll() is not None, timeout=20)


# -- the job (Windows) ----------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform != "win32", reason="job objects are Windows'")
def test_a_helper_in_the_editors_job_dies_when_the_editor_is_killed(spawned) -> None:
    """The editor is killed the hard way (no chance to clean up) while its helper is busy in a loop that never
    looks at its input: the operating system ends the helper, and what the helper started."""
    editor_code = (
        "import subprocess, sys, time\n"
        "from manim_studio import lifeline\n"
        "busy = subprocess.Popen([sys.executable, '-c', 'while True: pass'])\n"
        "print(busy.pid, lifeline.adopt(busy.pid), flush=True)\n"
        "time.sleep(120)\n"
    )
    editor = spawned(editor_code, stdout=subprocess.PIPE, text=True)
    pid, adopted = editor.stdout.readline().split()
    assert adopted == "True"
    below = [int(pid), *lifeline.descendants(int(pid))]
    assert wait_until(lambda: lifeline.process_alive(int(pid)))
    below = [int(pid), *lifeline.descendants(int(pid))]  # the launcher and the interpreter it started
    editor.kill()  # TerminateProcess: nothing in the editor runs any more
    assert wait_until(lambda: not any(lifeline.process_alive(p) for p in below), timeout=20), (
        "a helper outlived the editor that was killed"
    )


@pytest.mark.skipif(sys.platform != "win32", reason="job objects are Windows'")
def test_a_process_that_was_never_adopted_is_left_alone(spawned) -> None:
    editor_code = (
        "import subprocess, sys, time\n"
        "other = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
        "print(other.pid, flush=True)\n"
        "time.sleep(120)\n"
    )
    editor = spawned(editor_code, stdout=subprocess.PIPE, text=True)
    pid = int(editor.stdout.readline())
    editor.kill()
    time.sleep(1.5)
    assert lifeline.process_alive(pid)  # a document opened in another program must not close with the editor
    lifeline.kill_tree(pid)


def test_adopting_a_missing_process_says_so() -> None:
    assert lifeline.adopt(0) is False
    assert lifeline.adopt(-1) is False
    if sys.platform == "win32":
        assert lifeline.adopt(2**22 + 17) is False


# -- every helper asks to be watched ----------------------------------------------------------------


def test_every_process_entry_point_ends_with_its_editor() -> None:
    root = Path(SRC) / "manim_studio"
    for name in ("worker", "preview", "code_runner", "helper_check", "voice", "scene_recorder"):
        text = (root / "processes" / f"{name}.py").read_text(encoding="utf-8")
        assert "lifeline.die_with_editor()" in text, name
    assert "lifeline.die_with_editor()" in (root / "cli.py").read_text(encoding="utf-8")  # the export
