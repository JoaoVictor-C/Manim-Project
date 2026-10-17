"""Where the editor keeps and suggests files (GP): never the folder it was started from."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from manim_studio.ui import places

pytestmark = pytest.mark.ui


def test_the_cache_is_the_users_unless_overridden(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("MANIM_STUDIO_CACHE", raising=False)
    folder = places.cache_folder()
    assert folder.name == "manim" and Path.cwd() not in folder.parents
    monkeypatch.setenv("MANIM_STUDIO_CACHE", str(tmp_path / "c"))
    assert places.cache_folder() == tmp_path / "c"


def test_a_new_project_is_suggested_next_to_the_last_one(tmp_path, monkeypatch) -> None:
    last = tmp_path / "work" / "last.json"
    last.parent.mkdir()
    gone = tmp_path / "gone" / "old.json"
    assert places.default_folder([gone, last]) == last.parent  # the first that still exists
    monkeypatch.setattr(places, "documents", lambda: tmp_path / "docs")
    assert places.default_folder([]) == Path.home()  # no Documents folder: home
    (tmp_path / "docs").mkdir()
    assert places.default_folder([]) == tmp_path / "docs"
    (tmp_path / "docs" / "Manim Studio").mkdir()
    assert places.default_folder([gone]) == tmp_path / "docs" / "Manim Studio"


def test_the_window_suggests_that_folder_for_saving_and_exporting(qt_app, tmp_path, monkeypatch) -> None:
    from PySide6.QtWidgets import QFileDialog

    from manim_studio.ui.main_window import MainWindow
    from manim_studio.ui.pages.deliver import default_output

    win = MainWindow()
    try:
        monkeypatch.setattr(win, "default_folder", lambda: tmp_path)
        win.new_project()
        asked = {}

        def fake_save(parent, title, start, filter_):
            asked["start"] = start
            return "", ""

        monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(fake_save))
        win.save_as()
        assert Path(asked["start"]) == tmp_path / "untitled.json"
        assert default_output(None, tmp_path) == tmp_path / "out" / "untitled.mp4"
        assert default_output(tmp_path / "x" / "p.json", tmp_path) == tmp_path / "x" / "out" / "p.mp4"
    finally:
        win.document.undo_stack.setClean()
        win.close()
