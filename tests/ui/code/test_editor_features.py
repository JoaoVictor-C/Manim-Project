"""The code editor's settings and VS Code style editing (P12): the settings data and its storage,
``apply_settings`` live, the line commands (and their keys, each one undo step), auto-closing
brackets and quotes, and zoom. Offscreen, on a bare ``CodeEditor``."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QTextFormat, QTextOption, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QPlainTextEdit

from manim_studio.ui.code.code_editor import CodeEditor
from manim_studio.ui.session import editor_settings as es
from manim_studio.ui.session.editor_settings import EditorSettings, clamp, from_json, to_json
from manim_studio.ui.session.preferences import Preferences
from manim_studio.ui.style import theme

pytestmark = pytest.mark.ui

K = Qt.Key
CTRL, SHIFT, ALT = (
    Qt.KeyboardModifier.ControlModifier,
    Qt.KeyboardModifier.ShiftModifier,
    Qt.KeyboardModifier.AltModifier,
)


@pytest.fixture
def editor(qt_app):
    widget = CodeEditor()
    widget.resize(500, 300)
    return widget


def type_text(widget, text: str) -> None:
    for number, line in enumerate(text.split("\n")):
        if number:
            QTest.keyClick(widget, K.Key_Return)
        if line:
            QTest.keyClicks(widget, line)


def press(widget, key, mods=Qt.KeyboardModifier.NoModifier) -> None:
    QTest.keyClick(widget, key, mods)


def select_lines(widget, first: int, last: int) -> None:
    """Select lines ``first``..``last`` (0-based) from their start to their end."""
    widget._select_lines(first, last)


def undo_all(widget) -> None:
    while widget.document().isUndoAvailable():
        widget.undo()


# -- the settings data ----------------------------------------


def test_defaults_are_the_documented_ones() -> None:
    s = EditorSettings()
    assert (s.font_size, s.tab_width) == (10, 4)
    assert (s.word_wrap, s.line_numbers, s.highlight_line, s.show_whitespace) == (False, True, True, False)
    assert (s.auto_close_brackets, s.trim_trailing_whitespace) == (True, False)


def test_clamp_keeps_font_and_tab_width_in_range() -> None:
    assert clamp(EditorSettings(font_size=2)).font_size == es.MIN_FONT_SIZE == 7
    assert clamp(EditorSettings(font_size=99)).font_size == es.MAX_FONT_SIZE == 32
    assert clamp(EditorSettings(font_size=12)).font_size == 12
    assert [clamp(EditorSettings(tab_width=w)).tab_width for w in (1, 2, 3, 4, 5, 6, 7, 8, 12)] == [
        2,
        2,
        2,
        4,
        4,
        4,
        8,
        8,
        8,
    ]


def test_json_round_trip_keeps_every_field() -> None:
    s = EditorSettings(
        font_size=14,
        tab_width=2,
        word_wrap=True,
        line_numbers=False,
        highlight_line=False,
        show_whitespace=True,
        auto_close_brackets=False,
        trim_trailing_whitespace=True,
    )
    assert from_json(to_json(s)) == s
    assert from_json(to_json(EditorSettings())) == EditorSettings()


@pytest.mark.parametrize("text", ["", "garbage", "[1, 2]", "null", "42", '"x"', "{", None])
def test_from_json_falls_back_to_the_defaults_on_garbage(text) -> None:
    assert from_json(text) == EditorSettings()


def test_from_json_is_tolerant_field_by_field() -> None:
    text = (
        '{"font_size": "big", "tab_width": 8, "word_wrap": 1, "line_numbers": false, '
        '"highlight_line": null, "show_whitespace": true, "mystery": 5, "trim_trailing_whitespace": "yes"}'
    )
    s = from_json(text)
    assert s == EditorSettings(tab_width=8, line_numbers=False, show_whitespace=True)
    assert from_json('{"font_size": true}').font_size == 10  # a flag is not a number
    assert from_json('{"font_size": 500, "tab_width": 3}') == EditorSettings(font_size=32, tab_width=2)


def test_preferences_store_the_settings_as_json_under_editor_settings(tmp_path) -> None:
    ini = tmp_path / "p.ini"
    prefs = Preferences(ini)
    assert prefs.editor_settings() == EditorSettings()
    chosen = EditorSettings(font_size=13, word_wrap=True, tab_width=2)
    prefs.set_editor_settings(chosen)
    assert Preferences(ini).editor_settings() == chosen
    assert "editor_settings" in ini.read_text(encoding="utf-8")
    prefs.set_option("x", 1)  # other keys do not disturb it
    assert Preferences(ini).editor_settings() == chosen


def test_unreadable_stored_settings_give_the_defaults(tmp_path) -> None:
    ini = tmp_path / "p.ini"
    ini.write_text("[General]\neditor_settings=not json\n", encoding="utf-8")
    assert Preferences(ini).editor_settings() == EditorSettings()


# -- apply_settings, live ------------------------------------------------------------------------


def test_a_new_editor_has_the_default_behaviour(editor) -> None:
    assert editor.settings == EditorSettings()
    assert editor.indent == "    "
    assert editor.font().pointSize() == 10
    assert editor.lineWrapMode() == QPlainTextEdit.LineWrapMode.NoWrap
    assert editor.gutter_width() > 0


def test_font_size_is_applied_and_the_gutter_follows(editor) -> None:
    before = editor.gutter_width()
    editor.apply_settings(EditorSettings(font_size=20))
    assert editor.font().pointSize() == 20
    assert editor.font().family() == theme.mono_font().family()
    assert editor.gutter_width() > before
    assert editor.viewportMargins().left() == editor.gutter_width()
    editor.apply_settings(EditorSettings(font_size=1000))  # clamped
    assert editor.font().pointSize() == 32


def test_tab_width_sets_the_tab_stops_and_the_indent(editor) -> None:
    editor.apply_settings(EditorSettings(tab_width=2))
    assert editor.indent == "  "
    assert editor.tabStopDistance() == pytest.approx(2 * editor.fontMetrics().horizontalAdvance(" "))
    editor.set_text("")
    press(editor, K.Key_Tab)
    assert editor.text() == "  "
    type_text(editor, "a:")
    press(editor, K.Key_Return)
    assert editor.text() == "  a:\n    "  # the new line adds one indent of two
    press(editor, K.Key_Backspace)  # a whole indent
    assert editor.text() == "  a:\n  "
    editor.apply_settings(EditorSettings(tab_width=8))
    editor.set_text("")
    press(editor, K.Key_Tab)
    assert editor.text() == " " * 8


def test_tab_width_applies_to_indent_and_dedent_of_a_selection(editor) -> None:
    editor.apply_settings(EditorSettings(tab_width=2))
    editor.set_text("a\nb")
    editor.selectAll()
    press(editor, K.Key_Tab)
    assert editor.text() == "  a\n  b"
    press(editor, K.Key_Backtab)
    assert editor.text() == "a\nb"


def test_word_wrap_toggles_the_wrap_mode(editor) -> None:
    editor.apply_settings(EditorSettings(word_wrap=True))
    assert editor.lineWrapMode() == QPlainTextEdit.LineWrapMode.WidgetWidth
    editor.apply_settings(EditorSettings(word_wrap=False))
    assert editor.lineWrapMode() == QPlainTextEdit.LineWrapMode.NoWrap


def test_the_gutter_can_be_hidden_and_shown(editor) -> None:
    editor.show()
    editor.apply_settings(EditorSettings(line_numbers=False))
    assert editor.gutter_width() == 0 and editor.viewportMargins().left() == 0
    assert not editor._gutter.isVisible() and editor._gutter.width() == 0
    editor.apply_settings(EditorSettings(line_numbers=True))
    assert editor.gutter_width() > 0 and editor.viewportMargins().left() == editor.gutter_width()
    assert editor._gutter.isVisible() and editor._gutter.width() == editor.gutter_width()
    editor.hide()


def tinted(widget, token: str) -> list:
    return [
        s
        for s in widget.extraSelections()
        if s.format.property(QTextFormat.Property.FullWidthSelection)
        and s.format.background().color() == theme.qcolor(token)
    ]


def test_the_current_line_tint_can_be_switched_off(editor) -> None:
    editor.set_text("a\nb\nc")
    assert len(tinted(editor, theme.THEME.code_line)) == 1
    editor.apply_settings(EditorSettings(highlight_line=False))
    assert tinted(editor, theme.THEME.code_line) == []
    editor.set_error_line(2)  # the error line is not the current-line tint
    assert len(tinted(editor, theme.THEME.code_error_line)) == 1
    editor.apply_settings(EditorSettings(highlight_line=True))
    assert len(tinted(editor, theme.THEME.code_line)) == 1


def test_visible_whitespace_is_a_text_option_flag(editor) -> None:
    flag = QTextOption.Flag.ShowTabsAndSpaces
    assert not editor.document().defaultTextOption().flags() & flag
    editor.apply_settings(EditorSettings(show_whitespace=True))
    assert editor.document().defaultTextOption().flags() & flag
    editor.apply_settings(EditorSettings(show_whitespace=False))
    assert not editor.document().defaultTextOption().flags() & flag


def test_whitespace_and_wrap_do_not_undo_each_other(editor) -> None:
    editor.apply_settings(EditorSettings(show_whitespace=True, word_wrap=True))
    option = editor.document().defaultTextOption()
    assert option.flags() & QTextOption.Flag.ShowTabsAndSpaces
    assert option.wrapMode() == QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere


def test_trimmed_text_drops_trailing_whitespace_only_when_asked(editor) -> None:
    editor.set_text("a  \n\tb\t \n   \nc")
    assert editor.trimmed_text() == editor.text()
    editor.apply_settings(EditorSettings(trim_trailing_whitespace=True))
    assert editor.trimmed_text() == "a\n\tb\n\nc"
    assert editor.text() == "a  \n\tb\t \n   \nc"  # the editor itself is untouched
    editor.set_text("x \n")
    assert editor.trimmed_text() == "x\n"  # the final newline stays


def test_apply_settings_does_not_touch_the_text_or_the_undo_history(editor) -> None:
    editor.set_text("abc")
    type_text(editor, "d")
    editor.apply_settings(EditorSettings(font_size=16, tab_width=8, word_wrap=True))
    assert editor.text() == "dabc"
    editor.undo()
    assert editor.text() == "abc"


# -- toggle comment ----------------------------------------


def test_toggle_comment_comments_and_uncomments_one_line(editor) -> None:
    editor.set_text("    x = 1")
    editor.set_cursor(6)
    editor.toggle_comment()
    assert editor.text() == "    # x = 1"
    assert editor.cursor_position() == 8  # the cursor stays on the same character
    editor.toggle_comment()
    assert editor.text() == "    x = 1" and editor.cursor_position() == 6


def test_toggle_comment_keeps_the_common_indent_and_skips_blank_lines(editor) -> None:
    editor.set_text("def f():\n    a = 1\n\n        b = 2\n")
    select_lines(editor, 1, 3)
    editor.toggle_comment()
    assert editor.text() == "def f():\n    # a = 1\n\n    #     b = 2\n"
    assert editor.textCursor().selectedText().count("#") == 2  # still selected
    editor.toggle_comment()
    assert editor.text() == "def f():\n    a = 1\n\n        b = 2\n"


def test_toggle_comment_comments_everything_if_any_line_is_not_commented(editor) -> None:
    editor.set_text("# a\nb\n#c")
    editor.selectAll()
    editor.toggle_comment()
    assert editor.text() == "# # a\n# b\n# #c"
    editor.toggle_comment()
    assert editor.text() == "# a\nb\n#c"


def test_uncomment_accepts_a_hash_without_space(editor) -> None:
    editor.set_text("#a\n  #  b")
    editor.selectAll()
    editor.toggle_comment()
    assert editor.text() == "a\n   b"


def test_toggle_comment_on_blank_lines_does_nothing(editor) -> None:
    editor.set_text("\n\n")
    editor.selectAll()
    editor.toggle_comment()
    assert editor.text() == "\n\n"
    assert not editor.document().isUndoAvailable()


def test_toggle_comment_is_one_undo_step_on_the_key(editor) -> None:
    editor.set_text("a\nb\nc")
    editor.selectAll()
    press(editor, K.Key_Slash, CTRL)
    assert editor.text() == "# a\n# b\n# c"
    editor.undo()
    assert editor.text() == "a\nb\nc"


def test_a_selection_ending_at_a_line_start_leaves_that_line_alone(editor) -> None:
    editor.set_text("a\nb\nc")
    cursor = editor.textCursor()
    cursor.setPosition(0)
    cursor.setPosition(4, cursor.MoveMode.KeepAnchor)  # "a\nb\n": ends at the start of c
    editor.setTextCursor(cursor)
    editor.toggle_comment()
    assert editor.text() == "# a\n# b\nc"


# -- duplicate ----------------------------------------


def test_duplicate_a_line_down_moves_the_cursor_to_the_copy(editor) -> None:
    editor.set_text("a\nbcd\nz")
    editor.go_to_line(2)
    editor.set_cursor(editor.cursor_position() + 2)
    press(editor, K.Key_Down, SHIFT | ALT)
    assert editor.text() == "a\nbcd\nbcd\nz"
    assert editor.current_line() == 3 and editor.textCursor().positionInBlock() == 2
    editor.undo()
    assert editor.text() == "a\nbcd\nz"


def test_duplicate_a_line_up_keeps_the_cursor_on_the_upper_copy(editor) -> None:
    editor.set_text("a\nbcd\nz")
    editor.go_to_line(2)
    press(editor, K.Key_Up, SHIFT | ALT)
    assert editor.text() == "a\nbcd\nbcd\nz"
    assert editor.current_line() == 2
    editor.undo()
    assert editor.text() == "a\nbcd\nz"


def test_duplicate_a_selection_of_lines_down_and_up(editor) -> None:
    editor.set_text("a\nb\nc")
    select_lines(editor, 0, 1)
    editor.duplicate_lines_down()
    assert editor.text() == "a\nb\na\nb\nc"
    assert editor.textCursor().selectedText() == "a\u2029b"
    assert editor.textCursor().blockNumber() == 3  # the copy is selected
    undo_all(editor)
    assert editor.text() == "a\nb\nc"
    select_lines(editor, 1, 2)
    editor.duplicate_lines_up()
    assert editor.text() == "a\nb\nc\nb\nc"
    assert editor.textCursor().selectedText() == "b\u2029c" and editor.textCursor().selectionStart() == 2
    editor.undo()
    assert editor.text() == "a\nb\nc"


def test_duplicate_the_last_line_with_no_trailing_newline(editor) -> None:
    editor.set_text("a\nb")
    editor.go_to_line(2)
    editor.duplicate_lines_down()
    assert editor.text() == "a\nb\nb"


# -- move ----------------------------------------


def test_move_a_line_down_and_up_with_the_keys(editor) -> None:
    editor.set_text("a\nbc\nd")
    editor.go_to_line(2)
    editor.set_cursor(editor.cursor_position() + 1)
    press(editor, K.Key_Down, ALT)
    assert editor.text() == "a\nd\nbc"
    assert editor.current_line() == 3 and editor.textCursor().positionInBlock() == 1
    press(editor, K.Key_Up, ALT)
    press(editor, K.Key_Up, ALT)
    assert editor.text() == "bc\na\nd" and editor.current_line() == 1


def test_moving_at_the_edges_does_nothing(editor) -> None:
    editor.set_text("a\nb")
    editor.go_to_line(1)
    editor.move_lines_up()
    assert editor.text() == "a\nb" and editor.current_line() == 1
    editor.go_to_line(2)
    editor.move_lines_down()
    assert editor.text() == "a\nb" and editor.current_line() == 2
    assert not editor.document().isUndoAvailable()


def test_move_a_block_of_lines_keeps_it_selected_and_is_one_undo(editor) -> None:
    editor.set_text("a\nb\nc\nd")
    select_lines(editor, 1, 2)
    editor.move_lines_down()
    assert editor.text() == "a\nd\nb\nc"
    assert editor.textCursor().selectedText() == "b\u2029c" and editor.textCursor().blockNumber() == 3
    editor.move_lines_up()
    editor.move_lines_up()
    assert editor.text() == "b\nc\na\nd"
    undo_all(editor)
    assert editor.text() == "a\nb\nc\nd"


def test_move_one_step_is_one_undo_step(editor) -> None:
    editor.set_text("a\nb\nc")
    select_lines(editor, 0, 1)
    press(editor, K.Key_Down, ALT)
    assert editor.text() == "c\na\nb"
    editor.undo()
    assert editor.text() == "a\nb\nc"


# -- delete and select a line ----------------------------------------


def test_delete_a_middle_line(editor) -> None:
    editor.set_text("a\nbcd\nz")
    editor.go_to_line(2)
    editor.set_cursor(editor.cursor_position() + 2)
    press(editor, K.Key_K, CTRL | SHIFT)
    assert editor.text() == "a\nz"
    assert editor.current_line() == 2
    editor.undo()
    assert editor.text() == "a\nbcd\nz"


def test_delete_the_last_line_and_the_only_line(editor) -> None:
    editor.set_text("a\nb")
    editor.go_to_line(2)
    editor.delete_lines()
    assert editor.text() == "a" and editor.current_line() == 1
    editor.delete_lines()
    assert editor.text() == "" and editor.blockCount() == 1


def test_delete_the_selected_lines(editor) -> None:
    editor.set_text("a\nb\nc\nd")
    select_lines(editor, 1, 2)
    editor.delete_lines()
    assert editor.text() == "a\nd"
    editor.undo()
    assert editor.text() == "a\nb\nc\nd"
    select_lines(editor, 2, 3)  # the last lines take the newline before them
    editor.delete_lines()
    assert editor.text() == "a\nb"


def test_select_line_takes_the_whole_line_and_then_one_more(editor) -> None:
    editor.set_text("ab\ncd\nef")
    editor.go_to_line(2)
    editor.set_cursor(editor.cursor_position() + 1)
    press(editor, K.Key_L, CTRL)
    assert editor.textCursor().selectedText() == "cd\u2029"
    press(editor, K.Key_L, CTRL)
    assert editor.textCursor().selectedText() == "cd\u2029ef"
    assert not editor.document().isUndoAvailable()  # selecting is not an edit


def test_select_line_on_a_partial_selection_across_lines(editor) -> None:
    editor.set_text("abc\ndef\nghi")
    cursor = editor.textCursor()
    cursor.setPosition(2)
    cursor.setPosition(5, cursor.MoveMode.KeepAnchor)
    editor.setTextCursor(cursor)
    editor.select_lines()
    assert editor.textCursor().selectedText() == "abc\u2029def\u2029"


# -- auto-closing --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("opener,closer", [("(", ")"), ("[", "]"), ("{", "}"), ('"', '"'), ("'", "'")])
def test_an_opener_inserts_its_pair_with_the_cursor_between(editor, opener, closer) -> None:
    editor.set_text("")
    type_text(editor, opener)
    assert editor.text() == opener + closer and editor.cursor_position() == 1


@pytest.mark.parametrize("opener,closer", [("(", ")"), ("[", "]"), ("{", "}"), ('"', '"'), ("'", "'")])
def test_typing_the_closer_steps_over_the_one_we_inserted(editor, opener, closer) -> None:
    editor.set_text("")
    type_text(editor, opener + "x" + closer)
    assert editor.text() == opener + "x" + closer and editor.cursor_position() == 3


def test_stepping_over_works_through_nested_pairs(editor) -> None:
    editor.set_text("")
    type_text(editor, 'print(f("a", [1, 2]))')
    assert editor.text() == 'print(f("a", [1, 2]))'
    assert editor.cursor_position() == len(editor.text())


def test_a_closer_the_user_typed_is_not_stepped_over(editor) -> None:
    editor.set_text("a)")
    editor.set_cursor(1)
    type_text(editor, ")")
    assert editor.text() == "a))"


def test_a_closer_we_inserted_is_only_stepped_over_once(editor) -> None:
    editor.set_text("")
    type_text(editor, "(")
    type_text(editor, ")")
    type_text(editor, ")")
    assert editor.text() == "())"


def test_backspace_between_an_empty_pair_deletes_both(editor) -> None:
    editor.set_text("")
    type_text(editor, "f(")
    press(editor, K.Key_Backspace)
    assert editor.text() == "f"
    type_text(editor, '"')
    press(editor, K.Key_Backspace)
    assert editor.text() == "f"


def test_backspace_in_a_filled_pair_deletes_one_character(editor) -> None:
    editor.set_text("")
    type_text(editor, "(x")
    press(editor, K.Key_Backspace)
    assert editor.text() == "()"
    press(editor, K.Key_Backspace)  # now it is an empty pair
    assert editor.text() == ""


def test_a_quote_after_a_word_character_is_not_paired(editor) -> None:
    editor.set_text("")
    type_text(editor, "don't")
    assert editor.text() == "don't"
    editor.set_text("")
    type_text(editor, "x1'")
    assert editor.text() == "x1'"


def test_a_string_prefix_still_pairs_the_quote(editor) -> None:
    editor.set_text("")
    type_text(editor, 'f"')
    assert editor.text() == 'f""'
    editor.set_text("")
    type_text(editor, "rb'")
    assert editor.text() == "rb''"


def test_a_triple_quote_is_typed_as_three_quotes(editor) -> None:
    editor.set_text("")
    type_text(editor, '"""')
    assert editor.text() == '"""'  # the second quote steps over, the third is not paired


