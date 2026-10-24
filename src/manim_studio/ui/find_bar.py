"""Find and replace for the code editor (P12), a compact bar like a code editor's.

``FindBar(editor)`` sits above (or below) a ``CodeEditor``, hidden until ``open()``: a find
field, an optional replace field, Previous / Next, the toggles Match case / Whole word /
Regex, an "N of M" counter and Replace / Replace all. All matches are drawn in the editor
(``CodeEditor.set_search_highlights``) as you type and as the text changes; the one in
focus has its own tint. An invalid regular expression only marks the field, it never raises.
The page owns the shortcuts (Ctrl+F, Ctrl+H, F3, Shift+F3): it calls ``open``, ``find_next``
and ``find_previous``.

``find_matches`` is the search itself, a plain function over a string.
"""

from __future__ import annotations

import re

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QKeyEvent, QTextCursor
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QToolButton, QVBoxLayout, QWidget

from . import icons, theme
from .code_editor import CodeEditor

Match = tuple[int, int, "re.Match[str]"]  # start and length in document positions, and the regex match


def compile_pattern(
    query: str, *, case: bool = False, word: bool = False, regex: bool = False
) -> re.Pattern[str]:
    """The pattern for ``query`` (re.error for a bad regular expression)."""
    source = query if regex else re.escape(query)
    if word:
        source = rf"(?<!\w)(?:{source})(?!\w)"
    return re.compile(source, re.MULTILINE | (0 if case else re.IGNORECASE))


def _utf16_positions(text: str) -> list[int] | None:
    """Document positions count UTF-16 units: the offset of every character, or None when each
    character is one unit (the usual case)."""
    if all(ord(c) <= 0xFFFF for c in text):
        return None
    positions, at = [], 0
    for c in text:
        positions.append(at)
        at += 2 if ord(c) > 0xFFFF else 1
    positions.append(at)
    return positions


def find_matches(
    text: str, query: str, *, case: bool = False, word: bool = False, regex: bool = False
) -> list[Match]:
    """Every non-empty match of ``query`` in ``text`` as ``(start, length, match)`` in document
    positions, in order. An empty query finds nothing; a bad regex raises ``re.error``."""
    if not query:
        return []
    pattern = compile_pattern(query, case=case, word=word, regex=regex)
    positions = _utf16_positions(text)
    found = []
    for match in pattern.finditer(text):
        if match.end() == match.start():
            continue
        if positions is None:
            found.append((match.start(), match.end() - match.start(), match))
        else:
            start = positions[match.start()]
            found.append((start, positions[match.end()] - start, match))
    return found


