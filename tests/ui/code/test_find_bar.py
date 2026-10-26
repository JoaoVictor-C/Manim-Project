"""The find / replace bar of the code editor (P12): counts, match case / whole word / regex,
wrap-around, replace and replace all (one undo step), an invalid regex, the editor's highlights
composing with the current-line and error-line tints, and the keys. Offscreen."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextFormat
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QVBoxLayout, QWidget

from manim_studio.ui.code.code_editor import CodeEditor
from manim_studio.ui.code.find_bar import FindBar, find_matches
from manim_studio.ui.style import theme

pytestmark = pytest.mark.ui

T = theme.THEME
TEXT = "Cat cat\nconcat CAT\nthe cat sat"


@pytest.fixture
def parts(qt_app):
    """A window holding the bar over the editor, shown (focus needs it)."""
    window = QWidget()
    editor = CodeEditor()
    bar = FindBar(editor)
    layout = QVBoxLayout(window)
    layout.addWidget(bar)
    layout.addWidget(editor)
    window.resize(700, 400)
    window.show()
    window.activateWindow()
    QTest.qWaitForWindowActive(window)
    editor.set_text(TEXT)
    yield editor, bar
    window.close()


def search(bar: FindBar, query: str, *, case=False, word=False, regex=False) -> None:
    bar.open()
    bar.case_button.setChecked(case)
    bar.word_button.setChecked(word)
    bar.regex_button.setChecked(regex)
    bar.find_edit.setText(query)


def spans(editor: CodeEditor, token: str) -> list[tuple[int, int]]:
    """The (start, length) of the extra selections drawn with the theme's ``token``."""
    colour = theme.qcolor(token)
    return [
        (s.cursor.selectionStart(), s.cursor.selectionEnd() - s.cursor.selectionStart())
        for s in editor.extraSelections()
        if s.format.background().color() == colour
        and not s.format.property(QTextFormat.Property.FullWidthSelection)
    ]


def selected(editor: CodeEditor) -> tuple[int, int]:
    cursor = editor.textCursor()
    return cursor.selectionStart(), cursor.selectionEnd() - cursor.selectionStart()


# -- the search function ----------------------------------------


def test_find_matches_is_case_insensitive_by_default() -> None:
    assert [(s, n) for s, n, _m in find_matches(TEXT, "cat")] == [(0, 3), (4, 3), (11, 3), (15, 3), (23, 3)]
    assert [(s, n) for s, n, _m in find_matches(TEXT, "cat", case=True)] == [(4, 3), (11, 3), (23, 3)]


def test_find_matches_whole_word_and_regex() -> None:
    assert [s for s, _n, _m in find_matches(TEXT, "cat", word=True)] == [0, 4, 15, 23]
    assert [m.group() for _s, _n, m in find_matches("a1 b22 c", r"\d+", regex=True)] == ["1", "22"]
    assert find_matches("a.b axb", "a.b") != find_matches("a.b axb", "a.b", regex=True)
    assert len(find_matches("a.b axb", "a.b")) == 1 and len(find_matches("a.b axb", "a.b", regex=True)) == 2


def test_find_matches_skips_empty_matches_and_an_empty_query() -> None:
    assert find_matches("abc", "") == []
    assert [(s, n) for s, n, _m in find_matches("aab", "a*", regex=True)] == [(0, 2)]
    assert find_matches("abc", "x*", regex=True) == []


def test_find_matches_positions_count_utf16_units() -> None:
    text = "\U0001f600 a\nb a"  # an emoji is two units in a QTextDocument
    assert [(s, n) for s, n, _m in find_matches(text, "a")] == [(3, 1), (7, 1)]


def test_find_matches_with_a_bad_regex_raises_re_error() -> None:
    import re

    with pytest.raises(re.error):
        find_matches("x", "(", regex=True)


# -- the bar ----------------------------------------


def test_the_bar_is_hidden_until_opened_and_has_the_parts(parts) -> None:
    editor, bar = parts
    other = FindBar(editor)
    assert other.isHidden() and not other.is_open
    assert not bar.is_open
    bar.open()
    assert bar.is_open and bar.replace_row.isHidden()
    bar.show_replace()
    assert not bar.replace_row.isHidden()
    for button in (bar.case_button, bar.word_button, bar.regex_button):
        assert button.isCheckable() and button.toolTip()
    for button in (bar.previous_button, bar.next_button, bar.close_button, bar.replace_button):
        assert button.toolTip()


