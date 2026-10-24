"""Live mode on the Code page (P13.7): a Python object's code is applied after a pause in typing."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from manim_studio.core.schema import Canvas, Layer, Project, Spec
from manim_studio.ui.main_window import MainWindow

pytestmark = pytest.mark.ui

BASE = "PARAMS = {'r': (1.0, 0.5, 3.0)}\n\ndef build(p):\n    return Circle(radius=p['r'])\n"


@pytest.fixture
def code_text(tmp_path) -> str:
    return BASE + f"# {tmp_path.name}\n"  # unique: trust is by exact text and outlives a test


@pytest.fixture
def window(qt_app, tmp_path, code_text):
    project = Project(
        canvas=Canvas(width_px=320, height_px=180, fps=10, duration=2.0),
        layers=[Layer(id="wheel", name="Wheel", spec=Spec(type="Python", params={"code": code_text}))],
    )
    path = tmp_path / "scene.json"
    path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.ask_trust = lambda names: "skip"
    win.resize(1500, 850)
    win.show()
    win.load(path)
    win.show_page("code")
    win.selection.select_layer("wheel")
    qt_app.processEvents()
    yield win
    win.document.undo_stack.setClean()
    win.close()


def page(window):
    return window.pages.pages["code"]


def drain(qt_app) -> None:
    for _ in range(20):
        qt_app.processEvents()


def code_of(window) -> str:
    return window.project.layer("wheel").spec.params["code"]


def type_text(window, qt_app, text: str) -> None:
    page(window).editor.setPlainText(text)
    page(window)._live_apply()  # the timer's job, without waiting 800 ms
    drain(qt_app)


def test_live_is_off_until_chosen_and_typing_changes_nothing(window, qt_app, code_text) -> None:
    code = page(window)
    assert not code.live_action.isChecked()
    code.editor.setPlainText(code_text + "\n# a")
    assert not code._live_timer.isActive()
    assert code_of(window) == code_text


def test_choosing_live_starts_the_pause_timer_on_typing(window, code_text) -> None:
    code = page(window)
    code.live_action.setChecked(True)
    code._live_timer.stop()
    code.editor.setPlainText(code_text + "\n# a")
    assert code._live_timer.isActive()
    code.live_action.setChecked(False)
    assert not code._live_timer.isActive()


def test_an_object_that_was_never_run_waits_for_run(window, qt_app, code_text) -> None:
    code = page(window)
    changed = code_text.replace("1.0", "2.0")
    type_text(window, qt_app, changed)
    assert code_of(window) == code_text and "run this object once" in code.live_message


def test_after_a_run_the_pause_applies_the_text_as_one_undo_step(window, qt_app, code_text) -> None:
    code = page(window)
    code.run()  # trusts the code
    drain(qt_app)
    before = window.document.undo_stack.count()
    first, second = code_text.replace("1.0", "2.0"), code_text.replace("1.0", "2.5")
    type_text(window, qt_app, first)
    assert code_of(window) == first
    type_text(window, qt_app, second)
    assert code_of(window) == second
    assert window.document.undo_stack.count() == before + 1  # both applies merged
    window.document.undo_stack.undo()
    drain(qt_app)
    assert code_of(window) == code_text


def test_text_that_does_not_parse_is_not_applied_and_says_nothing(window, qt_app, code_text) -> None:
    code = page(window)
    code.run()
    drain(qt_app)
    type_text(window, qt_app, code_text + "\ndef (")
    assert code_of(window) == code_text and code.live_message == ""


def test_risky_code_is_paused_with_a_message(window, qt_app, code_text) -> None:
    code = page(window)
    code.run()
    drain(qt_app)
    type_text(window, qt_app, "import os\n" + code_text)
    assert code_of(window) == code_text and "uses os" in code.live_message


def test_copy_as_scene_puts_a_runnable_scene_on_the_clipboard(window, qt_app, code_text) -> None:
    from PySide6.QtWidgets import QApplication

    page(window).copy_as_scene()
    text = QApplication.clipboard().text()
    assert "class Wheel(Scene):" in text and "self.add(build(p))" in text