def test_nothing_pairs_before_a_word_character(editor) -> None:
    editor.set_text("abc")
    editor.set_cursor(0)
    type_text(editor, "(")
    assert editor.text() == "(abc"


def test_a_pair_is_made_before_a_closer_or_a_space(editor) -> None:
    editor.set_text("f()")
    editor.set_cursor(2)
    type_text(editor, "[")
    assert editor.text() == "f([])"
    editor.set_text("a b")
    editor.set_cursor(1)
    type_text(editor, "{")
    assert editor.text() == "a{} b"


def test_typing_an_opener_over_a_selection_wraps_it(editor) -> None:
    editor.set_text("hello world")
    cursor = editor.textCursor()
    cursor.setPosition(6)
    cursor.setPosition(11, cursor.MoveMode.KeepAnchor)
    editor.setTextCursor(cursor)
    type_text(editor, "(")
    assert editor.text() == "hello (world)"
    assert editor.textCursor().selectedText() == "world"  # still selected, so it can be wrapped again
    type_text(editor, '"')
    assert editor.text() == 'hello ("world")'
    editor.undo()
    assert editor.text() == "hello (world)"
    editor.undo()
    assert editor.text() == "hello world"


def test_wrapping_a_multi_line_selection(editor) -> None:
    editor.set_text("a\nb")
    editor.selectAll()
    type_text(editor, "[")
    assert editor.text() == "[a\nb]"
    assert editor.textCursor().selectedText() == "a\u2029b"


