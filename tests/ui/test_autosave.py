"""Autosave and crash recovery in the editor (P5d.3, ADR 0038): the timer writes unsaved work
only, the copy goes when the work is saved or thrown away, and a dead instance's copy is offered
back - restored as unsaved changes to the original file, or deleted."""

from __future__ import annotations

import json
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from core.test_recovery import dead_pid, sleeper  # noqa: F401 - a fixture
from manim_studio.core import edits, recovery
from manim_studio.core.schema import Canvas, Layer, Project, Spec
from manim_studio.ui import autosave
from manim_studio.ui.main_window import MainWindow
from ui.test_acceptance_v1 import menu_action, wait_until

pytestmark = pytest.mark.ui

PROJECT = Project(canvas=Canvas(width_px=320, height_px=180, fps=10, duration=2.0), layers=[])


@pytest.fixture
def folder(tmp_path, monkeypatch):
    path = tmp_path / "recovery"
    monkeypatch.setenv(autosave.RECOVERY_ENV, str(path))
    return path


@pytest.fixture
def saved(tmp_path):
    path = tmp_path / "scene.json"
    path.write_text(PROJECT.model_dump_json(by_alias=True), encoding="utf-8")
    return path


@pytest.fixture
def window(qt_app, folder, saved):
    win = MainWindow()
    win.show()
    win.load(saved)
    yield win
    win.close()


def edit(window, name: str = "dot") -> None:
    window.document.apply(edits.add_layer(window.project, Spec(type="Dot"), layer_id=name), "Add dot")


def copies(folder) -> list[str]:
    return sorted(p.name for p in folder.glob("*.json"))  # (a virus scanner may leave a .tmp briefly)


def leave_copy(
    folder, project: Project, path, pid: int, saved_at: float | None = None, n: int = 1
) -> recovery.Entry:
    """What a crashed instance leaves behind."""
    stem = recovery.stem_for(path, pid, n)
    return recovery.write(folder, stem, project, path, pid, time.time() + 5 if saved_at is None else saved_at)


def test_the_recovery_folder_comes_from_the_environment_or_app_data(folder, monkeypatch) -> None:
    assert autosave.recovery_dir() == folder
    monkeypatch.delenv(autosave.RECOVERY_ENV)
    assert autosave.recovery_dir().name == "recovery"
    assert autosave.INTERVAL_MS == 30_000


def test_the_timer_writes_unsaved_work_only(window, folder, monkeypatch) -> None:
    assert window.autosave.timer.isActive() and window.autosave.folder == folder
    window.autosave.tick()
    assert copies(folder) == []  # nothing unsaved
    edit(window)
    writes = []
    real = recovery.write
    monkeypatch.setattr(recovery, "write", lambda *a: writes.append(a) or real(*a))
    window.autosave.tick()
    stem = recovery.stem_for(window.path, os.getpid(), window.autosave._n)
    assert copies(folder) == [f"{stem}.json", f"{stem}.meta.json"]
    entry = window.autosave.written
    assert recovery.read_project(entry) == window.project and entry.path == window.path
    assert entry.pid == os.getpid()
    window.autosave.tick()
    assert len(writes) == 1  # the same snapshot is not written twice
    edit(window, "dot2")
    window.autosave.tick()
    assert len(writes) == 2 and recovery.read_project(window.autosave.written) == window.project


def test_the_timer_fires_by_itself(window, folder, qt_app) -> None:
    window.autosave.timer.setInterval(20)
    edit(window)
    wait_until(qt_app, lambda: len(copies(folder)) == 2, timeout=5)


def test_nothing_is_written_during_a_drag_or_without_a_project(qt_app, folder) -> None:
    win = MainWindow()
    try:
        win.autosave.tick()
        assert copies(folder) == []
        win.document.replace(PROJECT)
        win.document.begin_preview()
        win.document.preview(edits.add_layer(win.project, Spec(type="Dot")))
        win.autosave.tick()
        assert copies(folder) == []
        win.document.commit_preview("Add dot")
        win.autosave.tick()
        assert len(copies(folder)) == 2
        assert win.autosave.written.stem.startswith(f"untitled-{os.getpid()}-")
    finally:
        win.close()


def test_saving_or_undoing_to_the_saved_state_deletes_the_copy(window, folder) -> None:
    edit(window)
    window.autosave.tick()
    window.save()
    assert copies(folder) == []
    edit(window, "dot2")
    window.autosave.tick()
    window.document.undo_stack.undo()
    assert copies(folder) == []
    window.document.undo_stack.redo()
    window.autosave.tick()
    assert len(copies(folder)) == 2


def test_new_open_and_a_discarding_close_delete_the_copy(window, folder, saved, monkeypatch) -> None:
    edit(window)
    window.autosave.tick()
    menu_action(window.menuBar(), "File", "New").trigger()  # ask_unsaved: "discard" (conftest)
    assert copies(folder) == []
    edit(window)
    window.autosave.tick()
    window.load(saved)
    assert copies(folder) == []
    edit(window)
    window.autosave.tick()
    monkeypatch.setattr(MainWindow, "ask_unsaved", lambda self: "cancel")
    assert not window.close()
    assert len(copies(folder)) == 2  # still open: still protected
    monkeypatch.setattr(MainWindow, "ask_unsaved", lambda self: "discard")
    assert window.close()
    assert copies(folder) == []


