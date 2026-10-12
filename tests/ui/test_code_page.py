"""The Code page (P6b.3, ADR 0041, decision session 36), through the real MainWindow.

Code layers are not rendered here (MANIM_STUDIO_CODE=0): render statuses are injected, and the
real renderer is exercised in test_acceptance_p6b3.py."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QTextFormat
from PySide6.QtTest import QTest

from manim_studio.core import edits
from manim_studio.core.schema import Canvas, Layer, Project, Spec
from manim_studio.ui import theme
from manim_studio.ui.code_render import CodeStatus
from manim_studio.ui.main_window import MainWindow
from ui.test_acceptance_v1 import menu_action

pytestmark = pytest.mark.ui

T = theme.THEME
ORBIT = "class Orbit(Scene):\n    def construct(self):\n        self.add(Dot())\n"
SPIN = "class Spin(Scene):\n    def construct(self):\n        self.add(Square())\n"


def code_layer(layer_id: str, name: str, code: str) -> Layer:
    return Layer(id=layer_id, name=name, spec=Spec(type="Code", params={"code": code}))


def write(tmp_path, name: str, layers: list[Layer]):
    project = Project(canvas=Canvas(width_px=320, height_px=180, fps=10, duration=2.0), layers=layers)
    path = tmp_path / name
    path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
    return path


@pytest.fixture
def window(qt_app, tmp_path):
    path = write(
        tmp_path,
        "scene.json",
        [
            Layer(id="dot", spec=Spec(type="Circle")),
            code_layer("orbit", "Orbit", ORBIT),
            code_layer("spin", "Spin", SPIN),
        ],
    )
    win = MainWindow()
    win.ask_trust = lambda names: "skip"
    win.resize(1500, 850)
    win.show()
    win.load(path)
    win.show_page("code")
    qt_app.processEvents()
    yield win
    win.close()


def page(window):
    return window.pages.pages["code"]


def project_code(window, layer_id: str = "orbit") -> str:
    return window.project.layer(layer_id).spec.params["code"]


def type_text(editor, text: str) -> None:
    """Type like a user: a new line is the Return key (QTest.keyClicks of a newline character
    crashes the offscreen platform)."""
    for number, line in enumerate(text.split("\n")):
        if number:
            QTest.keyClick(editor, Qt.Key.Key_Return)
        if line:
            QTest.keyClicks(editor, line)


def set_status(window, layer_id: str, status: CodeStatus | None) -> None:
    window.code.status = lambda i: status if i == layer_id else None
    window.code.statusChanged.emit(layer_id)


def list_texts(code_page) -> list[str]:
    return [code_page.list.item(i).text() for i in range(code_page.list.count())]


# -- the page and its layout ---------------------------------------------------------------------


def test_the_page_is_registered_after_compose_with_the_viewer_beside_the_editor(window) -> None:
    assert list(window.pages.pages)[:3] == ["compose", "animate", "code"] and window.page == "code"
    code = page(window)
    assert code.widget.isAncestorOf(window.viewer) and window.viewer.isVisible()
    assert code.widget.isAncestorOf(code.editor) and code.editor.isVisible()
    for view in (window.timeline, window.layers, window.properties):
        assert view.parentWidget() is window.pages.parking
    assert window.pages.bar.tabText(2) == "Code" and not window.pages.bar.tabIcon(2).isNull()  # Shift+3
    assert menu_action(window.menuBar(), "View", "Pages", "Code")


def test_the_viewer_stays_on_the_right_of_the_editor(window) -> None:
    code = page(window)
    assert code.editor.mapToGlobal(QPoint(0, 0)).x() < window.canvas.mapToGlobal(QPoint(0, 0)).x()


def test_only_code_layers_are_listed_and_the_first_is_shown(window) -> None:
    code = page(window)
    assert list_texts(code) == ["Orbit", "Spin"]
    assert code.layer_id == "orbit" and window.selection.layer_id == "orbit"
    assert code.editor.text() == ORBIT and code.title_label.text() == "Orbit"
    assert code.list.currentItem().text() == "Orbit"


def test_choosing_a_layer_in_the_list_selects_it_everywhere(window) -> None:
    code = page(window)
    code.list.setCurrentRow(1)
    assert window.selection.layer_id == "spin" and code.layer_id == "spin" and code.editor.text() == SPIN
    window.show_page("compose")
    assert window.layers.selected_id() == "spin"


def test_selecting_a_code_layer_elsewhere_shows_it_in_the_editor(window, qt_app) -> None:
    window.show_page("compose")
    window.selection.select_layer("spin")
    window.show_page("code")
    assert page(window).layer_id == "spin" and page(window).editor.text() == SPIN
    assert page(window).list.currentItem().text() == "Spin"


def test_a_selected_layer_that_is_not_code_leaves_the_editor_on_its_layer(window) -> None:
    window.show_page("compose")
    window.selection.select_layer("dot")
    assert page(window).layer_id == "orbit"
    window.show_page("code")
    assert page(window).layer_id == "orbit" and window.selection.layer_id == "orbit"


def test_with_no_project_the_editor_is_disabled_and_new_asks_for_one(qt_app) -> None:
    win = MainWindow()
    win.show()
    win.show_page("code")
    code = page(win)
    assert not code.editor.isEnabled() and code.list.count() == 0 and not code.run_button.isEnabled()
    code.new_layer()
    assert "project" in win.statusBar().currentMessage().lower()
    win.close()


def test_new_code_layer_adds_the_starter_scene_and_shows_it(window, qt_app) -> None:
    code = page(window)
    before = len(window.project.layers)
    code.new_button.click()
    qt_app.processEvents()
    assert len(window.project.layers) == before + 1
    ids = {x.id for x in window.project.layers} - {"dot", "orbit", "spin"}
    assert len(ids) == 1
    layer_id = ids.pop()
    assert code.layer_id == layer_id == window.selection.layer_id
    assert code.editor.text().startswith("class Orbit(Scene)") and code.list.count() == 3
    assert window.trust.is_trusted(code.editor.text())  # the starter is the library's own code


# -- the editor ------------------------------------------------------------------------------------------


def test_python_is_highlighted_with_the_theme_colours(window) -> None:
    editor = page(window).editor
    ranges = editor.document().firstBlock().layout().formats()
    first = {(r.start, r.length): r.format.foreground().color() for r in ranges}
    assert first[(0, 5)] == theme.qcolor(T.syntax_keyword)  # class
    assert first[(6, 5)] == theme.qcolor(T.syntax_definition)  # Orbit
    assert first[(12, 5)] == theme.qcolor(T.syntax_manim)  # Scene


def test_a_triple_quoted_string_is_coloured_over_its_lines(window) -> None:
    editor = page(window).editor
    editor.set_text('s = """one\ntwo\nthree""" + 1\n')
    colours = []
    for block in (editor.document().findBlockByNumber(i) for i in range(3)):
        colours.append({r.format.foreground().color().name() for r in block.layout().formats()})
    string = theme.qcolor(T.syntax_string).name()
    assert string in colours[0] and colours[1] == {string} and string in colours[2]


def test_the_gutter_grows_with_the_line_count_and_the_current_line_is_tinted(window) -> None:
    editor = page(window).editor
    small = editor.gutter_width()
    editor.set_text("\n".join(f"x = {i}" for i in range(1500)))
    assert editor.gutter_width() > small
    editor.go_to_line(40)
    tinted = [
        s
        for s in editor.extraSelections()
        if s.format.property(QTextFormat.Property.FullWidthSelection)
        and s.format.background().color() == theme.qcolor(T.code_line)
    ]
    assert len(tinted) == 1 and tinted[0].cursor.blockNumber() == 39
    assert editor.font().family() == theme.mono_font().family()


def test_a_new_line_keeps_the_indent_and_adds_four_after_a_colon(window) -> None:
    editor = page(window).editor
    editor.set_text("")
    type_text(editor, "def f():")
    QTest.keyClick(editor, Qt.Key.Key_Return)
    type_text(editor, "x = 1")
    QTest.keyClick(editor, Qt.Key.Key_Return)
    type_text(editor, "y = 2")
    assert editor.text() == "def f():\n    x = 1\n    y = 2"


def test_tab_inserts_spaces_to_the_next_stop_and_shift_tab_takes_them_back(window) -> None:
    editor = page(window).editor
    editor.set_text("")
    QTest.keyClick(editor, Qt.Key.Key_Tab)
    assert editor.text() == "    "
    type_text(editor, "ab")
    QTest.keyClick(editor, Qt.Key.Key_Tab)
    assert editor.text() == "    ab  "
    editor.set_text("        x")
    editor.set_cursor(9)
    QTest.keyClick(editor, Qt.Key.Key_Backtab)
    assert editor.text() == "    x"


def test_tab_and_shift_tab_indent_and_dedent_every_selected_line(window) -> None:
    editor = page(window).editor
    editor.set_text("a\n\nb\nc")
    editor.selectAll()
    QTest.keyClick(editor, Qt.Key.Key_Tab)
    assert editor.text() == "    a\n\n    b\n    c"  # the empty line stays empty
    QTest.keyClick(editor, Qt.Key.Key_Backtab)
    assert editor.text() == "a\n\nb\nc"
    editor.undo()  # a whole indent is one undo step
    assert editor.text() == "    a\n\n    b\n    c"


def test_backspace_removes_a_whole_indent_but_only_an_indent(window) -> None:
    editor = page(window).editor
    editor.set_text("        x")
    editor.set_cursor(8)
    QTest.keyClick(editor, Qt.Key.Key_Backspace)
    assert editor.text() == "    x"
    editor.set_text("ab   ")
    editor.set_cursor(5)
    QTest.keyClick(editor, Qt.Key.Key_Backspace)
    assert editor.text() == "ab  "


# -- run, dirty, drafts -------------------------------------------------------------------------------------


def test_typing_changes_only_the_editor_until_run(window) -> None:
    code = page(window)
    steps = window.document.undo_stack.count()
    assert not code.is_dirty() and not code.dirty_label.isVisible() and not code.revert_button.isEnabled()
    type_text(code.editor, "# note\n")
    assert code.is_dirty() and code.dirty_label.isVisible() and code.revert_button.isEnabled()
    assert list_texts(code) == ["Orbit *", "Spin"]
    assert project_code(window) == ORBIT and window.document.undo_stack.count() == steps


def test_typing_a_letter_and_deleting_it_is_clean_again(window) -> None:
    code = page(window)
    type_text(code.editor, "x")
    assert code.is_dirty()
    QTest.keyClick(code.editor, Qt.Key.Key_Backspace)
    assert not code.is_dirty() and list_texts(code) == ["Orbit", "Spin"]


def test_run_applies_the_text_as_one_undo_step_and_trusts_it(window) -> None:
    code = page(window)
    steps = window.document.undo_stack.count()
    type_text(code.editor, "# first\n")
    type_text(code.editor, "# second\n")
    assert not window.trust.is_trusted(code.editor.text())
    code.run_button.click()
    assert project_code(window) == code.editor.text() and project_code(window).startswith(
        "# first\n# second\n"
    )
    assert window.document.undo_stack.count() == steps + 1
    assert window.trust.is_trusted(project_code(window))
    assert not code.is_dirty() and not code.dirty_label.isVisible() and list_texts(code) == ["Orbit", "Spin"]
    window.document.undo_stack.undo()
    assert project_code(window) == ORBIT
    assert code.editor.text() == ORBIT and not code.is_dirty()  # a clean editor follows the undo


def test_ctrl_enter_in_the_editor_runs(window) -> None:
    code = page(window)
    type_text(code.editor, "# go\n")
    QTest.keyClick(code.editor, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    assert project_code(window).startswith("# go\n") and not code.is_dirty()
    assert code.editor.text().count("\n") == project_code(window).count("\n")  # no stray newline typed


def test_run_with_the_same_text_adds_no_undo_step_and_retries_a_failed_render(window, monkeypatch) -> None:
    code = page(window)
    steps = window.document.undo_stack.count()
    calls = []
    monkeypatch.setattr(window.code, "retry", lambda layer_id: calls.append(("retry", layer_id)))
    monkeypatch.setattr(window.code, "trust_layers", lambda project, ids: calls.append(("trust", ids)))
    set_status(window, "orbit", CodeStatus("ready", frames=10))
    code.run()
    assert calls == [("trust", ["orbit"])] and window.document.undo_stack.count() == steps
    calls.clear()
    set_status(window, "orbit", CodeStatus("error", error="NameError: x", line=3))
    code.run()
    assert calls == [("trust", ["orbit"]), ("retry", "orbit")]


def test_run_trusts_the_exact_text_so_editing_again_is_untrusted_until_the_next_run(window) -> None:
    code = page(window)
    type_text(code.editor, "a = 1\n")
    code.run()
    first = project_code(window)
    type_text(code.editor, "b = 2\n")
    assert window.trust.is_trusted(first) and not window.trust.is_trusted(code.editor.text())


def test_revert_drops_the_changes_and_is_one_step_of_the_editors_own_undo(window) -> None:
    code = page(window)
    type_text(code.editor, "# lost?\n")
    typed = code.editor.text()
    code.revert_button.click()
    assert code.editor.text() == ORBIT and not code.is_dirty() and not code.revert_button.isEnabled()
    assert list_texts(code) == ["Orbit", "Spin"]
    code.editor.undo()  # the editor's own undo brings the typing back
    assert code.editor.text() == typed and code.is_dirty()


def test_drafts_survive_switching_layers_and_pages(window, qt_app) -> None:
    code = page(window)
    type_text(code.editor, "# orbit draft\n")
    draft = code.editor.text()
    code.list.setCurrentRow(1)
    assert code.editor.text() == SPIN and not code.is_dirty()
    assert list_texts(code) == ["Orbit *", "Spin"]  # the other layer's draft is marked in the list
    type_text(code.editor, "# spin draft\n")
    window.show_page("compose")
    window.show_page("code")
    assert code.layer_id == "spin" and code.editor.text().startswith("# spin draft")
    code.list.setCurrentRow(0)
    assert code.editor.text() == draft and code.is_dirty()
    assert project_code(window) == ORBIT and project_code(window, "spin") == SPIN  # nothing was applied
    assert list_texts(code) == ["Orbit *", "Spin *"]


def test_the_cursor_of_a_draft_comes_back_with_it(window) -> None:
    code = page(window)
    code.editor.go_to_line(2)
    type_text(code.editor, "z")
    position = code.editor.cursor_position()
    code.list.setCurrentRow(1)
    code.list.setCurrentRow(0)
    assert code.editor.cursor_position() == position


def test_the_project_changing_under_a_clean_editor_is_shown(window) -> None:
    code = page(window)
    code.run()  # nothing to apply: still clean
    window.builds.submit(
        lambda project: edits.update_layer(
            project, "orbit", spec=project.layer("orbit").spec.model_copy(update={"params": {"code": SPIN}})
        ),
        "Change code",
    )
    assert code.editor.text() == SPIN and not code.is_dirty() and not code.notice.isVisible()


def test_the_project_changing_under_a_dirty_editor_keeps_the_text_and_says_so(window) -> None:
    code = page(window)
    type_text(code.editor, "# mine\n")
    mine = code.editor.text()
    window.builds.submit(
        lambda project: edits.update_layer(
            project, "orbit", spec=project.layer("orbit").spec.model_copy(update={"params": {"code": SPIN}})
        ),
        "Edit in Properties",
    )
    assert code.editor.text() == mine and code.is_dirty() and code.notice.isVisible()
    code.revert_button.click()
    assert code.editor.text() == SPIN and not code.notice.isVisible() and not code.is_dirty()


def test_the_notice_also_shows_when_the_draft_comes_back_after_a_switch(window) -> None:
    code = page(window)
    type_text(code.editor, "# mine\n")
    code.list.setCurrentRow(1)
    window.builds.submit(
        lambda project: edits.update_layer(
            project,
            "orbit",
            spec=project.layer("orbit").spec.model_copy(update={"params": {"code": "x = 1\n"}}),
        ),
        "Edit in Properties",
    )
    code.list.setCurrentRow(0)
    assert code.editor.text().startswith("# mine") and code.notice.isVisible()


def test_undoing_a_run_under_newer_typing_keeps_the_typing(window) -> None:
    code = page(window)
    type_text(code.editor, "# applied\n")
    code.run()
    type_text(code.editor, "# newer\n")
    typed = code.editor.text()
    window.document.undo_stack.undo()  # the Edit menu's undo: the project goes back to the old code
    assert project_code(window) == ORBIT
    assert code.editor.text() == typed and code.is_dirty() and code.notice.isVisible()


def test_a_deleted_layers_draft_comes_back_when_the_delete_is_undone(window, qt_app) -> None:
    code = page(window)
    type_text(code.editor, "# keep me\n")
    typed = code.editor.text()
    window.layers.select("orbit")
    window.layers.delete_selected()
    assert "orbit" not in [x.id for x in window.project.layers]
    assert code.layer_id == "spin" and list_texts(code) == ["Spin"]
    window.document.undo_stack.undo()
    code.list.setCurrentRow(0)
    assert code.layer_id == "orbit" and code.editor.text() == typed and code.is_dirty()


def test_opening_another_project_drops_drafts_and_says_how_many(window, tmp_path, qt_app) -> None:
    code = page(window)
    type_text(code.editor, "# one\n")
    code.list.setCurrentRow(1)
    type_text(code.editor, "# two\n")
    other = write(tmp_path, "other.json", [code_layer("second", "Other", "class A(Scene):\n    pass\n")])
    window.load(other)
    qt_app.processEvents()
    assert len(code.drafts) == 0 and code.layer_id == "second" == window.selection.layer_id
    assert code.editor.text() == "class A(Scene):\n    pass\n" and not code.is_dirty()
    assert "Discarded 2" in window.statusBar().currentMessage()


# -- render status and errors ------------------------------------------------------------


def test_the_render_state_shows_under_the_editor(window) -> None:
    code = page(window)
    assert code.state_label.text() == "Not rendered yet" and not code.error_label.isVisible()
    set_status(window, "orbit", CodeStatus("rendering", frames=20))
    assert code.state_label.text() == "Rendering... 20 frames"
    set_status(window, "orbit", CodeStatus("ready", frames=90))
    assert code.state_label.text() == "Ready - 90 frames"
    set_status(window, "orbit", CodeStatus("untrusted"))
    assert "not trusted" in code.state_label.text()


def test_a_status_of_another_layer_does_not_change_the_output(window) -> None:
    code = page(window)
    set_status(window, "spin", CodeStatus("error", error="NameError: x", line=2))
    assert code.state_label.text() == "Not rendered yet" and not code.error_label.isVisible()
    assert list_texts(code) == ["Orbit", "Spin  (error)"]


def test_an_error_with_a_line_is_a_link_that_moves_the_cursor_there(window, qt_app) -> None:
    code = page(window)
    set_status(window, "orbit", CodeStatus("error", error="NameError: name 'Dotty' is not defined", line=3))
    assert code.state_label.text() == "Error" and code.error_label.isVisible()
    assert code.error_label.plain == "line 3: NameError: name 'Dotty' is not defined"
    assert code.editor.error_line == 3
    tinted = [
        s
        for s in code.editor.extraSelections()
        if s.format.background().color() == theme.qcolor(T.code_error_line)
    ]
    assert len(tinted) == 1 and tinted[0].cursor.blockNumber() == 2
    code.editor.go_to_line(1)
    QTest.mouseClick(code.error_label, Qt.MouseButton.LeftButton)
    assert code.editor.current_line() == 3


def test_an_error_line_past_the_end_goes_to_the_last_line(window) -> None:
    code = page(window)
    set_status(window, "orbit", CodeStatus("error", error="SyntaxError: bad", line=99))
    QTest.mouseClick(code.error_label, Qt.MouseButton.LeftButton)
    assert code.editor.current_line() == code.editor.blockCount()


def test_an_error_without_a_line_is_not_a_link(window) -> None:
    code = page(window)
    set_status(window, "orbit", CodeStatus("error", error="define exactly one Scene subclass (found: none)"))
    assert code.error_label.isVisible() and code.error_label.line is None and code.editor.error_line is None
    code.editor.go_to_line(2)
    QTest.mouseClick(code.error_label, Qt.MouseButton.LeftButton)
    assert code.editor.current_line() == 2
    assert code.error_label.cursor().shape() != Qt.CursorShape.PointingHandCursor


def test_with_unapplied_changes_the_error_is_labelled_stale_and_not_tinted(window) -> None:
    code = page(window)
    set_status(window, "orbit", CodeStatus("error", error="NameError: x", line=3))
    type_text(code.editor, "# above\n")
    assert code.state_label.text() == "Error (from the last run)" and code.editor.error_line is None
    code.revert()
    assert code.state_label.text() == "Error" and code.editor.error_line == 3


def test_unapplied_changes_are_pointed_out_next_to_a_ready_render(window) -> None:
    code = page(window)
    set_status(window, "orbit", CodeStatus("ready", frames=10))
    type_text(code.editor, "x")
    assert "not run" in code.state_label.text() and code.state_label.text().startswith("Ready - 10 frames")


def test_the_error_is_cleared_when_the_status_is_cleared(window) -> None:
    code = page(window)
    set_status(window, "orbit", CodeStatus("error", error="NameError: x", line=3))
    set_status(window, "orbit", None)
    assert not code.error_label.isVisible() and code.editor.error_line is None


def test_switching_layers_shows_that_layers_status(window) -> None:
    code = page(window)
    window.code.status = lambda i: CodeStatus("error", error="Boom: b", line=2) if i == "spin" else None
    code.list.setCurrentRow(1)
    assert code.error_label.plain == "line 2: Boom: b" and code.editor.error_line == 2
    code.list.setCurrentRow(0)
    assert not code.error_label.isVisible() and code.editor.error_line is None


# -- more guards ----------------------------------------------------------------------------


def test_ctrl_enter_reaches_the_editors_own_key_handler_too(window) -> None:
    """The page's shortcut normally takes Ctrl+Enter first; the editor still asks to run itself."""
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent

    code = page(window)
    asked = []
    code.editor.runRequested.connect(lambda: asked.append(True))
    ctrl = Qt.KeyboardModifier.ControlModifier
    code.editor.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, ctrl))
    code.editor.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Enter, ctrl))
    assert asked == [True, True] and code.editor.text() == ORBIT  # no newline typed


