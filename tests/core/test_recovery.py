"""Recovery copies on disk (P5d.3, ADR 0038): names, atomic files, what is offered back,
pruning, and telling whether the owner is still running."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from manim_studio.core import recovery
from manim_studio.core.schema import Canvas, Layer, Project, Spec

PROJECT = Project(canvas=Canvas(duration=2.0), layers=[Layer(id="dot", spec=Spec(type="Dot"))])
DAY = 86400.0


def dead_pid() -> int:
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait()
    return process.pid


@pytest.fixture
def sleeper():
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    yield process.pid
    process.kill()
    process.wait()


def never_alive(_pid: int) -> bool:
    return False


def test_names_follow_the_path_and_the_owner(tmp_path) -> None:
    a = recovery.stem_for(tmp_path / "scene.json", 10, 1)
    assert a == recovery.stem_for(Path(str(tmp_path / "x" / ".." / "scene.json")), 10, 7)  # n is for untitled
    assert a.endswith("-10") and len(a) == 16 + 3
    assert a != recovery.stem_for(tmp_path / "scene.json", 11, 1)  # another instance: another file
    assert a != recovery.stem_for(tmp_path / "other.json", 10, 1)
    assert recovery.stem_for(None, 10, 3) == "untitled-10-3"
    if sys.platform == "win32":
        assert a == recovery.stem_for(Path(str(tmp_path / "SCENE.JSON")), 10, 1)


def test_a_copy_is_a_project_file_and_a_sidecar(tmp_path) -> None:
    folder = tmp_path / "recovery"
    entry = recovery.write(folder, "s-1", PROJECT, tmp_path / "scene.json", 42, 1000.0)
    assert recovery.read_project(entry) == PROJECT
    meta = json.loads(entry.meta_file.read_text(encoding="utf-8"))
    assert meta == {"path": str(tmp_path / "scene.json"), "pid": 42, "saved_at": 1000.0}
    names = sorted(p.name for p in folder.iterdir())
    assert [n for n in names if not n.endswith(".tmp")] == ["s-1.json", "s-1.meta.json"]
    assert not any(n.endswith(f".{os.getpid()}.tmp") for n in names)  # our temporary files are gone
    (listed,) = recovery.entries(folder)
    assert listed == entry and listed.name == "scene.json"
    recovery.remove(folder, "s-1")
    assert list(folder.glob("*.json")) == []
    recovery.remove(folder, "s-1")  # twice is fine


def test_a_failed_write_keeps_the_previous_copy(tmp_path, monkeypatch) -> None:
    folder = tmp_path / "recovery"
    recovery.write(folder, "s-1", PROJECT, None, 42, 1000.0)
    changed = PROJECT.model_copy(update={"canvas": Canvas(duration=3.0)})

    def broken(*_args):
        raise OSError("disk full")

    monkeypatch.setattr(recovery.os, "replace", broken)
    with pytest.raises(OSError):
        recovery.write(folder, "s-1", changed, None, 42, 2000.0)
    monkeypatch.undo()
    (entry,) = recovery.entries(folder)
    assert recovery.read_project(entry) == PROJECT and entry.saved_at == 1000.0


def test_entries_are_newest_first_and_skip_what_is_not_a_copy(tmp_path) -> None:
    folder = tmp_path / "recovery"
    assert recovery.entries(folder) == []  # no folder yet
    recovery.write(folder, "old", PROJECT, None, 1, 100.0)
    recovery.write(folder, "new", PROJECT, None, 1, 200.0)
    (folder / "junk.meta.json").write_text("not json", encoding="utf-8")
    (folder / "lonely.meta.json").write_text('{"path": null, "pid": 1, "saved_at": 1}', encoding="utf-8")
    assert [e.stem for e in recovery.entries(folder)] == ["new", "old"]


def test_only_dead_owners_newer_copies_are_offered(tmp_path) -> None:
    folder = tmp_path / "recovery"
    saved = tmp_path / "scene.json"
    saved.write_text("{}", encoding="utf-8")
    now = time.time()
    recovery.write(folder, "newer", PROJECT, saved, 101, now + 10)
    recovery.write(folder, "older", PROJECT, saved, 102, now - 1000)
    os.utime(saved, (now, now))
    recovery.write(folder, "running", PROJECT, saved, 103, now + 10)
    recovery.write(folder, "mine", PROJECT, saved, 104, now + 10)
    recovery.write(folder, "untitled", PROJECT, None, 105, now - 5000)
    recovery.write(folder, "gone", PROJECT, tmp_path / "deleted.json", 106, now - 6000)

    def alive(pid: int) -> bool:
        return pid == 103

    offered = recovery.offered(folder, alive=alive, own_pid=104)
    assert [e.stem for e in offered] == ["newer", "untitled", "gone"]
    assert [e.stem for e in recovery.offered(folder, saved, alive=alive, own_pid=104)] == ["newer"]
    assert recovery.offered(folder, tmp_path / "nothing.json", alive=alive, own_pid=104) == []


def test_stale_copies_are_kept_then_pruned(tmp_path) -> None:
    folder = tmp_path / "recovery"
    saved = tmp_path / "scene.json"
    saved.write_text("{}", encoding="utf-8")
    now = time.time()
    os.utime(saved, (now, now))
    recovery.write(folder, "stale-old", PROJECT, saved, 1, now - 15 * DAY)
    recovery.write(folder, "stale-recent", PROJECT, saved, 2, now - 1 * DAY)
    recovery.write(folder, "offered-old", PROJECT, None, 3, now - 30 * DAY)  # never pruned while offered
    recovery.write(folder, "running-old", PROJECT, saved, 4, now - 30 * DAY)
    os.utime(folder / "running-old.json", (now - 30 * DAY, now - 30 * DAY))  # it has a sidecar: not an orphan
    recovery.write(folder, "mine-old", PROJECT, saved, 99, now - 30 * DAY)  # this instance's own
    orphan = folder / "orphan.json"
    orphan.write_text("{}", encoding="utf-8")
    os.utime(orphan, (now - 20 * DAY, now - 20 * DAY))
    young = folder / "young.json"
    young.write_text("{}", encoding="utf-8")
    gone = recovery.prune(folder, now, alive=lambda pid: pid == 4, own_pid=99)
    assert sorted(gone) == ["orphan", "stale-old"]
    left = sorted(p.name for p in folder.glob("*.json"))  # (a virus scanner may leave a .tmp briefly)
    assert left == [
        "mine-old.json",
        "mine-old.meta.json",
        "offered-old.json",
        "offered-old.meta.json",
        "running-old.json",
        "running-old.meta.json",
        "stale-recent.json",
        "stale-recent.meta.json",
        "young.json",
    ]
    assert recovery.prune(tmp_path / "missing") == []


def test_telling_whether_a_process_runs(sleeper) -> None:
    assert recovery.pid_alive(os.getpid())
    assert recovery.pid_alive(sleeper)
    assert not recovery.pid_alive(dead_pid())
    assert not recovery.pid_alive(0) and not recovery.pid_alive(-5)
    assert not recovery.pid_alive(0x7FFFFFF0)  # no such process (on Windows: OpenProcess fails)


def test_without_psutil_the_system_is_asked(sleeper, monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "psutil", None)  # import fails
    assert recovery.pid_alive(sleeper)
    assert not recovery.pid_alive(dead_pid())


def test_with_psutil_it_is_used(monkeypatch) -> None:
    class FakePsutil:
        @staticmethod
        def pid_exists(pid: int) -> bool:
            return pid == 12345

    monkeypatch.setitem(sys.modules, "psutil", FakePsutil)
    assert recovery.pid_alive(12345) and not recovery.pid_alive(12346)
