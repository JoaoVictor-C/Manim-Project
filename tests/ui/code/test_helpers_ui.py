"""Helpers on the Code page (ADR 0058, P13.5): the explorer section, editing in a tab, Run (apply, trust,
test-import), New, Rename, Delete, Duplicate, Export, import as a helper, helper presets, Extract to
helper, and the hint for a helper the code imports that may not run yet."""

from __future__ import annotations

import os
import re

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor

from manim_studio.core.exchange import code_import as ci
from manim_studio.core.exchange.code_import import ImportChoice, ImportItem
from manim_studio.core.model.schema import Canvas, Helper, Layer, Project, Spec
from manim_studio.ui.code.code_explorer import KIND_ROLE
from manim_studio.ui.main_window import MainWindow

pytestmark = pytest.mark.ui

OBJECT = "PARAMS = {}\n\ndef build(p):\n    return Circle()\n"


@pytest.fixture
def name(tmp_path) -> str:
    """A helper name of this test only: trust is by exact text and outlives a test."""
    return "h_" + re.sub(r"\W", "_", tmp_path.name).lower()


@pytest.fixture
def helper_code(name) -> str:
    return f"def double(x):\n    return 2 * x\n\n# {name}\n"


@pytest.fixture
def window(qt_app, tmp_path, name, helper_code):
    scene = (
        f"import {name}\n\n\nclass Orbit(Scene):\n    def construct(self):\n"
        f"        self.add(Dot())  # {name}\n"
    )
    project = Project(
        canvas=Canvas(width_px=320, height_px=180, fps=10, duration=2.0),
        layers=[
            Layer(id="orbit", name="Orbit", spec=Spec(type="Code", params={"code": scene})),
            Layer(
                id="wheel", name="Wheel", spec=Spec(type="Python", params={"code": OBJECT + f"# {name}\n"})
            ),
        ],
        helpers=[Helper(name=name, code=helper_code)],
    )
    path = tmp_path / "scene.json"
    path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.ask_trust = lambda names: "skip"
    win.resize(1500, 850)
    win.show()
    win.load(path)
    win.show_page("code")
    win.selection.select_layer("orbit")
    qt_app.processEvents()
    yield win
    page(win).helper_actions.checker.stop()
    win.document.undo_stack.setClean()
    win.close()


def page(window):
    return window.pages.pages["code"]


def drain(qt_app) -> None:
    for _ in range(20):
        qt_app.processEvents()


def helper_rows(code) -> list[str]:
    return [key for section, _source, key in code.explorer.rows() if section == "helpers"]


def open_helper(code, name: str) -> None:
    code.explorer.select("helper", f"helper:{name}")


def wait_check(code) -> None:
    assert code.helper_actions.checker.wait(60000)


# -- the explorer and the editor ---------------------------------------------------------------------


def test_the_helpers_section_lists_them_with_a_mark_until_trusted(window, name) -> None:
    code = page(window)
    assert helper_rows(code) == [f"helper:{name}"]
    (text,) = code.explorer.texts("helpers")
    assert text.startswith(name) and text.endswith("?")  # not run yet
    item = code.explorer._find("helper", f"helper:{name}")
    assert item.data(0, KIND_ROLE) == "helper" and not item.icon(0).isNull()
    assert not item.flags() & Qt.ItemFlag.ItemIsDragEnabled  # nothing to drop on the timeline


def test_the_section_shows_a_hint_when_there_are_no_helpers(window, name) -> None:
    code = page(window)
    code.confirm = lambda title, text: True
    code.helper_actions.delete(name)  # nothing imports it but the scene: asked, and forced
    assert window.project.helpers == []
    tops = [code.explorer.topLevelItem(i) for i in range(code.explorer.topLevelItemCount())]
    section = next(top for top in tops if top.data(0, Qt.ItemDataRole.UserRole) == "helpers")
    assert section.child(0).text(0) == "Add a helper: reusable Python your code can import"


def test_choosing_a_helper_opens_it_in_a_tab_without_changing_the_selection(
    window, name, helper_code
) -> None:
    code = page(window)
    open_helper(code, name)
    assert code.layer_id == f"helper:{name}" and code.editor.text() == helper_code
    assert window.selection.layer_id == "orbit"
    labels = [code.tabs.tabText(i) for i in range(code.tabs.count())]
    assert labels[-1] == name and code.tabs.currentIndex() == code.tabs.count() - 1
    assert not code.tabs.tabIcon(code.tabs.count() - 1).isNull()
    assert code.kind_label.text() == "Helper" and "helper" in code.title_label.text()
    assert not code.convert_button.isEnabled()
    assert "imported by Orbit" in code.state_label.text() and "defines double" in code.state_label.text()


