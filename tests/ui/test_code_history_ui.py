"""History and revert on the Code page (P13.4): versions of a layer's code, the last working one, a diff."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from manim_studio.core.schema import Canvas, Layer, Project, Spec
from manim_studio.ui.code_history_dialog import NO_WORKING, describe
from manim_studio.ui.code_render import CodeStatus
from manim_studio.ui.main_window import MainWindow

pytestmark = pytest.mark.ui

BASE = "PARAMS = {'r': (1.0, 0.5, 3.0)}\n\ndef build(p):\n    return Circle(radius=p['r'])\n"
BROKEN = "PARAMS = {'r': (1.0, 0.5, 3.0)}\n\ndef build(p):\n    raise ValueError('nope')\n"
SCENE = "class Orbit(Scene):\n    def construct(self):\n        self.add(Dot())\n"


@pytest.fixture
def tag(tmp_path) -> str:
    return f"# {tmp_path.name}\n"  # unique: trust is by exact text and outlives a test


def write(tmp_path, name: str, layers: list[Layer]):
    project = Project(canvas=Canvas(width_px=320, height_px=180, fps=10, duration=2.0), layers=layers)
    path = tmp_path / name
    path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
    return path


@pytest.fixture
def window(qt_app, tmp_path, tag):
    path = write(
        tmp_path,
        "scene.json",
        [
            Layer(id="wheel", name="Wheel", spec=Spec(type="Python", params={"code": BASE + tag})),
            Layer(id="orbit", name="Orbit", spec=Spec(type="Code", params={"code": SCENE + tag})),
        ],
    )
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


def code_of(window, layer_id: str = "wheel") -> str:
    return window.project.layer(layer_id).spec.params["code"]


def run_text(window, qt_app, text: str) -> None:
    page(window).editor.setPlainText(text)
    page(window).run()
    drain(qt_app)


def set_status(window, layer_id: str, status: CodeStatus | None) -> None:
    window.code.status = lambda i: status if i == layer_id else None
    window.code.statusChanged.emit(layer_id)


def test_opening_a_layer_begins_its_chain_and_each_run_adds_a_version(window, qt_app, tag) -> None:
    code = page(window)
    assert [v.text for v in code.history.versions("wheel")] == [BASE + tag]
    changed = (BASE + tag).replace("1.0", "2.0")
    run_text(window, qt_app, changed)
    versions = code.history.versions("wheel")
    assert [v.text for v in versions] == [changed, BASE + tag]
    assert versions[0].source == "run" and versions[0].working is True  # the object was built


def test_revert_to_last_working_puts_it_in_the_editor_without_applying(window, qt_app, tag) -> None:
    code = page(window)
    good = (BASE + tag).replace("1.0", "2.0")
    run_text(window, qt_app, good)
    run_text(window, qt_app, BROKEN + tag)
    assert code.status("wheel").state == "error"
    assert code.history.versions("wheel")[0].working is False
    assert code.revert_working_action.text() == "Revert to last working version"
    code.revert_working_action.trigger()
    assert code.editor.text() == good
    assert code_of(window) == BROKEN + tag  # nothing applied: Run decides
    code.editor.undo()  # one step of the editor's own undo
    assert code.editor.text() == BROKEN + tag


def test_revert_says_so_when_nothing_worked_yet(window, qt_app, tag) -> None:
    code = page(window)
    window.selection.select_layer("orbit")
    code.editor.setPlainText(SCENE + tag + "# more\n")
    assert not code.history_keeper.revert_to_working()
    assert window.statusBar().currentMessage() == NO_WORKING
    assert code.editor.text() == SCENE + tag + "# more\n"


def test_a_scene_render_that_settles_ready_marks_its_code_working(window, qt_app, tag) -> None:
    code = page(window)
    window.selection.select_layer("orbit")
    run_text(window, qt_app, SCENE + tag + "# v2\n")
    assert code.history.versions("orbit")[0].working is None
    set_status(window, "orbit", CodeStatus("ready", frames=10))
    assert code.history.versions("orbit")[0].working is True
    run_text(window, qt_app, SCENE + tag + "# v3\n")
    set_status(window, "orbit", CodeStatus("error", error="NameError: x", line=3))
    assert code.history.versions("orbit")[0].working is False
    assert code.history_keeper.revert_to_working()
    assert code.editor.text() == SCENE + tag + "# v2\n"


def test_the_history_window_lists_versions_and_diffs_against_the_editor(window, qt_app, tag) -> None:
    code = page(window)
    changed = (BASE + tag).replace("1.0", "2.0")
    run_text(window, qt_app, changed)
    code.editor.setPlainText(changed + "# typing\n")
    code.history_action.trigger()
    dialog = code.history_keeper.dialog
    assert dialog is not None and dialog.list.count() == 2
    assert "Run" in dialog.list.item(0).text() and "worked" in dialog.list.item(0).text()
    assert "+1 −0" in dialog.list.item(0).text()
    assert "Opened" in dialog.list.item(1).text()
    dialog.list.setCurrentRow(1)
    diff = dialog.diff.toPlainText()
    assert "-PARAMS = {'r': (1.0, 0.5, 3.0)}" in diff and "+PARAMS = {'r': (2.0, 0.5, 3.0)}" in diff
    dialog.put_in_editor()
    assert code.editor.text() == BASE + tag
    assert code_of(window) == changed  # not applied
    assert "same as the editor" in dialog.list.item(1).text()
    assert dialog.diff.toPlainText() == ""
    dialog.close_button.click()
    drain(qt_app)
    assert code.history_keeper.dialog is None


def test_another_project_drops_chains_and_a_reused_id_with_other_text_starts_again(
    window, qt_app, tmp_path, tag
) -> None:
    code = page(window)
    run_text(window, qt_app, (BASE + tag).replace("1.0", "2.0"))
    other = BASE.replace("Circle", "Square") + tag
    window.load(
        write(
            tmp_path,
            "other.json",
            [Layer(id="wheel", name="W", spec=Spec(type="Python", params={"code": other}))],
        )
    )
    window.selection.select_layer("wheel")
    drain(qt_app)
    assert code.history.layer_ids() == ["wheel"]  # orbit is not in this project
    assert [v.text for v in code.history.versions("wheel")] == [other]


def test_live_applies_are_versions_too(window, qt_app, tag) -> None:
    code = page(window)
    code.run()  # trusts the code, so Live may apply
    drain(qt_app)
    changed = (BASE + tag).replace("1.0", "2.5")
    code.editor.setPlainText(changed)
    code._live_apply()
    drain(qt_app)
    newest = code.history.versions("wheel")[0]
    assert newest.text == changed and newest.source == "live" and newest.working is True


def test_describe_counts_the_lines_that_differ_from_the_editor() -> None:
    from manim_studio.core.code_history import Version

    version = Version("a\nb\n", 0.0, True, "run")
    assert "+1 −1" in describe(version, "a\nc\n") and "worked" in describe(version, "a\nc\n")
    assert "same as the editor" in describe(version, "a\nb")
