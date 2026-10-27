"""P6d.1 acceptance (ADR 0044): quit and start again - everything as it was left; a fresh
settings file gives today's defaults. One user story across three sessions."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from manim_studio.core.model.schema import Canvas, Layer, Project, Spec
from manim_studio.ui.main_window import MainWindow

pytestmark = pytest.mark.ui


def write_project(folder: Path, name: str, layers: int) -> Path:
    project = Project(
        canvas=Canvas(width_px=320, height_px=180),
        layers=[Layer(id=f"c{i}", spec=Spec(type="Circle")) for i in range(layers)],
    )
    path = folder / name
    path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
    return path


def start(qt_app) -> MainWindow:
    win = MainWindow()
    win.show()
    qt_app.processEvents()
    return win


def test_quit_and_start_again_everything_as_left(qt_app, tmp_path, monkeypatch) -> None:
    intro, outro = write_project(tmp_path, "intro.json", 1), write_project(tmp_path, "outro.json", 2)

    # session 1: a first start greets, then the user works and leaves things their way
    first = start(qt_app)
    assert first.welcome.isVisible() and first.page == "compose"
    first.load(intro)
    first.load(outro)
    first.show_page("animate")
    first.pages.pages["animate"].top.setSizes([700, 400])
    first.snap_action.setChecked(False)
    first.half_action.setChecked(True)
    first.follow_action.setChecked(False)
    assert not first.timeline.follow_playhead
    qt_app.processEvents()
    kept_right = first.pages.pages["animate"].top.sizes()[1]
    first_size = first.size()
    first.close()

    # session 2: the empty start still greets - with the recent files; opening one returns the page
    second = start(qt_app)
    # The offscreen screen is 800 px wide, so the restored window was cut to it - narrower than the Animate
    # page's three panes can be (Lumen, ADR 0063): their sizes only come back in a window as wide as it was.
    second.resize(first_size)
    qt_app.processEvents()
    try:
        assert second.welcome.isVisible() and second.page == "compose"
        assert [b.text() for b in second.welcome.recent_links] == ["outro.json", "intro.json"]
        assert not second.snap_action.isChecked() and second.half_action.isChecked()
        assert not second.follow_action.isChecked() and not second.timeline.follow_playhead
        second.welcome.recent_links[1].click()
        assert second.path == intro.resolve() and not second.welcome.isVisible()
        assert second.page == "animate"
        qt_app.processEvents()
        assert abs(second.pages.pages["animate"].top.sizes()[1] - kept_right) <= 20
    finally:
        second.close()

    # session 3: a fresh settings file is today's defaults
    monkeypatch.setenv("MANIM_STUDIO_SETTINGS", str(tmp_path / "fresh.ini"))
    third = start(qt_app)
    try:
        assert third.welcome.isVisible() and third.welcome.recent_links == []
        assert third.snap_action.isChecked() and not third.half_action.isChecked()
        assert third.render_ahead_action.isChecked()
        assert third.follow_action.isChecked() and third.timeline.follow_playhead
        third.load(intro)
        assert third.page == "compose"
    finally:
        third.close()