def test_drafts_dirty_marks_and_revert_work_for_a_helper(window, name, helper_code) -> None:
    code = page(window)
    open_helper(code, name)
    code.editor.setPlainText(helper_code + "Y = 2\n")
    assert code.is_dirty() and code.dirty_label.isVisibleTo(code.widget)
    assert code.tabs.tabText(code.tabs.currentIndex()).endswith("●")
    assert "●" in code.explorer.texts("helpers")[0]
    code.explorer.select("layer", "wheel")  # away and back: the draft is kept
    assert code.layer_id == "wheel"
    open_helper(code, name)
    assert code.editor.text() == helper_code + "Y = 2\n"
    code.revert()
    assert code.editor.text() == helper_code and not code.is_dirty()
    assert window.project.helper(name).code == helper_code  # nothing was applied


def test_switching_tabs_between_a_helper_and_a_layer(window, name) -> None:
    code = page(window)
    open_helper(code, name)
    code.tabs.setCurrentIndex(0)
    assert code.layer_id == "orbit"
    code.tabs.setCurrentIndex(code.tabs.count() - 1)
    assert code.layer_id == f"helper:{name}"
    code._close_tab(code.tabs.currentIndex())
    assert code.layer_id == "orbit" and f"helper:{name}" not in code.open_ids


def test_quick_open_finds_helpers(window, name) -> None:
    code = page(window)
    item = next(i for i in code.quick_items() if i.source == "helper")
    assert (item.key, item.label) == (f"helper:{name}", name)
    code.quick = lambda items: item
    code.quick_open()
    assert code.layer_id == f"helper:{name}"


# -- run ---------------------------------------------------------------------------------------------


def test_run_applies_trusts_and_test_imports_the_helper(window, qt_app, name, helper_code) -> None:
    code = page(window)
    open_helper(code, name)
    text = helper_code + "print('ready')\n"
    code.editor.setPlainText(text)
    code.run()
    assert window.project.helper(name).code == text
    assert window.document.undo_stack.undoText() == "Edit helper"
    assert window.trust.is_trusted(text)
    assert code.status(code.layer_id).state == "checking" and not code.run_button.isEnabled()
    wait_check(code)
    drain(qt_app)
    assert code.status(code.layer_id).state == "ready"
    assert "Imported without errors" in code.state_label.text()
    assert "ready" in code.trace_label.text() and code.trace_label.isVisibleTo(code.widget)
    assert code.explorer.texts("helpers")[0] == name  # no marks: trusted, no error
    assert code.trust_label.text() == "Imported"


def test_an_error_in_the_helper_shows_at_its_line(window, qt_app, name, helper_code) -> None:
    code = page(window)
    open_helper(code, name)
    code.editor.setPlainText(helper_code + "X = 1\nY = missing_name\n")
    code.run()
    wait_check(code)
    drain(qt_app)
    status = code.status(code.layer_id)
    assert (status.state, status.error_type, status.helper_line) == ("error", "NameError", 6)
    assert code.error_label.line == 6 and code.error_label.helper is None
    assert code.explorer.texts("helpers")[0].endswith("!")
    code.editor.go_to_line(1)
    code.go_to_error()
    assert code.editor.current_line() == 6


def test_an_error_raised_in_a_helper_opens_it_from_the_layer(window, name) -> None:
    from manim_studio.ui.services.code_render import CodeStatus

    code = page(window)
    status = CodeStatus(
        "error", error="ZeroDivisionError: division by zero", line=1, where=f"helper:{name}", helper_line=2
    )
    window.code.status = lambda i: status if i == "orbit" else None
    window.code.statusChanged.emit("orbit")
    assert code.layer_id == "orbit"
    assert code.error_label.helper == name and f"helper {name}, line 2" in code.error_label.plain
    code.go_to_error()
    assert code.layer_id == f"helper:{name}" and code.editor.current_line() == 2