def test_a_dead_instances_copy_is_offered_when_its_file_opens(qt_app, folder, saved, monkeypatch) -> None:
    unsaved = PROJECT.model_copy(update={"layers": [Layer(id="dot", spec=Spec(type="Dot"))]})
    old = leave_copy(folder, unsaved, saved, dead_pid())
    asked = []
    monkeypatch.setattr(MainWindow, "ask_recover", lambda self, entries: asked.append(entries) or "restore")
    win = MainWindow()
    try:
        win.load(saved)
        assert [[e.stem for e in entries] for entries in asked] == [[old.stem]]
        assert win.project == unsaved and win.path == saved
        assert not win.document.undo_stack.isClean() and win.windowTitle().endswith("scene.json *")
        mine = recovery.stem_for(saved, os.getpid(), win.autosave._n)
        assert copies(folder) == [f"{mine}.json", f"{mine}.meta.json"]  # taken over by this instance
        win.save()
        assert Project.model_validate_json(saved.read_text(encoding="utf-8")) == unsaved
        assert copies(folder) == []
    finally:
        win.close()


def test_a_running_instances_copy_is_left_alone(qt_app, folder, saved, sleeper, monkeypatch) -> None:  # noqa: F811
    theirs = leave_copy(folder, PROJECT, saved, sleeper)
    monkeypatch.setattr(MainWindow, "ask_recover", lambda self, entries: pytest.fail("asked"))
    win = MainWindow()
    try:
        win.load(saved)
        assert not win.check_recovery()
        edit(win)
        win.autosave.tick()
        win.save()
    finally:
        win.close()
    assert sorted(copies(folder)) == sorted([theirs.project_file.name, theirs.meta_file.name])


def test_declining_deletes_and_later_keeps(qt_app, folder, saved, monkeypatch) -> None:
    pid = dead_pid()
    leave_copy(folder, PROJECT, saved, pid)
    answers = iter(["later", "discard"])
    monkeypatch.setattr(MainWindow, "ask_recover", lambda self, entries: next(answers))
    win = MainWindow()
    try:
        win.load(saved)
        assert len(copies(folder)) == 2 and win.document.undo_stack.isClean()
        win.load(saved)
        assert copies(folder) == [] and win.document.undo_stack.isClean() and win.path == saved
    finally:
        win.close()


def test_a_copy_older_than_the_saved_file_is_not_offered(qt_app, folder, saved, monkeypatch) -> None:
    leave_copy(folder, PROJECT, saved, dead_pid(), saved_at=saved.stat().st_mtime - 60)
    monkeypatch.setattr(MainWindow, "ask_recover", lambda self, entries: pytest.fail("asked"))
    win = MainWindow()
    try:
        win.load(saved)
        assert not win.check_recovery()
    finally:
        win.close()
    assert len(copies(folder)) == 2  # kept (pruned after 14 days)


def test_at_start_up_an_untitled_crash_is_restored_as_unsaved(qt_app, folder, monkeypatch) -> None:
    lost = PROJECT.model_copy(update={"layers": [Layer(id="sq", spec=Spec(type="Square"))]})
    pid = dead_pid()
    first = leave_copy(folder, lost, None, pid, saved_at=time.time() - 10, n=1)
    newest = leave_copy(folder, lost.model_copy(update={"layers": []}), None, pid, n=2)
    offered = []
    monkeypatch.setattr(MainWindow, "ask_recover", lambda self, entries: offered.append(entries) or "restore")
    win = MainWindow()
    try:
        assert win.check_recovery()
        assert [e.stem for e in offered[0]] == [newest.stem, first.stem]
        assert win.path is None and win.project.layers == [] and not win.document.undo_stack.isClean()
        names = copies(folder)
        assert first.project_file.name in names and newest.project_file.name not in names  # one per start
    finally:
        win.close()


def test_a_damaged_copy_is_reported_and_kept(qt_app, folder, saved, monkeypatch) -> None:
    entry = leave_copy(folder, PROJECT, saved, dead_pid())
    entry.project_file.write_text("{ broken", encoding="utf-8")
    monkeypatch.setattr(MainWindow, "ask_recover", lambda self, entries: "restore")
    shown = []
    monkeypatch.setattr("manim_studio.ui.main_window.QMessageBox.critical", lambda *a: shown.append(a))
    win = MainWindow()
    try:
        win.load(saved)
        assert shown and win.path == saved and win.document.undo_stack.isClean()  # the saved file opened
    finally:
        win.close()
    assert entry.project_file.exists()


def test_the_recovery_copy_names_the_original_file(window, folder) -> None:
    edit(window)
    window.autosave.tick()
    meta = json.loads(window.autosave.written.meta_file.read_text(encoding="utf-8"))
    assert meta["path"] == str(window.path) and meta["pid"] == os.getpid()
