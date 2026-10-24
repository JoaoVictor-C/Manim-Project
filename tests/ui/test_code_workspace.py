"""The Code page as a workspace (P12.5): explorer sections, tabs, presets, find, go to, quick open,
settings, output and status strip, and files dropped on it."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDropEvent

from manim_studio.core import python_templates
from manim_studio.core.schema import Canvas, Layer, Project, Spec
from manim_studio.ui.main_window import MainWindow
from manim_studio.ui.quick_open import QuickItem
from ui.code_page_helpers import choose, list_texts, project_ids

pytestmark = pytest.mark.ui

ORBIT = "class Orbit(Scene):\n    def construct(self):\n        self.add(Dot())\n"
SPIN = "class Spin(Scene):\n    def construct(self):\n        self.add(Square())\n"
OBJECT = "PARAMS = {}\n\ndef build(p):\n    return Circle()\n"


def make_window(qt_app, tmp_path) -> MainWindow:
    project = Project(
        canvas=Canvas(width_px=320, height_px=180, fps=10, duration=2.0),
        layers=[
            Layer(id="dot", spec=Spec(type="Circle")),
            Layer(id="orbit", name="Orbit", spec=Spec(type="Code", params={"code": ORBIT})),
            Layer(id="spin", name="Spin", spec=Spec(type="Code", params={"code": SPIN})),
            Layer(id="wheel", name="Wheel", spec=Spec(type="Python", params={"code": OBJECT})),
        ],
    )
    path = tmp_path / "scene.json"
    path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.ask_trust = lambda names: "skip"
    win.resize(1500, 850)
    win.show()
    win.load(path)
    win.show_page("code")
    qt_app.processEvents()
    return win


@pytest.fixture
def window(qt_app, tmp_path):
    win = make_window(qt_app, tmp_path)
    yield win
    win.document.undo_stack.setClean()
    win.close()


def names(code) -> list[str]:
    """The layers' names without the marks (a Python object not run yet has a "?")."""
    return [text.split("  ")[0] for text in list_texts(code)]


def page(window):
    return window.pages.pages["code"]


def drain(qt_app) -> None:
    for _ in range(20):
        qt_app.processEvents()


# -- the explorer ---------------------------------------------------------------------------


def test_the_explorer_lists_the_project_then_the_preset_groups(window) -> None:
    code = page(window)
    assert names(code) == ["Orbit", "Spin", "Wheel"] and list_texts(code)[2].endswith("?")
    assert code.explorer.texts("builtin") == list(python_templates.TEMPLATES)
    assert code.explorer.texts("user") == [] and code.explorer.texts("online") == []


def test_my_and_downloaded_presets_are_listed_in_their_groups(window) -> None:
    window.code_presets.add("Mine", "object", OBJECT)
    window.code_presets.add("Fetched", "scene", ORBIT, origin="online", source_url="https://example.com/x.py")
    window.codePresetsChanged.emit()
    code = page(window)
    assert code.explorer.texts("user") == ["Mine"] and code.explorer.texts("online") == ["Fetched"]


def test_the_filter_narrows_the_explorer(window) -> None:
    code = page(window)
    code.filter.setText("whe")
    assert names(code) == ["Wheel"] and code.explorer.texts("builtin") == []
    code.filter.setText("")
    assert len(names(code)) == 3


# -- tabs -------------------------------------------------------------------------------------


def test_a_tab_opens_for_each_layer_visited_and_follows_the_editor(window) -> None:
    code = page(window)
    choose(code, 0)
    choose(code, 2)
    assert [code.tabs.tabText(i) for i in range(code.tabs.count())] == ["Orbit", "Wheel"]
    assert code.tabs.tabData(code.tabs.currentIndex()) == "wheel"
    code.tabs.setCurrentIndex(0)
    assert code.layer_id == "orbit" and window.selection.layer_id == "orbit"


def test_a_tab_shows_a_dot_while_the_layer_has_unapplied_changes(window) -> None:
    code = page(window)
    choose(code, 0)
    code.editor.setPlainText(ORBIT + "# changed\n")
    assert code.tabs.tabText(code.tabs.currentIndex()) == "Orbit  ●"
    code.revert()
    assert code.tabs.tabText(code.tabs.currentIndex()) == "Orbit"


def test_closing_a_tab_keeps_the_layer_and_moves_to_a_neighbour(window) -> None:
    code = page(window)
    choose(code, 0)
    choose(code, 1)
    assert code.tabs.count() == 2 and code.tabs.tabsClosable()
    code._close_tab(1)
    assert code.layer_id == "orbit" and code.tabs.count() == 1 and not code.tabs.tabsClosable()
    assert len(window.project.layers) == 4


# -- presets ---------------------------------------------------------------------------------


def builtin(window):
    return next(p for p in window.code_presets.presets() if p.builtin)


