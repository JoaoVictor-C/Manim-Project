"""Importing a Manim scene in the editor (P10.3, ADR 0053): File > Import Manim Scene..., the
Code page's Convert to layers, the recording process and the report."""

from __future__ import annotations

import os
import sys
import textwrap
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QObject, Signal

from manim_studio.core.model.schema import Canvas, Layer, Lifetime, Project, Spec
from manim_studio.processes import scene_recorder
from manim_studio.ui.main_window import MainWindow
from manim_studio.ui.services.scene_import import SceneImporter

pytestmark = pytest.mark.ui

SCENE = textwrap.dedent(
    """
    from manim import *

    class Intro(Scene):
        def construct(self):
            self.play(Create(Circle()))
            self.play(FadeIn(Square().shift(RIGHT * 2)))

    class Other(Scene):
        def construct(self):
            self.add(Dot())
            self.wait()
    """
)


class InProcess(QObject):
    """The importer, recording in this process (the editor's own starts another one)."""

    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.busy = False
        self.jobs: list[tuple] = []

    def warm(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def start(self, path, scene, prelude=False) -> None:
        self.jobs.append((path, scene, prelude))
        try:
            recording = scene_recorder.record_file(path, scene, prelude=prelude)
        except scene_recorder.RecordError as exc:
            self.failed.emit(f"line {exc.line}: {exc}")
            return
        self.finished.emit(recording)


@pytest.fixture
def window(qt_app, tmp_path):
    project = Project(
        canvas=Canvas(width_px=320, height_px=180, fps=10, duration=1.0),
        layers=[Layer(id="dot-1", spec=Spec(type="Dot"))],
    )
    path = tmp_path / "project.json"
    path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    importer = InProcess()
    importer.finished.connect(win._on_scene_recorded)
    importer.failed.connect(win._on_scene_failed)
    win.scene_importer = importer
    win.reports = []
    win.show_import_report = lambda title, lines: win.reports.append((title, lines))
    win.show()
    win.load(path)
    qt_app.processEvents()
    yield win
    win.close()


def menu_action(window, text: str):
    menu = next(a.menu() for a in window.menuBar().actions() if a.text() == "&File")
    return next(a for a in menu.actions() if a.text().replace("&", "") == text)


def unique_scene(tmp_path):
    """The scene in a file of its own text: no other test trusted it (the trust store is shared)."""
    path = tmp_path / "intro.py"
    path.write_text(f"{SCENE}# {tmp_path.name}\n", encoding="utf-8")
    return path


def test_the_menu_item_asks_runs_and_adds_the_scene_on_top_as_one_undo_step(window, tmp_path) -> None:
    path = unique_scene(tmp_path)
    asked = []
    window.ask_scene_path = lambda: str(path)
    window.ask_scene_name = lambda file, scenes: asked.append(scenes) or "Intro"
    window.ask_run_scene = lambda name: asked.append(name) or "run"
    action = menu_action(window, "Import Manim Scene...")
    assert action.toolTip()
    action.trigger()
    assert asked == [["Intro", "Other"], "intro.py"]
    project = window.project
    assert [x.id for x in project.layers] == ["dot-1", "circle-1", "square-1"]
    assert set(window.selection.layer_ids) == {"circle-1", "square-1"}
    assert project.canvas.duration == pytest.approx(2.0)  # grown to hold the scene
    assert window.document.undo_stack.undoText() == "Import Manim scene"
    assert window.reports and window.reports[0][1][0].startswith("Imported Intro")
    window.document.undo_stack.undo()
    assert [x.id for x in window.project.layers] == ["dot-1"]
    asked.clear()
    action.trigger()  # the file is trusted now: no second question
    assert asked == [["Intro", "Other"]]


def test_declining_to_run_the_file_imports_nothing(window, tmp_path) -> None:
    path = unique_scene(tmp_path)
    window.ask_scene_path = lambda: str(path)
    window.ask_scene_name = lambda file, scenes: "Other"
    window.ask_run_scene = lambda name: "skip"
    window.import_manim_scene()
    assert window.scene_importer.jobs == [] and len(window.project.layers) == 1
    assert "was not run" in window.statusBar().currentMessage()


def test_a_scene_that_fails_says_where(window, tmp_path) -> None:
    path = tmp_path / "bad.py"
    path.write_text("from manim import *\nclass Bad(Scene):\n    def construct(self):\n        1 / 0\n")
    window.ask_scene_path = lambda: str(path)
    window.ask_run_scene = lambda name: "run"
    window.import_manim_scene()
    assert "line 4" in window.statusBar().currentMessage() and len(window.project.layers) == 1


def code_window(window, code: str) -> None:
    layer = Layer(id="code-1", spec=Spec(type="Code", params={"code": code}), lifetime=Lifetime(in_=0.5))
    window.document.apply(
        __import__("manim_studio.core.editing.edits", fromlist=["x"]).insert_scene(
            window.project, Project(layers=[layer]), 0.0
        )[0],
        "Add code",
    )


def test_convert_to_layers_replaces_a_code_layer_from_its_start(window, qt_app) -> None:
    code = "class Rings(Scene):\n    def construct(self):\n        self.play(Create(Circle()))\n"
    code_window(window, code)  # the code layer uses Manim's names without importing them (ADR 0019)
    window.ask_run_scene = lambda name: "run"
    window.show_page("code")
    page = window.pages.pages["code"]
    window.selection.select_layer("code-1")
    qt_app.processEvents()
    assert page.convert_button.isEnabled() and page.convert_button.toolTip()
    page.convert_button.click()
    layers = window.project.layers
    assert [x.spec.type for x in layers] == ["Dot", "Circle"]
    assert layers[1].clips[0].start == pytest.approx(0.5)
    assert window.scene_importer.jobs[0][2] is True  # with the code layer's prelude
    assert window.document.undo_stack.undoText() == "Convert to layers"


def test_convert_to_layers_refuses_a_scene_that_must_stay_code(window, qt_app) -> None:
    code = (
        "class Orbit(Scene):\n    def construct(self):\n"
        "        d = Dot().add_updater(lambda m, dt: m.shift(RIGHT * dt))\n        self.add(d)\n"
        "        self.wait(1)\n"
    )
    code_window(window, code)
    window.trust.trust([code])
    assert window.convert_code_layer("code-1")
    assert [x.spec.type for x in window.project.layers] == ["Dot", "Code"]
    assert "stays a code layer" in window.statusBar().currentMessage()
    assert window.reports and "updaters" in "\n".join(window.reports[0][1])


# -- the recording process -----------------------------------------------------------------------------

FAKE = textwrap.dedent(
    """
    import json, sys, pathlib
    print("starting")
    print(json.dumps({"ready": True}), flush=True)
    job = json.loads(sys.stdin.readline())
    if job["scene"] == "Slow":
        import time; time.sleep(30)
    if job["scene"] == "Bad":
        print(json.dumps({"error": "NameError: x", "line": 7}), flush=True)
        sys.exit(1)
    pathlib.Path(job["output"]).write_text(json.dumps({"scene": job["scene"], "prelude": job["prelude"]}))
    print(json.dumps({"done": True}), flush=True)
    """
)


def wait_for(qt_app, condition, seconds: float = 15.0) -> None:
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        qt_app.processEvents()
        time.sleep(0.01)


def test_the_importer_process_takes_one_job_and_reports(qt_app, tmp_path) -> None:
    script = tmp_path / "fake.py"
    script.write_text(FAKE, encoding="utf-8")
    results: list = []
    for scene, timeout in (("Intro", 30.0), ("Bad", 30.0), ("Slow", 1.0)):
        importer = SceneImporter(tmp_path, program=sys.executable, args=[str(script)], timeout_s=timeout)
        importer.finished.connect(lambda r: results.append(("ok", r)))
        importer.failed.connect(lambda m: results.append(("failed", m)))
        importer.start(tmp_path / "x.py", scene, prelude=scene == "Intro")
        assert importer.busy
        count = len(results)
        wait_for(qt_app, lambda count=count: len(results) > count)
        assert not importer.busy
        importer.stop()
    assert results[0] == ("ok", {"scene": "Intro", "prelude": True})
    assert results[1] == ("failed", "line 7: NameError: x")
    assert results[2][0] == "failed" and "longer than 1 s" in results[2][1]


@pytest.mark.slow
def test_the_real_recorder_process_records_a_scene(qt_app, tmp_path) -> None:
    path = tmp_path / "intro.py"
    path.write_text(SCENE, encoding="utf-8")
    results: list = []
    importer = SceneImporter(tmp_path / "cache")
    importer.finished.connect(results.append)
    importer.failed.connect(results.append)
    importer.warm()
    importer.start(path, "Intro")
    wait_for(qt_app, lambda: results, seconds=60.0)
    importer.stop()
    assert results and results[0]["scene"] == "Intro" and results[0]["problems"] == []