def test_auto_closing_can_be_switched_off(editor) -> None:
    editor.apply_settings(EditorSettings(auto_close_brackets=False))
    editor.set_text("")
    type_text(editor, "(")
    assert editor.text() == "("
    type_text(editor, ")")
    press(editor, K.Key_Backspace)
    assert editor.text() == "("
    editor.set_text("word")
    editor.selectAll()
    type_text(editor, "(")
    assert editor.text() == "("  # a typed key replaces the selection as in any editor


def test_set_text_forgets_the_remembered_closers(editor) -> None:
    editor.set_text("")
    type_text(editor, "(")
    editor.set_text("()")
    editor.set_cursor(1)
    type_text(editor, ")")
    assert editor.text() == "())"


def test_pairs_do_not_break_new_lines_and_indentation(editor) -> None:
    editor.set_text("")
    type_text(editor, "def f(a):")
    press(editor, K.Key_Return)
    type_text(editor, "return [a]")
    assert editor.text() == "def f(a):\n    return [a]"


# -- zoom ----------------------------------------


def test_zoom_keys_change_the_font_and_report_the_new_size(editor) -> None:
    sizes = []
    editor.zoomChanged.connect(sizes.append)
    press(editor, K.Key_Equal, CTRL)
    press(editor, K.Key_Plus, CTRL | SHIFT)
    assert editor.settings.font_size == 12 and abs(editor.font().pointSize() - 12) <= 1
    press(editor, K.Key_Minus, CTRL)
    assert editor.settings.font_size == 11
    press(editor, K.Key_0, CTRL)
    assert editor.settings.font_size == 10
    assert sizes == [11, 12, 11, 10]