def test_a_helper_not_trusted_yet_offers_to_run_it(window, qt_app, name, helper_code) -> None:
    code = page(window)
    assert code.layer_id == "orbit"
    assert code.hint_label.isVisibleTo(code.widget) and name in code.hint_label.text()
    assert code.fix_button.text() == f"Run helper {name}" and code.fix_button.isVisibleTo(code.widget)
    code.fix_button.click()
    assert window.trust.is_trusted(helper_code)
    wait_check(code)
    drain(qt_app)
    assert not code.fix_button.isVisibleTo(code.widget)
    assert code.helper_actions.status(name).state == "ready"


# -- managing ----------------------------------------------------------------------------------------


def test_new_helper_adds_the_starter_and_opens_it(window, name) -> None:
    code = page(window)
    new = f"{name}_new"
    asked = []
    code.ask_name = lambda current: asked.append(current) or new
    before = window.document.undo_stack.count()
    code.row_menu("helpers").actions()[0].trigger()  # the section's New helper...
    assert asked == ["my_helper"]
    helper = window.project.helper(new)
    assert f"from {new} import double" in helper.code and window.trust.is_trusted(helper.code)
    assert window.document.undo_stack.count() == before + 1
    assert window.document.undo_stack.undoText() == "New helper"
    assert code.layer_id == f"helper:{new}" and code.editor.text() == helper.code


def test_new_helper_refuses_a_name_that_cannot_be_imported(window) -> None:
    code = page(window)
    for bad, why in (("2x", "Python name"), ("json", "standard library"), ("numpy", "editor uses")):
        code.ask_name = lambda current, b=bad: b
        code.helper_actions.new_helper()
        assert why in window.statusBar().currentMessage()
    assert len(window.project.helpers) == 1
    assert "New helper..." in [a.text() for a in code.row_menu("", "").actions()]


def test_rename_rewrites_the_imports_and_keeps_their_trust_and_the_tab(window, name) -> None:
    code = page(window)
    scene = window.project.layer("orbit").spec.params["code"]
    window.trust.trust([scene])
    open_helper(code, name)
    code.editor.setPlainText(code.editor.text() + "Z = 3\n")  # a draft follows the rename
    new = f"{name}_two"
    code.ask_name = lambda current: new
    code.explorer.select("helper", f"helper:{name}")
    code.rename_item()
    assert [h.name for h in window.project.helpers] == [new]
    rewritten = window.project.layer("orbit").spec.params["code"]
    assert f"import {new}" in rewritten and window.trust.is_trusted(rewritten)
    assert code.layer_id == f"helper:{new}" and code.editor.text().endswith("Z = 3\n")
    assert code.tabs.tabText(code.tabs.currentIndex()).startswith(new)
    window.document.undo_stack.undo()
    assert [h.name for h in window.project.helpers] == [name]


def test_delete_says_who_imports_it_and_asks_first(window, name) -> None:
    code = page(window)
    asked = []
    code.confirm = lambda title, text: asked.append(text) or False
    code.explorer.select("helper", f"helper:{name}")
    code.delete_item()
    assert "imported by Orbit" in asked[0] and len(window.project.helpers) == 1
    code.confirm = lambda title, text: True
    code.delete_item()
    assert window.project.helpers == [] and window.document.undo_stack.undoText() == "Delete helper"
    window.document.undo_stack.undo()
    assert [h.name for h in window.project.helpers] == [name]


def test_duplicate_adds_a_copy_under_a_free_name(window, name, helper_code) -> None:
    code = page(window)
    code.helper_actions.duplicate(name)
    assert [h.name for h in window.project.helpers] == [name, f"{name}_copy"]
    assert window.project.helper(f"{name}_copy").code == helper_code
    assert code.layer_id == f"helper:{name}_copy"


def test_export_writes_the_helper_with_the_text_in_the_editor(window, name, helper_code) -> None:
    code = page(window)
    open_helper(code, name)
    code.editor.setPlainText(helper_code + "W = 4\n")
    seen = {}

    def ask(entries, checked, folder, options):
        seen["entries"], seen["checked"] = entries, checked
        return None

    window.importer.ask_export = ask
    code.helper_actions.export(name)
    entry = next(e for e in seen["entries"] if e.key == f"helper:{name}")
    assert (entry.name, entry.kind, entry.source) == (name, "helper", helper_code + "W = 4\n")
    assert seen["checked"] == {f"helper:{name}"}
    labels = [a.text() for a in code.row_menu("helper", f"helper:{name}").actions()]
    assert labels == ["Open", "Run", "Rename...", "Duplicate", "Save as preset...", "Export...", "Delete"]