def test_a_selection_ending_at_a_line_start_does_not_indent_that_line(window) -> None:
    editor = page(window).editor
    editor.set_text("a\nb\nc\n")
    cursor = editor.textCursor()
    cursor.setPosition(0)
    cursor.setPosition(4, cursor.MoveMode.KeepAnchor)  # "a\nb\n": ends at the start of "c"
    editor.setTextCursor(cursor)
    QTest.keyClick(editor, Qt.Key.Key_Tab)
    assert editor.text() == "    a\n    b\nc\n"


def test_a_restored_draft_that_is_then_run_leaves_no_stale_marker(window) -> None:
    code = page(window)
    type_text(code.editor, "# draft\n")
    code.list.setCurrentRow(1)
    code.list.setCurrentRow(0)  # the draft is back in the editor
    assert list_texts(code) == ["Orbit *", "Spin"]
    code.run()
    assert not code.is_dirty() and list_texts(code) == ["Orbit", "Spin"] and len(code.drafts) == 0
    code.list.setCurrentRow(1)
    code.list.setCurrentRow(0)
    assert code.editor.text() == project_code(window) and not code.is_dirty()


def test_revert_on_a_restored_draft_leaves_no_stale_marker(window) -> None:
    code = page(window)
    type_text(code.editor, "# draft\n")
    code.list.setCurrentRow(1)
    code.list.setCurrentRow(0)
    code.revert()
    assert list_texts(code) == ["Orbit", "Spin"] and len(code.drafts) == 0