def test_zoom_stops_at_the_limits_without_emitting(editor) -> None:
    sizes = []
    editor.zoomChanged.connect(sizes.append)
    editor.apply_settings(EditorSettings(font_size=32))
    editor.zoom_in()
    assert sizes == [] and editor.font().pointSize() == 32
    editor.apply_settings(EditorSettings(font_size=7))
    editor.zoom_out()
    assert sizes == [] and editor.font().pointSize() == 7
    editor.zoom_reset()
    assert sizes == [10]


def test_apply_settings_does_not_emit_zoom_changed(editor) -> None:
    sizes = []
    editor.zoomChanged.connect(sizes.append)
    editor.apply_settings(EditorSettings(font_size=18))
    assert sizes == []


def test_ctrl_wheel_zooms_and_a_plain_wheel_scrolls(editor) -> None:
    sizes = []
    editor.zoomChanged.connect(sizes.append)

    def wheel(delta: int, mods):
        return QWheelEvent(
            QPointF(10, 10),
            QPointF(10, 10),
            QPoint(0, 0),
            QPoint(0, delta),
            Qt.MouseButton.NoButton,
            mods,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )

    editor.wheelEvent(wheel(120, CTRL))
    editor.wheelEvent(wheel(120, CTRL))
    editor.wheelEvent(wheel(-120, CTRL))
    assert sizes == [11, 12, 11]
    editor.set_text("\n".join(str(i) for i in range(200)))
    editor.wheelEvent(wheel(-120, Qt.KeyboardModifier.NoModifier))
    assert sizes == [11, 12, 11]  # no zoom without Ctrl


