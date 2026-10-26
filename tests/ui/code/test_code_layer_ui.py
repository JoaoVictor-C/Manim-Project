"""Code layers in the editor (P2d.4, ADR 0019): trust prompt, code field, status, export flag."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys
import time

import pytest

pytest.importorskip("PySide6")

from manim_studio.core.code.code_cache import code_hash
from manim_studio.core.code.code_frame import CodeFrame
from manim_studio.core.model.schema import Canvas, Layer, Project, Spec
from manim_studio.ui import main_window as main_window_module
from manim_studio.ui.main_window import MainWindow
from manim_studio.ui.services.code_render import CodeRenderService
from manim_studio.ui.style.fields import CodeField
from ui.services.test_code_render import STAND_IN

pytestmark = pytest.mark.ui

CODE = "class Orbit(Scene):\n    def construct(self):\n        self.add(Dot())\n"


def wait_until(qt_app, condition, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("timed out waiting")
        qt_app.processEvents()
        time.sleep(0.01)


def write_project(tmp_path, code: str = CODE):
    project = Project(
        canvas=Canvas(width_px=64, height_px=36, fps=10, duration=1.0),
        layers=[Layer(id="orbit", name="Orbit", spec=Spec(type="Code", params={"code": code}))],
    )
    path = tmp_path / "code.json"
    path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def own_trust_store(monkeypatch, tmp_path):
    """Each test starts with nothing trusted."""
    monkeypatch.setenv("MANIM_STUDIO_TRUST_FILE", str(tmp_path / "trusted.json"))


@pytest.fixture
def stand_in_renderer(monkeypatch, tmp_path):
    """The window's code renderer, with a runner that writes frames without Manim."""

    def make(cache_dir, trust, parent=None):
        return CodeRenderService(
            tmp_path / "cache",
            trust,
            program=sys.executable,
            args=["-c", STAND_IN, str(tmp_path / "cache")],
            parent=parent,
        )

    monkeypatch.setattr(main_window_module, "make_code_renderer", make)


def open_window(qt_app, path, answer: str, asked: list) -> MainWindow:
    win = MainWindow()
    win.ask_trust = lambda names: asked.append(names) or answer
    win.resize(1000, 700)
    win.show()
    win.load(path)
    qt_app.processEvents()
    return win


def test_opening_untrusted_code_asks_and_skipping_runs_nothing(qt_app, tmp_path, stand_in_renderer) -> None:
    asked = []
    win = open_window(qt_app, write_project(tmp_path), "skip", asked)
    try:
        assert asked == [["Orbit"]]
        assert win.code.status("orbit").state == "untrusted"
        assert win.code.spare_count == 0
        assert "were not run" in win.statusBar().currentMessage()
        assert not win.trust.is_trusted(CODE)
        [(layer_id, mob)] = win.evaluator.frame_layers(0.0)
        assert layer_id == "orbit" and not isinstance(mob, CodeFrame)  # the placeholder
    finally:
        win.close()


def test_agreeing_trusts_the_code_and_renders_it(qt_app, tmp_path, stand_in_renderer) -> None:
    asked = []
    win = open_window(qt_app, write_project(tmp_path), "run", asked)
    try:
        assert win.trust.is_trusted(CODE)
        wait_until(qt_app, lambda: win.code.status("orbit").state == "ready")
        assert isinstance(win.evaluator.frame_layers(0.0)[0][1], CodeFrame)
        win.close()
        again = open_window(qt_app, write_project(tmp_path), "skip", asked)
        assert len(asked) == 1  # trusted now: not asked again
        again.close()
    finally:
        win.close()


def test_the_code_field_applies_trusts_and_shows_the_status(qt_app, tmp_path, stand_in_renderer) -> None:
    win = open_window(qt_app, write_project(tmp_path), "skip", [])
    try:
        win.selection.select_layer("orbit")
        field = win.properties.fields["params.code"]
        assert isinstance(field, CodeField)
        assert "not trusted" in win.properties.code_label.text()
        mine = CODE.replace("Dot()", "Square()")
        field.commit(mine)
        assert win.trust.is_trusted(mine)  # applying code in the editor is trusting it
        assert win.project.layer("orbit").spec.params["code"] == mine
        wait_until(qt_app, lambda: win.properties.code_label.text() == "Ready - 3 frames")
        assert not win.properties.retry_button.isVisible()
        field.commit(CODE.replace("Dot()", "FAIL()"))
        wait_until(qt_app, lambda: "Error - line 2" in win.properties.code_label.text())
        assert win.properties.retry_button.isVisible()
    finally:
        win.close()


def test_the_library_starter_code_is_trusted(qt_app) -> None:
    win = MainWindow()
    try:
        win.new_project()
        win.layers.add_object("Code")
        code = win.project.layers[0].spec.params["code"]
        assert win.trust.is_trusted(code)
        assert win.timeline.context_menu  # code rows exist; clips are refused by the schema
    finally:
        win.close()


def test_export_runs_code_only_when_every_code_layer_is_trusted(qt_app, tmp_path, monkeypatch) -> None:
    from manim_studio.ui.deliver import export_job

    started = []
    monkeypatch.setattr(export_job.ExportJob, "start", lambda self: started.append(self.trust_code))
    win = open_window(qt_app, write_project(tmp_path), "skip", [])
    try:
        win.show_export_dialog()
        win.export_dialog.path.setText(str(tmp_path / "a.mp4"))
        win.export_dialog.start()
        win.trust.trust([CODE])
        win.export_dialog.start()
        assert started == [False, True]
        assert code_hash(CODE) in win.trust.path.read_text(encoding="utf-8")
    finally:
        win.export_dialog.close()
        win.close()


def test_a_code_layer_has_no_style_section(qt_app, tmp_path) -> None:
    win = open_window(qt_app, write_project(tmp_path), "skip", [])
    try:
        win.selection.select_layer("orbit")
        assert not any(path.startswith("style.") for path in win.properties.fields)
        assert "base.position" in win.properties.fields
    finally:
        win.close()