def test_open_with_replace_shows_the_replace_row(parts) -> None:
    _editor, bar = parts
    bar.open(replace=True)
    assert not bar.replace_row.isHidden()
    bar.close_bar()
    assert bar.isHidden()
    bar.open()
    assert bar.is_open


def test_open_seeds_the_find_field_with_a_one_line_selection_and_focuses_it(parts) -> None:
    editor, bar = parts
    cursor = editor.textCursor()
    cursor.setPosition(4)
    cursor.setPosition(7, cursor.MoveMode.KeepAnchor)
    editor.setTextCursor(cursor)
    bar.open()
    assert bar.query == "cat"
    assert bar.find_edit.hasFocus()
    assert bar.find_edit.selectedText() == "cat"


def test_open_with_a_multi_line_selection_keeps_the_old_query(parts) -> None:
    editor, bar = parts
    search(bar, "sat")
    editor.selectAll()
    bar.open()
    assert bar.query == "sat"


def test_open_with_no_selection_keeps_the_last_query(parts) -> None:
    editor, bar = parts
    search(bar, "cat")
    bar.close_bar()
    editor.set_cursor(3)  # the match found is no longer selected
    bar.open()
    assert bar.query == "cat"


def test_counter_counts_as_you_type(parts) -> None:
    editor, bar = parts
    search(bar, "")
    assert bar.counter.text() == "" and bar.match_count() == 0
    bar.find_edit.setText("c")
    assert bar.match_count() == 6  # Cat, cat, the two c of concat, CAT, cat
    bar.find_edit.setText("cat")
    assert bar.match_count() == 5
    assert bar.counter.text() == "1 of 5"
    bar.find_edit.setText("zzz")
    assert bar.counter.text() == "No results"
    assert spans(editor, T.search_match) == [] and spans(editor, T.search_current) == []


def test_typing_selects_the_first_match_from_the_cursor_and_draws_all(parts) -> None:
    editor, bar = parts
    editor.set_cursor(8)  # start of line 2
    search(bar, "cat")
    assert selected(editor) == (11, 3)  # "concat"'s cat
    assert bar.counter.text() == "3 of 5"
    assert spans(editor, T.search_current) == [(11, 3)]
    assert sorted(spans(editor, T.search_match)) == [(0, 3), (4, 3), (15, 3), (23, 3)]


def test_options_change_the_count(parts) -> None:
    _editor, bar = parts
    search(bar, "cat")
    assert bar.match_count() == 5
    bar.case_button.setChecked(True)
    assert bar.match_count() == 3 and bar.counter.text().endswith("of 3")
    bar.case_button.setChecked(False)
    bar.word_button.setChecked(True)
    assert bar.match_count() == 4  # not the one inside "concat"
    bar.word_button.setChecked(False)
    bar.find_edit.setText(r"c.t")
    assert bar.match_count() == 0
    bar.regex_button.setChecked(True)
    assert bar.match_count() == 5


def test_case_and_word_together(parts) -> None:
    _editor, bar = parts
    search(bar, "cat", case=True, word=True)
    assert bar.match_count() == 2  # "cat" in line 1 and in line 3


def test_regex_special_characters_are_literal_without_the_regex_toggle(parts) -> None:
    editor, bar = parts
    editor.set_text("f(x) + f(y)")
    search(bar, "f(")
    assert bar.match_count() == 2 and bar.counter.text() != "Invalid"


def test_find_next_goes_forward_and_wraps_around(parts) -> None:
    editor, bar = parts
    editor.set_cursor(0)
    search(bar, "cat", case=True)  # three matches: 4, 11, 23
    assert selected(editor) == (4, 3)
    assert bar.find_next() and selected(editor) == (11, 3)
    assert bar.find_next() and selected(editor) == (23, 3)
    assert bar.find_next() and selected(editor) == (4, 3)  # wrapped
    assert bar.counter.text() == "1 of 3"


