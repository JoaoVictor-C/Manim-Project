"""The Deliver page (P6b.5, ADR 0042) through the real main window.

Exports are replaced by a fake ``ExportJob`` the test drives (progress, finished, failed), so the
queue, the settings and the buttons are checked without starting a renderer; the real process is
exercised by the acceptance test (test_acceptance_p6b5.py).
"""

from __future__ import annotations

import os
from typing import ClassVar

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QKeySequence

from manim_studio.core import edits
from manim_studio.core.python_export import to_python
from manim_studio.core.schema import Canvas, Clip, Cue, Layer, Project, Spec
from manim_studio.render.options import RenderOptions
from manim_studio.ui.main_window import MainWindow
from manim_studio.ui.pages import deliver
from manim_studio.ui.render_queue import Status
from ui.test_acceptance_v1 import menu_action

pytestmark = pytest.mark.ui

CANVAS = Canvas(width_px=320, height_px=180, fps=10, duration=4.0)


def make_project(**fields) -> Project:
    layer = Layer(
        id="sq",
        spec=Spec(type="Square", style={"fill": "#3b82f6", "fill_opacity": 1}),
        clips=[Clip(id="c", kind="FadeIn", start=0, duration=1.0)],
    )
    return Project(canvas=fields.pop("canvas", CANVAS), layers=[layer], **fields)


class FakeExport(QObject):
    """Stands in for ExportJob: records what it was asked, the test emits the outcome."""

    instances: ClassVar[list[FakeExport]] = []
    progress = Signal(int, int)
    finished = Signal(str, str)
    failed = Signal(str)

    def __init__(self, project, output, cache_dir, *, trust_code=False, options=None, parent=None):
        super().__init__(parent)
        self.project, self.output, self.trust_code, self.options = project, output, trust_code, options
        self.started = self.cancelled = False
        FakeExport.instances.append(self)

    def start(self) -> None:
        self.started = True

    def cancel(self) -> None:
        self.cancelled = True


@pytest.fixture(autouse=True)
def fake_export(monkeypatch):
    FakeExport.instances = []
    monkeypatch.setattr(deliver, "ExportJob", FakeExport)
    yield FakeExport