def test_a_status_with_a_line_but_not_an_error_has_no_error_line(window) -> None:
    code = page(window)
    set_status(window, "orbit", CodeStatus("ready", frames=3, line=2))
    assert code.editor.error_line is None and not code.error_label.isVisible()


def test_a_run_that_fails_to_apply_says_so_and_changes_nothing(window, monkeypatch) -> None:
    code = page(window)
    type_text(code.editor, "# x\n")

    def refuse(op, text, **kwargs):
        raise edits.EditError("no such layer")

    monkeypatch.setattr(window.builds, "submit", refuse)
    steps = window.document.undo_stack.count()
    code.run()
    assert (
        "no such layer" in window.statusBar().currentMessage() and window.document.undo_stack.count() == steps
    )
    assert code.is_dirty()


def test_shift_tab_takes_only_the_indent_that_is_there(window) -> None:
    editor = page(window).editor
    editor.set_text("  ab\nabc\n\tz")
    editor.selectAll()
    QTest.keyClick(editor, Qt.Key.Key_Backtab)
    assert editor.text() == "ab\nabc\nz"


def test_an_edit_elsewhere_leaves_a_clean_editor_alone(window) -> None:
    code = page(window)
    type_text(code.editor, "# t\n")
    code.revert()  # clean again, with the editor's undo history holding the revert
    assert code.editor.document().isUndoAvailable()
    window.builds.submit(lambda project: edits.update_layer(project, "dot", name="Renamed"), "Rename")
    assert code.editor.document().isUndoAvailable() and code.editor.text() == ORBIT