def test_find_previous_goes_back_and_wraps_around(parts) -> None:
    editor, bar = parts
    editor.set_cursor(0)
    search(bar, "cat", case=True)
    assert bar.find_previous() and selected(editor) == (23, 3)  # wrapped to the last
    assert bar.find_previous() and selected(editor) == (11, 3)
    assert bar.find_previous() and selected(editor) == (4, 3)
    assert bar.counter.text() == "1 of 3"


def test_find_next_and_previous_without_matches_return_false(parts) -> None:
    editor, bar = parts
    search(bar, "zzz")
    editor.set_cursor(5)
    assert bar.find_next() is False and bar.find_previous() is False
    assert editor.cursor_position() == 5


def test_next_and_previous_buttons(parts) -> None:
    editor, bar = parts
    editor.set_cursor(0)
    search(bar, "sat")
    assert selected(editor) == (27, 3)
    QTest.mouseClick(bar.previous_button, Qt.MouseButton.LeftButton)
    assert selected(editor) == (27, 3)  # the only one: wraps onto itself
    editor.set_cursor(0)
    search(bar, "the")
    QTest.mouseClick(bar.next_button, Qt.MouseButton.LeftButton)
    assert selected(editor) == (19, 3)


def test_the_counter_follows_the_cursor_and_the_text(parts) -> None:
    editor, bar = parts
    editor.set_cursor(0)
    search(bar, "cat", case=True)
    assert bar.counter.text() == "1 of 3"
    editor.set_cursor(2)  # the selection is gone
    assert bar.counter.text() == "? of 3"
    editor.set_text(TEXT + "\ncat")
    assert bar.counter.text().endswith("of 4")
    cursor = editor.textCursor()
    cursor.setPosition(editor.document().characterCount() - 1)
    cursor.insertText(" cat")
    assert bar.match_count() == 5  # typing in the editor updates it live


def test_a_match_selected_by_hand_is_the_current_one(parts) -> None:
    editor, bar = parts
    search(bar, "cat", case=True)
    cursor = editor.textCursor()
    cursor.setPosition(23)
    cursor.setPosition(26, cursor.MoveMode.KeepAnchor)
    editor.setTextCursor(cursor)
    assert bar.current_match() == 2 and bar.counter.text() == "3 of 3"
    assert spans(editor, T.search_current) == [(23, 3)]


def test_matches_after_non_bmp_characters_are_selected_correctly(parts) -> None:
    editor, bar = parts
    editor.set_text("\U0001f600 cat\ncat")
    editor.set_cursor(0)
    search(bar, "cat")
    assert editor.textCursor().selectedText() == "cat"
    bar.find_next()
    assert editor.textCursor().selectedText() == "cat" and editor.textCursor().blockNumber() == 1


# -- invalid regex ----------------------------------------


def test_an_invalid_regex_marks_the_field_and_never_raises(parts) -> None:
    editor, bar = parts
    search(bar, "cat")
    bar.regex_button.setChecked(True)
    bar.find_edit.setText("(")
    assert bar.find_edit.property("invalid") is True
    assert bar.find_edit.toolTip().startswith("Invalid regular expression")
    assert theme.THEME.danger in bar.find_edit.styleSheet()
    assert bar.counter.text() == "Invalid" and bar.match_count() == 0
    assert spans(editor, T.search_match) == []
    assert bar.find_next() is False and bar.find_previous() is False
    assert bar.replace_all() == 0 and bar.replace_current() is False
    bar.find_edit.setText("c.t")  # valid again: the error state goes
    assert bar.find_edit.property("invalid") is False and bar.find_edit.styleSheet() == ""
    assert bar.match_count() == 5


def test_turning_regex_off_clears_the_error(parts) -> None:
    _editor, bar = parts
    search(bar, "[", regex=True)
    assert bar.find_edit.property("invalid") is True
    bar.regex_button.setChecked(False)
    assert bar.find_edit.property("invalid") is False
    assert bar.counter.text() == "No results"


# -- replace ----------------------------------------


def test_replace_swaps_the_current_match_and_moves_on(parts) -> None:
    editor, bar = parts
    editor.set_cursor(0)
    bar.open(replace=True)
    bar.find_edit.setText("cat")
    bar.case_button.setChecked(True)
    bar.replace_edit.setText("dog")
    assert selected(editor) == (4, 3)
    assert bar.replace_current() is True
    assert editor.text() == "Cat dog\nconcat CAT\nthe cat sat"
    assert selected(editor) == (11, 3)  # on the next one
    assert bar.counter.text() == "1 of 2"
    editor.undo()
    assert editor.text() == TEXT