def test_choosing_a_preset_shows_its_code_read_only(window) -> None:
    code = page(window)
    preset = builtin(window)
    code.explorer.select("preset", preset.id)
    assert code.views.currentIndex() == 1 and code.preview_editor.text() == preset.code
    assert code.preview_editor.isReadOnly() and not code.run_button.isEnabled()
    assert preset.name in code.preset_title.text()
    choose(code, 1)  # a layer again
    assert code.views.currentIndex() == 0 and code.run_button.isEnabled()


def test_add_to_project_places_the_preset_and_edit_a_copy_opens_it(window, qt_app) -> None:
    code = page(window)
    preset = builtin(window)
    code.explorer.select("preset", preset.id)
    code.preset_add_button.click()
    drain(qt_app)
    added = window.project.layers[-1]
    assert added.spec.type == "Python" and added.spec.params["code"] == preset.code
    code.explorer.select("preset", preset.id)
    code.preset_copy_button.click()
    drain(qt_app)
    assert code.preset_id is None and code.views.currentIndex() == 0
    assert code.layer_id == window.project.layers[-1].id and len(window.project.layers) == 6


def test_double_clicking_a_preset_adds_it(window, qt_app) -> None:
    code = page(window)
    code.explorer.select("preset", builtin(window).id)
    code._on_opened("preset", builtin(window).id)
    drain(qt_app)
    assert len(window.project.layers) == 5


def test_rename_and_delete_apply_to_my_presets_only(window) -> None:
    code = page(window)
    mine = window.code_presets.add("Mine", "object", OBJECT)
    window.codePresetsChanged.emit()
    code.explorer.select("preset", builtin(window).id)
    code.rename_item()
    code.delete_item()
    assert builtin(window) is not None and "cannot" in window.statusBar().currentMessage()
    code.explorer.select("preset", mine.id)
    code.ask_name = lambda current: "Renamed"
    code.rename_item()
    assert window.code_presets.get(mine.id).name == "Renamed" and "Renamed" in code.explorer.texts("user")
    code.confirm = lambda title, text: False
    code.delete_item()
    assert window.code_presets.get(mine.id) is not None
    code.confirm = lambda title, text: True
    code.delete_item()
    assert window.code_presets.get(mine.id) is None and code.explorer.texts("user") == []
    assert len(window.project.layers) == 4  # no layer was deleted by mistake


def test_save_as_preset_stores_the_editor_text_and_asks_when_the_name_is_taken(window) -> None:
    code = page(window)
    choose(code, 2)  # Wheel, an object
    code.editor.setPlainText(OBJECT + "# edited\n")
    code.ask_name = lambda current: "My wheel"
    code.save_as_preset()
    saved = next(p for p in window.code_presets.presets() if p.name == "My wheel")
    assert saved.kind == "object" and saved.code.endswith("# edited\n") and saved.origin == "user"
    assert "Saved as a preset" in window.statusBar().currentMessage()
    code.editor.setPlainText(OBJECT + "# edited again\n")
    asked = []
    window.importer.conflicts = lambda folder="", what="file": (
        lambda name: asked.append((name, what)) or "replace"
    )
    code.save_as_preset()
    assert asked == [("My wheel", "preset")]
    assert [p.code for p in window.code_presets.presets() if p.name == "My wheel"] == [
        OBJECT + "# edited again\n"
    ]


def test_row_menus_match_what_the_row_can_do(window) -> None:
    code = page(window)
    mine = window.code_presets.add("Mine", "object", OBJECT)
    labels = lambda menu: [a.text() for a in menu.actions() if a.text()]  # noqa: E731
    assert labels(code.row_menu("preset", builtin(window).id)) == [
        "Add to project",
        "Edit a copy",
        "Export...",
    ]
    assert labels(code.row_menu("preset", mine.id))[-2:] == ["Rename...", "Delete"]
    assert "New code layer" in labels(code.row_menu("", ""))


# -- find, go to, quick open ------------------------------------------------------------------


def test_find_opens_the_bar_and_walks_the_matches(window) -> None:
    code = page(window)
    choose(code, 0)
    code.open_find()
    assert code.find_bar.is_open
    code.find_bar.find_edit.setText("Dot")
    assert code.find_bar.match_count() == 1
    code.find_next()
    code.find_previous()
    code.find_bar.close_bar()
    assert not code.find_bar.is_open


def test_replace_opens_the_replace_row(window) -> None:
    code = page(window)
    choose(code, 0)
    code.open_replace()
    assert code.find_bar.is_open and not code.find_bar.replace_row.isHidden()


def test_opening_find_while_looking_at_a_preset_goes_back_to_the_editor(window) -> None:
    code = page(window)
    choose(code, 0)
    code.explorer.select("preset", builtin(window).id)
    code.open_find()
    assert code.views.currentIndex() == 0 and code.find_bar.is_open