class FindBar(QWidget):
    closed = Signal()

    def __init__(self, editor: CodeEditor, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("findBar")
        self.editor = editor
        self._matches: list[Match] = []
        self._invalid = False
        self.find_edit = QLineEdit()
        self.find_edit.setPlaceholderText("Find")
        self.find_edit.setClearButtonEnabled(True)
        self.replace_edit = QLineEdit()
        self.replace_edit.setPlaceholderText("Replace")
        self.counter = QLabel()
        self.counter.setMinimumWidth(72)
        self.counter.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.previous_button = self._button("Previous match (Shift+F3)", icon="move-up")
        self.next_button = self._button("Next match (F3)", icon="move-down")
        self.case_button = self._button("Match case", text="Aa", checkable=True)
        self.word_button = self._button("Whole word", text="ab", checkable=True)
        self.regex_button = self._button("Regular expression", text=".*", checkable=True)
        self.close_button = self._button("Close (Escape)", icon="close")
        self.replace_button = self._button("Replace the current match", text="Replace")
        self.replace_all_button = self._button("Replace every match", text="Replace all")
        for name, button in (
            ("findPrevious", self.previous_button),
            ("findNext", self.next_button),
            ("findCase", self.case_button),
            ("findWord", self.word_button),
            ("findRegex", self.regex_button),
            ("findClose", self.close_button),
            ("findReplace", self.replace_button),
            ("findReplaceAll", self.replace_all_button),
        ):
            button.setObjectName(name)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        for widget in (
            self.find_edit,
            self.counter,
            self.previous_button,
            self.next_button,
            self.case_button,
            self.word_button,
            self.regex_button,
            self.close_button,
        ):
            row.addWidget(widget, 1 if widget is self.find_edit else 0)
        self.replace_row = QWidget()
        replace = QHBoxLayout(self.replace_row)
        replace.setContentsMargins(0, 0, 0, 0)
        replace.addWidget(self.replace_edit, 1)
        replace.addWidget(self.replace_button)
        replace.addWidget(self.replace_all_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        layout.addLayout(row)
        layout.addWidget(self.replace_row)

        self.find_edit.textChanged.connect(self._query_changed)
        for button in (self.case_button, self.word_button, self.regex_button):
            button.toggled.connect(self._query_changed)
        self.previous_button.clicked.connect(self.find_previous)
        self.next_button.clicked.connect(self.find_next)
        self.replace_button.clicked.connect(self.replace_current)
        self.replace_all_button.clicked.connect(self.replace_all)
        self.close_button.clicked.connect(self.close_bar)
        self.find_edit.installEventFilter(self)
        self.replace_edit.installEventFilter(self)
        editor.textChanged.connect(self._text_changed)
        editor.cursorPositionChanged.connect(self._update_current)
        self.replace_row.hide()
        self.hide()
        self._show_counter()

    def _button(self, tip: str, *, text: str = "", icon: str = "", checkable: bool = False) -> QToolButton:
        button = QToolButton()
        button.setToolTip(tip)
        button.setAccessibleName(tip)
        button.setCheckable(checkable)
        button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        if icon:
            button.setIcon(icons.icon(icon))
        else:
            button.setText(text)
        return button

    # -- opening and closing ----------------------------------------------------------------

    @property
    def is_open(self) -> bool:
        return not self.isHidden()

    def open(self, replace: bool = False) -> None:
        """Show the bar (with the replace row when ``replace``), seed the find field with the selected
        text if it is on one line, and focus the find field."""
        self.show()
        self.replace_row.setVisible(replace or not self.replace_row.isHidden())
        selected = self.editor.textCursor().selectedText()
        if selected and " " not in selected:
            self.find_edit.setText(selected)
        self._recompute()
        self.find_edit.setFocus()
        self.find_edit.selectAll()

    def show_replace(self) -> None:
        """Show the replace row (and the bar, if it is closed)."""
        if self.is_open:
            self.replace_row.show()
        else:
            self.open(replace=True)

    def close_bar(self) -> None:
        """Hide the bar, clear the highlights and give the focus back to the editor."""
        self.hide()
        self.editor.set_search_highlights([], None)
        self.editor.setFocus()
        self.closed.emit()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.KeyPress and isinstance(event, QKeyEvent):
            key, shift = event.key(), bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            if key == Qt.Key.Key_Escape:
                self.close_bar()
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if watched is self.replace_edit:
                    self.replace_current()
                elif shift:
                    self.find_previous()
                else:
                    self.find_next()
                return True
        return super().eventFilter(watched, event)

    # -- the search --------------------------------------------------------------------------

    @property
    def query(self) -> str:
        return self.find_edit.text()

    def match_count(self) -> int:
        return len(self._matches)

    def current_match(self) -> int | None:
        """The index of the match the editor's selection is on, None when it is on none."""
        cursor = self.editor.textCursor()
        span = (cursor.selectionStart(), cursor.selectionEnd() - cursor.selectionStart())
        if not cursor.hasSelection():
            return None
        for index, (start, length, _match) in enumerate(self._matches):
            if (start, length) == span:
                return index
        return None

    def _recompute(self) -> None:
        """Search the editor's text again (the query, an option or the text changed)."""
        self._matches = []
        message = ""
        try:
            self._matches = find_matches(
                self.editor.toPlainText(),
                self.query,
                case=self.case_button.isChecked(),
                word=self.word_button.isChecked(),
                regex=self.regex_button.isChecked(),
            )
        except re.error as error:
            message = f"Invalid regular expression: {error}"
        self._set_invalid(self.find_edit, bool(message), message)
        self._update_current()

    def _query_changed(self, *_args) -> None:
        """Find as you type: search again and select the first match from the cursor on."""
        self._recompute()
        if self._matches and self.is_open:
            self._select(self._first_from(self.editor.textCursor().selectionStart()))

    def _text_changed(self) -> None:
        if self.is_open:
            self._recompute()

    def _update_current(self) -> None:
        if not self.is_open:
            return
        self.editor.set_search_highlights([(s, n) for s, n, _m in self._matches], self.current_match())
        self._show_counter()

    def _show_counter(self) -> None:
        if not self.query:
            text = ""
        elif self._invalid:
            text = "Invalid"
        elif not self._matches:
            text = "No results"
        else:
            current = self.current_match()
            text = f"{'?' if current is None else current + 1} of {len(self._matches)}"
        self.counter.setText(text)

    def _set_invalid(self, field: QLineEdit, invalid: bool, tip: str = "") -> None:
        if field is self.find_edit:
            self._invalid = invalid
        field.setProperty("invalid", invalid)
        field.setToolTip(tip)
        field.setStyleSheet(f"QLineEdit {{ border: 1px solid {theme.THEME.danger}; }}" if invalid else "")

    def _first_from(self, position: int) -> int:
        """The index of the first match starting at or after ``position`` (the first one if none)."""
        for index, (start, _length, _match) in enumerate(self._matches):
            if start >= position:
                return index
        return 0

    def _select(self, index: int) -> None:
        start, length, _match = self._matches[index]
        cursor = QTextCursor(self.editor.document())
        cursor.setPosition(start)
        cursor.setPosition(start + length, QTextCursor.MoveMode.KeepAnchor)
        self.editor.setTextCursor(cursor)
        self.editor.ensureCursorVisible()

    def find_next(self) -> bool:
        """Select the next match after the selection (or the cursor), wrapping to the first.
        False when there is none."""
        self._recompute()
        if not self._matches:
            return False
        cursor = self.editor.textCursor()
        self._select(self._first_from(cursor.selectionEnd() if cursor.hasSelection() else cursor.position()))
        return True

    def find_previous(self) -> bool:
        """Select the match before the selection (or the cursor), wrapping to the last."""
        self._recompute()
        if not self._matches:
            return False
        before = self.editor.textCursor().selectionStart()
        earlier = [i for i, (start, _n, _m) in enumerate(self._matches) if start < before]
        self._select(earlier[-1] if earlier else len(self._matches) - 1)
        return True

    # -- replacing ---------------------------------------------------------------------------

    def _replacement(self, match: re.Match[str]) -> str | None:
        """The text that replaces ``match`` (group references expand in regex mode); None for a bad one."""
        text = self.replace_edit.text()
        if not self.regex_button.isChecked():
            return text
        try:
            return match.expand(text)
        except (re.error, IndexError) as error:
            self._set_invalid(self.replace_edit, True, f"Invalid replacement: {error}")
            return None

    def replace_current(self) -> bool:
        """Replace the selected match and select the next one; when the selection is not on a match,
        just go to the next. False when nothing was replaced."""
        self._recompute()
        index = self.current_match()
        if index is None:
            self.find_next()
            return False
        start, length, match = self._matches[index]
        replacement = self._replacement(match)
        if replacement is None:
            return False
        self._set_invalid(self.replace_edit, False)
        cursor = QTextCursor(self.editor.document())
        cursor.setPosition(start)
        cursor.setPosition(start + length, QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(replacement)  # the cursor is now after it, the next search starts there
        self.editor.setTextCursor(cursor)
        self.find_next()
        return True

    def replace_all(self) -> int:
        """Replace every match, as one step of the editor's undo; returns how many."""
        self._recompute()
        if not self._matches:
            return 0
        replacements = [self._replacement(match) for _s, _n, match in self._matches]
        if any(r is None for r in replacements):
            return 0
        self._set_invalid(self.replace_edit, False)
        edit = QTextCursor(self.editor.document())
        edit.beginEditBlock()
        for (start, length, _match), text in reversed(list(zip(self._matches, replacements, strict=True))):
            edit.setPosition(start)
            edit.setPosition(start + length, QTextCursor.MoveMode.KeepAnchor)
            edit.insertText(text)
        edit.endEditBlock()
        self.editor.setTextCursor(edit)
        return len(replacements)