def test_replace_without_a_current_match_only_goes_to_the_next(parts) -> None:
    editor, bar = parts
    editor.set_cursor(0)
    bar.open(replace=True)
    bar.case_button.setChecked(True)
    bar.find_edit.setText("cat")
    editor.set_cursor(0)  # drop the selection
    bar.replace_edit.setText("dog")
    assert bar.replace_current() is False
    assert editor.text() == TEXT and selected(editor) == (4, 3)


def test_replace_all_replaces_every_match_in_one_undo_step(parts) -> None:
    editor, bar = parts
    bar.open(replace=True)
    bar.find_edit.setText("cat")
    bar.replace_edit.setText("dog")
    assert bar.replace_all() == 5
    assert editor.text() == "dog dog\ncondog dog\nthe dog sat"
    assert bar.counter.text() == "No results"
    editor.undo()
    assert editor.text() == TEXT  # one step brings every one back


def test_replace_all_with_a_longer_and_a_shorter_text(parts) -> None:
    editor, bar = parts
    bar.open(replace=True)
    bar.find_edit.setText("cat")
    bar.case_button.setChecked(True)
    bar.replace_edit.setText("elephant")
    bar.replace_all()
    assert editor.text() == "Cat elephant\nconelephant CAT\nthe elephant sat"
    bar.find_edit.setText("elephant")
    bar.replace_edit.setText("")
    bar.replace_all()
    assert editor.text() == "Cat \ncon CAT\nthe  sat"


def test_replace_all_regex_expands_groups(parts) -> None:
    editor, bar = parts
    editor.set_text("a1 b22 c3")
    bar.open(replace=True)
    bar.regex_button.setChecked(True)
    bar.find_edit.setText(r"([a-z])(\d+)")
    bar.replace_edit.setText(r"\2\1")
    assert bar.replace_all() == 3
    assert editor.text() == "1a 22b 3c"


def test_a_plain_replace_text_keeps_backslashes_literally(parts) -> None:
    editor, bar = parts
    editor.set_text("a b")
    bar.open(replace=True)
    bar.find_edit.setText("a")
    bar.replace_edit.setText(r"\1\n")
    bar.replace_all()
    assert editor.text() == r"\1\n b"


def test_a_bad_group_reference_marks_the_replace_field_and_changes_nothing(parts) -> None:
    editor, bar = parts
    editor.set_text("abc")
    bar.open(replace=True)
    bar.regex_button.setChecked(True)
    bar.find_edit.setText("b")
    bar.replace_edit.setText(r"\9")
    assert bar.replace_all() == 0
    assert editor.text() == "abc"
    assert bar.replace_edit.property("invalid") is True
    bar.replace_edit.setText("x")
    assert bar.replace_all() == 1  # fixed: it replaces and the mark goes
    assert bar.replace_edit.property("invalid") is False and editor.text() == "axc"


def test_replace_all_buttons_work_by_click(parts) -> None:
    editor, bar = parts
    bar.open(replace=True)
    bar.find_edit.setText("sat")
    bar.replace_edit.setText("ran")
    QTest.mouseClick(bar.replace_all_button, Qt.MouseButton.LeftButton)
    assert editor.text().endswith("the cat ran")


def test_replace_all_with_no_matches_changes_nothing(parts) -> None:
    editor, bar = parts
    bar.open(replace=True)
    bar.find_edit.setText("zzz")
    assert bar.replace_all() == 0 and editor.text() == TEXT
    assert not editor.document().isUndoAvailable()


# -- the highlights compose with the other tints ----------------------------------------


def test_highlights_compose_with_the_current_line_and_the_error_line(parts) -> None:
    editor, bar = parts
    editor.set_error_line(2)
    editor.set_cursor(0)
    search(bar, "cat", case=True)
    full = [s for s in editor.extraSelections() if s.format.property(QTextFormat.Property.FullWidthSelection)]
    colours = {s.format.background().color().rgba() for s in full}
    assert len(full) == 2 and len(colours) == 2  # the line tint and the error tint are still there
    assert len(spans(editor, T.search_match)) == 2 and len(spans(editor, T.search_current)) == 1
    bar.close_bar()
    after = editor.extraSelections()
    assert len(after) == 2 and all(s.format.property(QTextFormat.Property.FullWidthSelection) for s in after)
    assert editor.error_line == 2