def test_go_to_line_moves_the_cursor(window) -> None:
    code = page(window)
    choose(code, 0)
    seen = []
    code.ask_line = lambda current, last: seen.append((current, last)) or 3
    code.goto_line()
    assert seen == [(1, 4)] and code.editor.current_line() == 3
    code.ask_line = lambda current, last: None
    code.goto_line()
    assert code.editor.current_line() == 3


def test_quick_open_lists_layers_and_presets_and_opens_the_choice(window) -> None:
    code = page(window)
    items = code.quick_items()
    assert [i.label for i in items[:3]] == ["Orbit", "Spin", "Wheel"]
    assert {i.source for i in items} == {"layer", "preset"}
    code.quick = lambda items: QuickItem("layer", "spin", "Spin")
    code.quick_open()
    assert code.layer_id == "spin" and window.selection.layer_id == "spin"
    preset = builtin(window)
    code.quick = lambda items: QuickItem("preset", preset.id, preset.name)
    code.quick_open()
    assert code.preset_id == preset.id and code.views.currentIndex() == 1
    code.quick = lambda items: None
    code.quick_open()
    assert code.preset_id == preset.id


# -- settings, output, status -----------------------------------------------------------------


def test_a_setting_in_the_menu_changes_the_editor_and_is_remembered(window, qt_app, tmp_path) -> None:
    code = page(window)
    code.setting_actions["word_wrap"].setChecked(True)
    code.tab_actions[2].trigger()
    assert code.editor.settings.word_wrap and code.editor.settings.tab_width == 2
    assert code.preview_editor.settings.word_wrap and code.indent_label.text() == "Spaces: 2"
    assert window.prefs.editor_settings().word_wrap and window.prefs.editor_settings().tab_width == 2
    other = make_window(qt_app, tmp_path)
    try:
        again = page(other)
        assert again.editor.settings.word_wrap and again.setting_actions["word_wrap"].isChecked()
        assert again.tab_actions[2].isChecked()
    finally:
        other.document.undo_stack.setClean()
        other.close()


def test_zooming_is_remembered(window) -> None:
    code = page(window)
    start = code.editor.settings.font_size
    code.editor.zoom_in()
    assert code.editor.settings.font_size == start + 1
    assert window.prefs.editor_settings().font_size == start + 1


def test_trimming_on_run_is_a_setting(window) -> None:
    code = page(window)
    choose(code, 0)
    code.setting_actions["trim_trailing_whitespace"].setChecked(True)
    code.editor.setPlainText(ORBIT.replace("def construct(self):", "def construct(self):   "))
    code.run()
    assert "   \n" not in code.editor.text()


def test_the_output_can_be_hidden_and_stays_hidden(window, qt_app, tmp_path) -> None:
    code = page(window)
    assert code.output.isVisibleTo(code.widget)
    code.toggle_output()
    assert not code.output.isVisibleTo(code.widget)
    other = make_window(qt_app, tmp_path)
    try:
        assert not page(other).output.isVisibleTo(page(other).widget)
    finally:
        other.document.undo_stack.setClean()
        other.close()
    code.toggle_output()
    assert window.prefs.option("code_output_open", False)


def test_the_status_strip_follows_the_cursor_and_the_layer(window) -> None:
    code = page(window)
    choose(code, 0)
    code.editor.go_to_line(2)
    assert code.cursor_label.text() == "Ln 2, Col 1"
    assert code.kind_label.text() == "Manim scene"
    choose(code, 2)
    assert code.kind_label.text() == "Python object"


# -- files dropped on the page ----------------------------------------------------------------


def file_drop(path) -> QDropEvent:
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path))])
    event = QDropEvent(
        QPointF(5, 5),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    event.keep_alive = mime  # the event does not own its mime data
    return event


def test_a_py_file_dropped_on_the_editor_opens_the_import_window(window, tmp_path, monkeypatch) -> None:
    file = tmp_path / "Wheel.py"
    file.write_text(OBJECT, encoding="utf-8")
    seen = []
    monkeypatch.setattr(window.importer, "import_paths", lambda paths, *a, **k: seen.append(list(paths)))
    code = page(window)
    event = file_drop(file)
    assert code._drops.eventFilter(code.editor.viewport(), event)
    assert seen == [[file]]


def test_other_drops_on_the_editor_are_left_alone(window, tmp_path) -> None:
    text = tmp_path / "notes.txt"
    text.write_text("x", encoding="utf-8")
    code = page(window)
    assert not code._drops.eventFilter(code.editor.viewport(), file_drop(text))


def test_files_dropped_on_the_explorer_open_the_import_window(window, tmp_path, monkeypatch) -> None:
    file = tmp_path / "Wheel.py"
    file.write_text(OBJECT, encoding="utf-8")
    seen = []
    monkeypatch.setattr(window.importer, "import_paths", lambda paths, *a, **k: seen.append(list(paths)))
    page(window).explorer.dropEvent(file_drop(file))
    assert seen == [[file]]


def test_project_ids_helper_matches_the_list(window) -> None:
    assert project_ids(page(window)) == ["orbit", "spin", "wheel"]