def test_zoom_keeps_the_other_settings(editor) -> None:
    editor.apply_settings(EditorSettings(tab_width=2, word_wrap=True, show_whitespace=True))
    editor.zoom_in()
    assert editor.settings == EditorSettings(font_size=11, tab_width=2, word_wrap=True, show_whitespace=True)
    assert editor.tabStopDistance() == pytest.approx(2 * editor.fontMetrics().horizontalAdvance(" "))


# -- unchanged behaviour ----------------------------------------


def test_ctrl_enter_still_asks_to_run_and_does_not_edit(editor) -> None:
    asked = []
    editor.runRequested.connect(lambda: asked.append(1))
    editor.set_text("a")
    press(editor, K.Key_Return, CTRL)
    assert asked == [1] and editor.text() == "a"


# -- names while typing (P13.6) -----------------------------------------------------------------


def test_typing_a_name_opens_suggestions_and_enter_takes_the_choice(editor) -> None:
    editor.setPlainText("")
    editor.show()
    QTest.keyClicks(editor, "Circ")
    assert editor._completer.popup().isVisible()
    QTest.keyClick(editor._completer.popup(), K.Key_Enter)
    assert editor.text().startswith("Circle")


def test_escape_closes_the_suggestions_without_changing_the_text(editor) -> None:
    editor.setPlainText("")
    editor.show()
    QTest.keyClicks(editor, "Circ")
    assert editor._completer.popup().isVisible()
    QTest.keyClick(editor._completer.popup(), K.Key_Escape)
    assert not editor._completer.popup().isVisible() and editor.text() == "Circ"


def test_suggestions_can_be_turned_off(editor) -> None:
    editor.apply_settings(EditorSettings(suggest_names=False))
    editor.setPlainText("")
    QTest.keyClicks(editor, "Circ")
    assert not editor._completer.popup().isVisible()


def test_a_dot_after_a_known_object_suggests_its_methods(editor) -> None:
    editor.setPlainText("c = Circle()\nc")
    editor.show()
    editor.moveCursor(editor.textCursor().MoveOperation.End)
    QTest.keyClicks(editor, ".mov")
    assert "move_to" in editor._names.stringList()