def test_highlights_survive_cursor_moves_and_error_changes(parts) -> None:
    editor, bar = parts
    search(bar, "cat", case=True)
    editor.set_cursor(10)
    editor.set_error_line(3)
    editor.set_error_line(None)
    assert len(spans(editor, T.search_match)) + len(spans(editor, T.search_current)) == 3


def test_the_editor_api_draws_and_clears_highlights_directly(parts) -> None:
    editor, _bar = parts
    editor.set_search_highlights([(0, 3), (4, 3)], 1)
    assert spans(editor, T.search_match) == [(0, 3)] and spans(editor, T.search_current) == [(4, 3)]
    editor.set_search_highlights([(0, 3)], None)
    assert spans(editor, T.search_current) == []
    editor.set_search_highlights([(0, 3)], 7)  # an index out of range is no current match
    assert spans(editor, T.search_current) == [] and spans(editor, T.search_match) == [(0, 3)]
    editor.set_search_highlights([(0, 0), (-1, 2), (500, 4)], None)  # empty or outside: ignored
    assert spans(editor, T.search_match) == []
    editor.set_search_highlights([], None)
    assert all(s.format.property(QTextFormat.Property.FullWidthSelection) for s in editor.extraSelections())


def test_the_search_tints_are_theme_tokens() -> None:
    for token in ("search_match", "search_current"):
        assert token in theme.token_names()
        assert theme.qcolor(getattr(T, token)).isValid()


# -- closing and the keys ----------------------------------------


def test_escape_closes_the_bar_clears_the_highlights_and_focuses_the_editor(parts) -> None:
    editor, bar = parts
    closed = []
    bar.closed.connect(lambda: closed.append(1))
    search(bar, "cat")
    assert spans(editor, T.search_match)
    QTest.keyClick(bar.find_edit, Qt.Key.Key_Escape)
    assert bar.isHidden() and not bar.is_open and closed == [1]
    assert spans(editor, T.search_match) == [] and spans(editor, T.search_current) == []
    assert editor.hasFocus()
    editor.set_text("cat cat")  # a closed bar no longer follows the text
    assert spans(editor, T.search_match) == []


def test_escape_in_the_replace_field_and_the_close_button_close_it_too(parts) -> None:
    editor, bar = parts
    bar.open(replace=True)
    QTest.keyClick(bar.replace_edit, Qt.Key.Key_Escape)
    assert bar.isHidden() and editor.hasFocus()
    bar.open()
    QTest.mouseClick(bar.close_button, Qt.MouseButton.LeftButton)
    assert bar.isHidden() and editor.hasFocus()


def test_enter_finds_next_and_shift_enter_finds_previous(parts) -> None:
    editor, bar = parts
    editor.set_cursor(0)
    search(bar, "cat", case=True)
    assert selected(editor) == (4, 3)
    QTest.keyClick(bar.find_edit, Qt.Key.Key_Return)
    assert selected(editor) == (11, 3)
    QTest.keyClick(bar.find_edit, Qt.Key.Key_Return)
    assert selected(editor) == (23, 3)
    QTest.keyClick(bar.find_edit, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert selected(editor) == (11, 3)


def test_enter_in_the_replace_field_replaces_the_current_match(parts) -> None:
    editor, bar = parts
    editor.set_cursor(0)
    bar.open(replace=True)
    bar.case_button.setChecked(True)
    bar.find_edit.setText("cat")
    bar.replace_edit.setText("x")
    QTest.keyClick(bar.replace_edit, Qt.Key.Key_Return)
    assert editor.text() == "Cat x\nconcat CAT\nthe cat sat"


def test_typing_in_the_find_field_does_not_take_the_focus_from_it(parts) -> None:
    _editor, bar = parts
    bar.open()
    QTest.keyClicks(bar.find_edit, "cat")
    assert bar.find_edit.hasFocus() and bar.query == "cat" and bar.match_count() == 5