def open_window(qt_app, tmp_path, project: Project | None = None, name: str = "scene") -> MainWindow:
    path = tmp_path / f"{name}.json"
    path.write_text((project or make_project()).model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.resize(1300, 850)
    win.show()
    win.load(path)
    win.show_page("deliver")
    qt_app.processEvents()
    return win


@pytest.fixture
def window(qt_app, tmp_path):
    windows: list[MainWindow] = []

    def make(project: Project | None = None, name: str = "scene") -> MainWindow:
        win = open_window(qt_app, tmp_path, project, name)
        windows.append(win)
        return win

    yield make
    for win in windows:
        win.ask_stop_export = lambda: "stop"
        win.close()


def page(win: MainWindow) -> deliver.DeliverPage:
    return win.pages.pages["deliver"]


def set_canvas(win: MainWindow, **fields) -> None:
    project = win.project
    win.document.apply(
        edits.Edit(
            project.model_copy(update={"canvas": project.canvas.model_copy(update=fields)}),
            "timing",
            frozenset(),
        ),
        "Canvas",
    )


def pick(combo, data) -> None:
    combo.setCurrentIndex(combo.findData(data))


# -- the page and its place in the window ------------------------------------------------


def test_deliver_is_a_page_after_compose_with_the_viewer(window) -> None:
    win = window()
    names = list(win.pages.pages)
    assert names[0] == "compose" and "deliver" in names and win.page == "deliver"
    assert page(win).widget.isAncestorOf(win.viewer) and win.viewer.isVisible()
    index = [win.pages.bar.tabData(i) for i in range(win.pages.bar.count())].index("deliver")
    assert win.pages.bar.tabText(index) == "Deliver" and not win.pages.bar.tabIcon(index).isNull()
    action = menu_action(win.menuBar(), "View", "Pages", "Deliver")
    assert action.shortcut() == QKeySequence(f"Shift+{names.index('deliver') + 1}")  # Shift+5 in the end


def test_the_settings_start_from_the_project(window, tmp_path) -> None:
    win = window(make_project(canvas=Canvas(width_px=320, height_px=180, fps=24, duration=4.0)))
    p = page(win)
    assert p.size.currentData() == "project" and p.size.currentText() == "Project canvas (320x180)"
    assert (p.width.value(), p.height.value(), p.fps.value()) == (320, 180, 24)
    assert not p.width.isEnabled() and not p.height.isEnabled()
    assert p.range.currentData() == "whole" and (p.start.value(), p.end.value()) == (0.0, 4.0)
    assert p.quality.currentData() == 18 and p.subtitles.currentData() == "burn"
    assert p.path.text() == str(tmp_path / "out" / "scene.mp4")
    assert p.options() == RenderOptions()
    assert p.summary.text() == "96 frames, 4.00 s - 320x180 at 24 fps"


def test_size_presets_follow_the_project_aspect_ratio(window) -> None:
    win = window(make_project(canvas=Canvas(width_px=640, height_px=480, fps=10, duration=4.0)))  # 4:3
    p = page(win)
    labels = [p.size.itemText(i) for i in range(p.size.count())]
    assert labels == [
        "Project canvas (640x480)",
        "480p (640x480)",
        "720p (960x720)",
        "1080p (1440x1080)",
        "1440p (1920x1440)",
        "2160p (2880x2160)",
        "Custom",
    ]
    pick(p.size, "1080p")
    assert (p.width.value(), p.height.value()) == (1440, 1080) and not p.width.isEnabled()
    options = p.options()
    assert (options.width, options.height) == (1440, 1080)
    assert "1440x1080" in p.summary.text()


def test_custom_size_starts_from_the_last_choice_and_is_editable(window) -> None:
    p = page(window())
    pick(p.size, "720p")
    pick(p.size, "custom")
    assert p.width.isEnabled() and (p.width.value(), p.height.value()) == (1280, 720)
    p.width.setValue(400)
    p.height.setValue(226)
    options = p.options()
    assert (options.width, options.height) == (400, 226)
    assert "400x226" in p.summary.text()
    pick(p.size, "project")
    assert p.options().width is None and (p.width.value(), p.height.value()) == (320, 180)


def test_the_frame_rate_follows_the_canvas_until_it_is_set(window) -> None:
    win = window()
    p = page(win)
    set_canvas(win, fps=12)
    assert p.fps.value() == 12 and p.options().fps is None
    p.fps.setValue(30)
    assert p.options().fps == 30 and "at 30 fps" in p.summary.text()
    set_canvas(win, fps=15)
    assert p.fps.value() == 30  # the user's choice stays
    p.fps.setValue(15)
    assert p.options().fps is None  # the same as the project's: nothing to override


def test_the_range_by_times(window) -> None:
    p = page(window())
    pick(p.range, "times")
    assert p.start.isEnabled() and p.end.isEnabled() and not p.marker_from.isEnabled()
    p.start.setValue(1.0)
    p.end.setValue(2.5)
    options = p.options()
    assert (options.start, options.end) == (1.0, 2.5)
    assert p.summary.text() == "15 frames, 1.50 s - 320x180 at 10 fps"
    pick(p.range, "whole")
    assert not p.start.isEnabled() and (p.options().start, p.options().end) == (0.0, None)


def test_the_range_between_markers(window) -> None:
    project = make_project()
    for t, name in ((0.5, "intro"), (2.0, "formula"), (3.0, "")):
        project = edits.add_marker(project, t, name).project
    win = window(project)
    p = page(win)
    pick(p.range, "markers")
    assert p.marker_from.isEnabled() and p.marker_to.isEnabled() and not p.start.isEnabled()
    assert p.marker_from.itemText(0) == "intro (0.50 s)" and p.marker_from.count() == 3
    assert (p.options().start, p.options().end) == (0.5, 3.0)  # first to last by default
    pick(p.marker_from, 2.0)
    pick(p.marker_to, 0.5)
    options = p.options()  # chosen backwards: still from the earlier to the later
    assert (options.start, options.end) == (0.5, 2.0)
    assert p.summary.text().startswith("15 frames")


def test_the_marker_range_is_first_to_last_until_the_user_picks(window) -> None:
    win = window()
    p = page(win)
    pick(p.range, "markers")
    for t in (1.0, 2.0, 3.0):  # markers added one by one, as on the timeline
        win.document.apply(edits.add_marker(win.project, t), "Marker")
    assert (p.marker_from.currentData(), p.marker_to.currentData()) == (1.0, 3.0)
    p.marker_to.setCurrentIndex(1)
    p.marker_to.activated.emit(1)  # the user picked the second marker
    win.document.apply(edits.add_marker(win.project, 3.5), "Marker")
    assert (p.marker_from.currentData(), p.marker_to.currentData()) == (1.0, 2.0)
    win.document.apply(edits.remove_marker(win.project, win.project.markers[1].id), "Delete marker")
    assert p.marker_to.currentData() == 3.5  # its marker went: back to the last one


def test_an_edit_that_leaves_the_markers_alone_keeps_the_form(window) -> None:
    project = make_project()
    for t in (1.0, 2.0, 3.0):
        project = edits.add_marker(project, t).project
    win = window(project)
    p = page(win)
    p.marker_to.setCurrentIndex(1)
    win.document.apply(edits.update_layer(win.project, "sq", name="Renamed square"), "Rename")
    assert p.marker_to.currentData() == 2.0  # the combos were not rebuilt


def test_a_marker_range_needs_two_different_markers(window) -> None:
    win = window(edits.add_marker(make_project(), 1.0).project)
    p = page(win)
    pick(p.range, "markers")
    assert p.add_to_queue() is None and "two markers" in p.error.text()
    assert "two markers" in p.summary.text() and not p.queue.jobs
    both = edits.add_marker(win.project, 2.0).project
    win.document.apply(edits.Edit(both, "timing", frozenset()), "Marker")
    pick(p.marker_from, 1.0)
    pick(p.marker_to, 1.0)
    assert p.add_to_queue() is None and "different markers" in p.error.text()
    pick(p.marker_to, 2.0)
    assert p.add_to_queue() is not None and p.error.text() == ""


def test_a_range_that_cannot_render_is_refused_with_the_reason(window) -> None:
    p = page(window())
    pick(p.range, "times")
    p.start.setValue(3.0)
    p.end.setValue(2.0)
    assert p.add_to_queue() is None and "must end after" in p.error.text() and not p.queue.jobs
    p.end.setValue(3.0)
    assert p.add_to_queue() is None and "must end after" in p.summary.text()
    p.end.setValue(3.5)
    assert p.add_to_queue() is not None and p.error.text() == ""


def test_quality_and_subtitle_choices(window) -> None:
    win = window()
    p = page(win)
    assert [p.quality.itemText(i) for i in range(p.quality.count())] == [
        "Draft (crf 28)",
        "Standard (crf 23)",
        "High (crf 18)",
        "Archive (crf 12)",
    ]
    pick(p.quality, 28)
    assert p.options().crf == 28
    assert not p.subtitles.isEnabled() and p.options().subtitles is None  # no subtitles: nothing to choose
    win.document.apply(edits.add_cue(win.project, 0.5, 1.5, "Hello"), "Add subtitle")
    assert p.subtitles.isEnabled() and p.options().subtitles == "burn"
    pick(p.subtitles, "srt")
    assert p.options().subtitles == "srt"
    pick(p.subtitles, "none")
    assert p.options().subtitles == "none"


def test_opening_a_project_resets_the_settings(window, tmp_path) -> None:
    win = window()
    p = page(win)
    pick(p.size, "1080p")
    p.fps.setValue(60)
    pick(p.quality, 28)
    other = tmp_path / "other.json"
    other.write_text(
        make_project(canvas=Canvas(width_px=160, height_px=90, fps=8, duration=2.0)).model_dump_json(
            by_alias=True
        ),
        encoding="utf-8",
    )
    win.load(other)
    assert p.size.currentData() == "project" and (p.fps.value(), p.end.value()) == (8, 2.0)
    assert p.quality.currentData() == 18 and p.path.text() == str(tmp_path / "out" / "other.mp4")
    assert p.options() == RenderOptions()


def test_the_path_follows_the_project_until_it_is_typed(window) -> None:
    win = window()
    p = page(win)
    p.path.setText("D:/videos/mine.mp4")
    win.show_page("compose")
    win.show_page("deliver")
    assert p.path.text() == "D:/videos/mine.mp4"


def test_browse_sets_the_path(window, monkeypatch) -> None:
    p = page(window())
    monkeypatch.setattr(deliver.QFileDialog, "getSaveFileName", lambda *a, **k: ("E:/x/clip.mp4", ""))
    p._browse()
    assert p.path.text() == "E:/x/clip.mp4"
    monkeypatch.setattr(deliver.QFileDialog, "getSaveFileName", lambda *a, **k: ("", ""))
    p._browse()
    assert p.path.text() == "E:/x/clip.mp4"  # cancelled: unchanged


def test_without_a_project_nothing_can_be_added(qt_app) -> None:
    win = MainWindow()
    try:
        win.show()
        win.show_page("deliver")
        p = page(win)
        assert not p.add_button.isEnabled() and win.project is None
        assert p.add_to_queue() is None and "open a project" in p.error.text().lower()
        assert "Open a project" in p.python_kind.text() and not p.python_save.isEnabled()
    finally:
        win.close()


# -- the queue ----------------------------------------------------------------------------------


def add(win: MainWindow, name: str, **kw):
    p = page(win)
    p.path.setText(str(win.path.parent / "out" / f"{name}.mp4"))
    job = p.add_to_queue()
    assert job is not None
    return job


def row_status(p, job) -> str:
    return p._rows[job.id].text(2)


def test_adding_snapshots_the_project_and_the_settings(window) -> None:
    win = window()
    p = page(win)
    before = win.project
    pick(p.size, "720p")
    pick(p.quality, 28)
    job = add(win, "first")
    assert job.project is before and job.options == RenderOptions(width=1280, height=720, crf=28)
    assert job.status is Status.QUEUED and p.tree.topLevelItemCount() == 1
    item = p._rows[job.id]
    assert [item.text(i) for i in range(3)] == ["first.mp4", "1280x720 10 fps, 0.00-4.00 s", "Queued"]
    win.document.apply(edits.update_layer(win.project, "sq", name="renamed"), "Rename")  # edits after adding
    assert job.project is before and job.project != win.project
    assert not FakeExport.instances  # nothing runs until Start


def test_a_pending_output_path_is_not_reused(window) -> None:
    win = window()
    first, second = add(win, "same"), add(win, "same")
    assert first.output.name == "same.mp4" and second.output.name == "same (2).mp4"
    assert page(win)._rows[second.id].text(0) == "same (2).mp4"


def test_the_queue_runs_the_jobs_one_after_another(window) -> None:
    win = window()
    p = page(win)
    a = add(win, "a")
    pick(p.size, "480p")
    b = add(win, "b")
    assert p.start_button.isEnabled() and not p.cancel_button.isEnabled()
    p.start_button.click()
    assert len(FakeExport.instances) == 1
    run = FakeExport.instances[0]
    assert run.started and run.output == a.output and run.project is a.project
    assert run.options == a.options and run.trust_code is True
    assert a.status is Status.RENDERING and b.status is Status.QUEUED
    assert not p.start_button.isEnabled() and p.cancel_button.isEnabled()

    run.progress.emit(10, 40)
    assert row_status(p, a) == "Rendering 25 %"
    assert (p.bar.maximum(), p.bar.value()) == (40, 10) and "frame 10 of 40" in p.queue_status.text()
    assert "Deliver: Rendering a.mp4" in win.statusBar().currentMessage()

    run.finished.emit(str(a.output), "")
    assert a.status is Status.DONE and row_status(p, a) == "Done"
    assert len(FakeExport.instances) == 2  # b started by itself
    second = FakeExport.instances[1]
    assert second.output == b.output and second.options == b.options and b.status is Status.RENDERING
    second.finished.emit(str(b.output), "b.mp4 is in use; saved as b (2).mp4")
    assert row_status(p, b) == "Done - b.mp4 is in use; saved as b (2).mp4"
    assert not p.queue.busy and not p.queue.active and not p.cancel_button.isEnabled()
    assert win.statusBar().currentMessage() == ""
    assert p.clear_button.isEnabled()


def test_a_failed_job_shows_its_reason_and_the_queue_goes_on(window) -> None:
    win = window()
    p = page(win)
    a, b = add(win, "a"), add(win, "b")
    p.start_queue()
    FakeExport.instances[0].failed.emit("cannot write x\nmore detail")
    assert a.status is Status.FAILED and row_status(p, a) == "Failed: cannot write x"
    assert "more detail" in p._rows[a.id].toolTip(2)
    assert b.status is Status.RENDERING and len(FakeExport.instances) == 2


def test_cancel_stops_the_running_job_and_the_next_one_starts(window) -> None:
    win = window()
    p = page(win)
    a, b = add(win, "a"), add(win, "b")
    p.start_queue()
    running = FakeExport.instances[0]
    p.cancel_button.click()  # nothing selected: the running job
    assert running.cancelled and a.status is Status.CANCELLED and row_status(p, a) == "Cancelled"
    assert b.status is Status.RENDERING and len(FakeExport.instances) == 2
    text = p.queue_status.text()
    running.progress.emit(30, 40)  # signals from the killed process change nothing
    running.failed.emit("late")
    running.finished.emit("x.mp4", "")
    assert a.status is Status.CANCELLED and a.frame == 0 and p.queue_status.text() == text


def test_cancel_and_start_with_nothing_queued_do_nothing(window) -> None:
    p = page(window())
    assert not p.cancel_button.isEnabled() and not p.start_button.isEnabled()
    p.cancel_selected()
    p.start_queue()
    p.remove_selected()
    assert p.queue.jobs == [] and not FakeExport.instances


def test_a_queued_job_can_be_cancelled_selected(window) -> None:
    win = window()
    p = page(win)
    a, b, c = add(win, "a"), add(win, "b"), add(win, "c")
    p.start_queue()
    p.select(b)
    assert p.cancel_button.isEnabled()
    p.cancel_button.click()
    assert (
        b.status is Status.CANCELLED
        and a.status is Status.RENDERING
        and not FakeExport.instances[0].cancelled
    )
    FakeExport.instances[0].finished.emit(str(a.output), "")
    assert FakeExport.instances[1].output == c.output  # b was skipped


def test_remove_and_clear_finished(window) -> None:
    win = window()
    p = page(win)
    a, _b, c = add(win, "a"), add(win, "b"), add(win, "c")
    p.select(c)
    p.remove_button.click()
    assert c not in p.queue.jobs and p.tree.topLevelItemCount() == 2
    p.start_queue()
    p.select(a)
    assert not p.remove_button.isEnabled()  # rendering
    p.remove_selected()
    assert a in p.queue.jobs
    FakeExport.instances[0].finished.emit(str(a.output), "")
    FakeExport.instances[1].failed.emit("x")
    assert p.clear_button.isEnabled()
    p.clear_button.click()
    assert p.queue.jobs == [] and p.tree.topLevelItemCount() == 0 and not p.clear_button.isEnabled()


def test_a_job_added_while_the_queue_runs_follows_the_others(window) -> None:
    win = window()
    p = page(win)
    a = add(win, "a")
    p.start_queue()
    b = add(win, "b")
    assert b.status is Status.QUEUED and len(FakeExport.instances) == 1
    FakeExport.instances[0].finished.emit(str(a.output), "")
    assert b.status is Status.RENDERING and len(FakeExport.instances) == 2


def test_open_folder_of_a_finished_job(window, monkeypatch) -> None:
    win = window()
    p = page(win)
    opened = []
    monkeypatch.setattr(deliver, "open_folder", lambda path: opened.append(path))
    a, b = add(win, "a"), add(win, "b")
    p.select(a)
    assert not p.open_button.isEnabled()
    p.start_queue()
    FakeExport.instances[0].finished.emit(str(a.output), "")
    p.select(a)
    assert p.open_button.isEnabled()
    p.open_button.click()
    assert opened == [a.output]
    p.select(b)
    assert not p.open_button.isEnabled()
    p.open_folder()
    assert opened == [a.output]


def test_trust_for_code_layers_is_decided_when_the_job_is_added(window) -> None:
    win = window()
    p = page(win)
    win.trust.untrusted = lambda project: ["sq"]
    untrusted = add(win, "a")
    win.trust.untrusted = lambda project: []
    trusted = add(win, "b")
    assert (untrusted.trust, trusted.trust) == (False, True)
    p.start_queue()
    assert FakeExport.instances[0].trust_code is False  # trusting later does not change the first job


def test_closing_asks_while_the_queue_renders_and_stops_it(window) -> None:
    win = window()
    p = page(win)
    a, b = add(win, "a"), add(win, "b")
    p.start_queue()
    assert win.deliver_busy()
    asked = []
    win.ask_stop_export = lambda: asked.append(1) or "cancel"
    win.close()
    assert asked and win.isVisible() and a.status is Status.RENDERING  # quitting was cancelled
    win.ask_stop_export = lambda: asked.append(1) or "stop"
    win.close()
    assert not win.isVisible() and FakeExport.instances[0].cancelled
    assert (a.status, b.status) == (Status.CANCELLED, Status.CANCELLED) and not p.queue.active


def test_closing_without_a_render_does_not_ask(window) -> None:
    win = window()
    win.ask_stop_export = lambda: pytest.fail("nothing is rendering")
    add(win, "a")  # queued only
    win.close()
    assert not win.isVisible()


# -- the Python scene --------------------------------------------------------------------------------


def test_the_python_panel_previews_readable_code(window) -> None:
    win = window()
    p = page(win)
    assert p.python_kind.text().startswith("Readable Manim code")
    code = p.python_code.toPlainText()
    assert code == to_python(win.project, "Scene", str(deliver.adapter.cache_dir() / "code")).code
    assert "class Scene(" in code and p.python_code.isReadOnly() and p.python_save.isEnabled()
    assert "plain Manim" in p.python_kind.text()


def test_the_python_panel_says_why_a_scene_is_exact(window) -> None:
    cue = Cue(id="s", start=0.0, end=1.0, text="Hi")
    win = window(make_project(subtitles=[cue]))
    p = page(win)
    export = to_python(win.project, "Scene", str(deliver.adapter.cache_dir() / "code"))
    assert not export.readable
    assert p.python_kind.text().startswith("Exact scene")
    assert (
        p.python_reasons.text().startswith("Exact because: ")
        and export.problems[0] in p.python_reasons.text()
    )
    assert p.python_code.toPlainText() == export.code


def test_the_python_preview_follows_edits_after_a_moment(window, qt_app) -> None:
    win = window()
    p = page(win)
    before = p.python_code.toPlainText()
    p._python_timer.setInterval(0)
    win.document.apply(edits.update_layer(win.project, "sq", name="Renamed square"), "Rename")
    assert p._python_stale and p.python_code.toPlainText() == before  # not recomputed on every edit
    for _ in range(20):
        qt_app.processEvents()
    assert not p._python_stale and p.python_code.toPlainText() != before


def test_a_stale_preview_is_refreshed_when_the_page_is_shown(window) -> None:
    win = window()
    p = page(win)
    win.show_page("compose")
    win.document.apply(edits.update_layer(win.project, "sq", name="Renamed square"), "Rename")
    assert p._python_stale and not p._python_timer.isActive()  # hidden: no work
    before = p.python_code.toPlainText()
    win.show_page("deliver")
    assert not p._python_stale and p.python_code.toPlainText() != before


def test_save_as_writes_the_scene_through_the_window(window, tmp_path) -> None:
    win = window()
    p = page(win)
    target = tmp_path / "scene_out.py"
    asked = []
    win.ask_python_path = lambda start: asked.append(start) or str(target)
    p.python_save.click()
    assert asked == [tmp_path / "scene.py"]
    assert (
        target.read_text(encoding="utf-8")
        == to_python(win.project, "SceneOut", str(deliver.adapter.cache_dir() / "code")).code
    )
    win.ask_python_path = lambda start: ""
    target.unlink()
    p.python_save.click()  # cancelled: nothing written
    assert not target.exists()