def test_save_as_preset_keeps_a_helper_preset(window, name, helper_code) -> None:
    code = page(window)
    code.ask_name = lambda current: f"{name} preset"
    code.save_item_as_preset(f"helper:{name}")
    preset = next(p for p in window.code_presets.presets() if p.name == f"{name} preset")
    assert (preset.kind, preset.code) == ("helper", helper_code)


# -- import and presets ------------------------------------------------------------------------------


def test_importing_a_file_as_a_helper_adds_it_and_asks_about_a_taken_name(window, qt_app, name) -> None:
    source = f"VALUE = 1  # {name}\n"
    window.importer.ask = lambda items, at, position, **kw: [ImportChoice(items[0], f"{name}_b", ci.HELPER)]
    window.importer.import_items([ImportItem(source, "b.py")])
    drain(qt_app)
    assert window.project.helper(f"{name}_b").code == source and not window.trust.is_trusted(source)
    assert "1 helper" in window.statusBar().currentMessage()
    asked = []

    class Asker:
        def __call__(self, filename):
            asked.append(filename)
            return "copy"

    window.importer.conflicts = lambda folder="", what="file": Asker()
    other = f"VALUE = 2  # {name}\n"
    window.importer.ask = lambda items, at, position, **kw: [
        ImportChoice(items[0], f"{name}_b", ci.HELPER, trust=True)
    ]
    window.importer.import_items([ImportItem(other, "b.py")])
    drain(qt_app)
    assert asked == [f"{name}_b"]
    assert window.project.helper(f"{name}_b_helper").code == other and window.trust.is_trusted(other)


def test_a_helper_preset_added_to_the_project_becomes_a_helper(window, name) -> None:
    code = page(window)
    preset = window.code_presets.add(f"Tools {name}", "helper", f"T = 1  # {name}\n")
    window.codePresetsChanged.emit()
    assert f"Tools {name}" in code.explorer.texts("user")
    item = code.explorer._find("preset", preset.id)
    assert not item.flags() & Qt.ItemFlag.ItemIsDragEnabled
    code.show_preset(preset.id)
    code.add_preset_to_project(edit_copy=True)
    added = window.project.helpers[-1]
    assert added.name == f"tools_{name}" and added.code == preset.code
    assert not window.trust.is_trusted(preset.code)  # yours: not run until allowed
    assert code.layer_id == f"helper:{added.name}"
    assert window.project.layers[-1].id == "wheel"  # no layer was added


# -- extract -----------------------------------------------------------------------------------------


def test_extract_moves_the_function_at_the_cursor_into_a_new_helper(window, name) -> None:
    code = page(window)
    code.explorer.select("layer", "wheel")
    text = f"def ring(r):\n    return Circle(radius=r)\n\n\n{OBJECT}# {name} extract\n"
    code.editor.setPlainText(text)
    code.editor.go_to_line(2)
    target = f"{name}_rings"
    asked = []
    code.ask_name = lambda current: asked.append(current) or target
    before = window.document.undo_stack.count()
    code.extract_action.trigger()
    assert asked == ["ring"]
    helper = window.project.helper(target)
    assert "def ring(r):" in helper.code and "from manim import *" in helper.code
    assert window.trust.is_trusted(helper.code)
    assert window.document.undo_stack.count() == before + 1
    assert code.editor.text().startswith(f"from {target} import ring\n")
    assert "def ring" not in code.editor.text() and code.is_dirty()  # the code is applied by Run
    code.editor.undo()  # one step of the editor's undo puts it back
    assert code.editor.text() == text


def test_extract_refuses_a_selection_that_is_not_whole_definitions(window, name) -> None:
    code = page(window)
    code.explorer.select("layer", "wheel")
    cursor = code.editor.textCursor()
    cursor.setPosition(0)
    cursor.movePosition(QTextCursor.MoveOperation.Down, QTextCursor.MoveMode.KeepAnchor)
    code.editor.setTextCursor(cursor)  # "PARAMS = {}" is not a function or class
    code.ask_name = lambda current: pytest.fail("no name is asked")
    code.helper_actions.extract()
    assert "not a function or class" in window.statusBar().currentMessage()
    assert len(window.project.helpers) == 1
    menu = code.editor_menu_at()
    assert menu.actions()[-1].text() == "Extract selection to helper…"