def test_backspace_after_spaces_removes_one_space_unless_it_is_a_whole_indent(window) -> None:
    editor = page(window).editor
    editor.set_text("      x")  # six spaces, then x
    editor.set_cursor(6)
    QTest.keyClick(editor, Qt.Key.Key_Backspace)
    assert editor.text() == "     x"  # not a multiple of four: one space
    editor.set_text("ab      ")
    editor.set_cursor(8)
    QTest.keyClick(editor, Qt.Key.Key_Backspace)
    assert editor.text() == "ab     "  # after text, even at a multiple of four: one space


def test_a_selection_made_before_the_page_was_first_shown_is_the_one_edited(qt_app, tmp_path) -> None:
    path = write(
        tmp_path, "two.json", [code_layer("orbit", "Orbit", ORBIT), code_layer("spin", "Spin", SPIN)]
    )
    win = MainWindow()
    win.ask_trust = lambda names: "skip"
    win.resize(1500, 850)
    win.show()
    win.load(path)
    win.selection.select_layer("spin")
    win.show_page("code")
    assert page(win).layer_id == "spin" and page(win).editor.text() == SPIN
    win.close()


def test_a_layer_deleted_while_another_page_is_shown_keeps_its_draft(window, qt_app) -> None:
    code = page(window)
    type_text(code.editor, "# keep me\n")
    typed = code.editor.text()
    window.show_page("compose")
    window.layers.select("orbit")
    window.layers.delete_selected()
    assert code.layer_id == "spin" and code.editor.text() == SPIN
    window.document.undo_stack.undo()
    window.selection.select_layer("orbit")
    window.show_page("code")
    assert code.layer_id == "orbit" and code.editor.text() == typed and code.is_dirty()
