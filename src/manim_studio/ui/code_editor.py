"""The code editor of the Code page (P6b.3, ADR 0041).

A ``QPlainTextEdit`` for Python: the theme's monospace font, a line number gutter,
the current line (and the line a render error points at) tinted, Python highlighting
from ``code_syntax``, auto-indent (a new line keeps the indent and adds four spaces
after a colon), Tab as one indent (four spaces by default, indenting a selection's lines),
Shift+Tab dedenting, Backspace removing a whole indent, and Ctrl+Enter asking to run.

P12 makes it behave like a code editor: ``apply_settings`` takes an ``EditorSettings`` live
(font size, tab width, wrapping, gutter, current-line tint, visible whitespace, auto-closing
brackets and quotes), the usual line commands exist as methods and keys (toggle comment,
duplicate, move, delete and select line, zoom), and ``set_search_highlights`` draws the find
bar's matches. Every multi-line edit is one step of the editor's own undo. All colours come
from the theme's tokens.
"""

from __future__ import annotations

import re
from dataclasses import replace

from PySide6.QtCore import QEvent, QRect, QSize, QStringListModel, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QKeyEvent,
    QPainter,
    QSyntaxHighlighter,
    QTextBlock,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextFormat,
    QTextOption,
    QWheelEvent,
)
from PySide6.QtWidgets import QCompleter, QPlainTextEdit, QTextEdit, QToolTip, QWidget

from ..core import completion, snippets
from . import theme
from .code_drafts import clamp_line
from .code_syntax import NORMAL, scan_line
from .editor_settings import MAX_FONT_SIZE, MIN_FONT_SIZE, EditorSettings, clamp

INDENT = " " * 4
CODE_POINT_SIZE = 10
MAX_HIGHLIGHTS = 5000  # find matches drawn at most (the counter still counts them all)
PAIRS = {"(": ")", "[": "]", "{": "}", '"': '"', "'": "'"}
CLOSERS = frozenset(PAIRS.values())
STRING_PREFIXES = frozenset({"r", "b", "f", "u", "rb", "br", "fr", "rf"})  # f"..." still pairs
BEFORE_CLOSER = frozenset(")]},:;.")  # a bracket pairs when the next character is one of these or blank
MAX_TRACKED = 200  # auto-inserted closers remembered


class PythonHighlighter(QSyntaxHighlighter):
    """Colours a document line by line with ``code_syntax.scan_line`` (the state is the block state)."""

    def __init__(self, document: QTextDocument) -> None:
        super().__init__(document)
        colours = theme.THEME
        self.formats: dict[str, QTextCharFormat] = {}
        for kind, token in (
            ("keyword", colours.syntax_keyword),
            ("string", colours.syntax_string),
            ("number", colours.syntax_number),
            ("comment", colours.syntax_comment),
            ("manim", colours.syntax_manim),
            ("definition", colours.syntax_definition),
        ):
            fmt = QTextCharFormat()
            fmt.setForeground(theme.qcolor(token))
            if kind == "comment":
                fmt.setFontItalic(True)
            self.formats[kind] = fmt

    def highlightBlock(self, text: str) -> None:
        state = max(self.previousBlockState(), NORMAL)
        spans, state = scan_line(text, state)
        for start, length, kind in spans:
            self.setFormat(start, length, self.formats[kind])
        self.setCurrentBlockState(state)


class _Gutter(QWidget):
    def __init__(self, editor: CodeEditor) -> None:
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self.editor.gutter_width(), 0)

    def paintEvent(self, event) -> None:
        self.editor.paint_gutter(event.rect())


class CodeEditor(QPlainTextEdit):
    runRequested = Signal()  # Ctrl+Enter
    zoomChanged = Signal(int)  # the new font size after Ctrl+= / Ctrl+- / Ctrl+0 / Ctrl+wheel

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("codeEditor")
        self.indent = INDENT  # one level of indent: ``tab_width`` spaces
        self._settings = EditorSettings(font_size=CODE_POINT_SIZE)
        self.highlighter = PythonHighlighter(self.document())
        self._gutter = _Gutter(self)
        self._error_line: int | None = None
        self._names = QStringListModel(self)
        self._completer = QCompleter(self._names, self)  # the names offered while typing (P13.6)
        self._completer.setWidget(self)
        self._completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer.activated[str].connect(self._complete_with)
        self._snippet_stops: list[tuple[QTextCursor, QTextCursor]] = []  # places Tab still visits
        self._syntax: tuple[int, int, int, int] | None = None  # line, column, end line, end column
        self._search_selections: list[QTextEdit.ExtraSelection] = []
        self._auto_closers: list[QTextCursor] = []  # before each closer the editor typed itself
        self.blockCountChanged.connect(self._update_margin)
        self.updateRequest.connect(self._update_gutter)
        self.cursorPositionChanged.connect(self._update_selections)
        self.apply_settings(self._settings)

    # -- settings --------------------------------------------------------------------------

    @property
    def settings(self) -> EditorSettings:
        """The settings in force (zooming changes the font size in them)."""
        return self._settings

    def apply_settings(self, settings: EditorSettings) -> None:
        """Take ``settings`` (clamped) live: font, tab stops and indent, wrapping, gutter, line tint,
        visible whitespace and auto-closing. Never emits ``zoomChanged``."""
        settings = clamp(settings)
        self._settings = settings
        self.setFont(theme.mono_font(settings.font_size))
        self.indent = " " * settings.tab_width
        self.setTabStopDistance(settings.tab_width * self.fontMetrics().horizontalAdvance(" "))
        self.setLineWrapMode(
            QPlainTextEdit.LineWrapMode.WidgetWidth
            if settings.word_wrap
            else QPlainTextEdit.LineWrapMode.NoWrap
        )
        option = self.document().defaultTextOption()
        flags = option.flags()
        if settings.show_whitespace:
            flags |= QTextOption.Flag.ShowTabsAndSpaces
        else:
            flags &= ~QTextOption.Flag.ShowTabsAndSpaces
        option.setFlags(flags)
        self.document().setDefaultTextOption(option)
        self._gutter.setVisible(settings.line_numbers)
        self._update_margin()
        self._place_gutter()
        self._update_selections()
        self.viewport().update()

    def trimmed_text(self) -> str:
        """The text, with trailing spaces and tabs dropped from every line when the setting is on
        (the text as it is otherwise); the editor itself is left alone."""
        text = self.text()
        if not self._settings.trim_trailing_whitespace:
            return text
        return "\n".join(line.rstrip(" \t") for line in text.split("\n"))

    # -- zoom --------------------------------------------------------------------------------

    def zoom_in(self) -> None:
        self._zoom(self._settings.font_size + 1)

    def zoom_out(self) -> None:
        self._zoom(self._settings.font_size - 1)

    def zoom_reset(self) -> None:
        self._zoom(EditorSettings().font_size)

    def _zoom(self, size: int) -> None:
        size = max(MIN_FONT_SIZE, min(MAX_FONT_SIZE, size))
        if size != self._settings.font_size:
            self.apply_settings(replace(self._settings, font_size=size))
            self.zoomChanged.emit(size)

    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta:
                self.zoom_in() if delta > 0 else self.zoom_out()
            event.accept()
            return
        super().wheelEvent(event)

    # -- text and lines -------------------------------------------------------------

    def text(self) -> str:
        return self.toPlainText()

    def set_text(self, text: str, cursor: int = 0) -> None:
        """Replace everything (the text-undo history starts again) and put the cursor back."""
        self._auto_closers.clear()
        self.setPlainText(text)
        self.set_cursor(cursor)

    def replace_text(self, text: str) -> None:
        """Replace everything as one step of the editor's own undo (Ctrl+Z gets the old text back)."""
        cursor = self.textCursor()
        cursor.beginEditBlock()
        cursor.select(QTextCursor.SelectionType.Document)
        cursor.insertText(text)
        cursor.endEditBlock()
        self.setTextCursor(cursor)

    def insert_snippet(self, code: str, module_level: bool = False) -> None:
        """Insert a snippet (``${1:default}`` stops, P13.3) at the cursor as one editor-undo step.

        On a blank line it takes the line's place; elsewhere it goes on the line below, indented like
        the cursor's line (one level more after a colon). The first stop is selected and Tab visits
        the rest; Esc leaves them. ``module_level`` snippets sit at the left margin."""
        cursor = self.textCursor()
        block = cursor.block()
        line = block.text()
        lead = line[: len(line) - len(line.lstrip(" \t"))]
        prefix = "" if module_level else lead + (self.indent if line.rstrip().endswith(":") else "")
        text, stops = snippets.expand(snippets.indent(code, prefix))
        cursor.beginEditBlock()
        if not line.strip():
            cursor.setPosition(block.position())
            cursor.setPosition(block.position() + len(line), QTextCursor.MoveMode.KeepAnchor)
            start = block.position()
        else:
            cursor.setPosition(block.position() + len(line))
            text = chr(10) + text
            start = block.position() + len(line) + 1
        cursor.insertText(text)
        cursor.endEditBlock()
        self._snippet_stops = []
        for first, last in stops:
            begin = QTextCursor(self.document())
            begin.setPosition(start + first)
            end = QTextCursor(self.document())
            end.setPosition(start + last)
            self._snippet_stops.append((begin, end))
        if self._snippet_stops:
            self._next_stop()
        else:
            self.setTextCursor(cursor)

    def _next_stop(self) -> None:
        begin, end = self._snippet_stops.pop(0)
        cursor = QTextCursor(self.document())
        cursor.setPosition(begin.position())
        cursor.setPosition(end.position(), QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    def cursor_position(self) -> int:
        return self.textCursor().position()

    def set_cursor(self, position: int) -> None:
        cursor = self.textCursor()
        cursor.setPosition(max(0, min(position, self.document().characterCount() - 1)))
        self.setTextCursor(cursor)

    def current_line(self) -> int:
        """The 1-based line the cursor is on."""
        return self.textCursor().blockNumber() + 1

    def go_to_line(self, line: int) -> int:
        """Put the cursor at the start of ``line`` (kept inside the text), show it and focus the
        editor; returns the line it went to."""
        line = clamp_line(line, self.blockCount())
        self.setTextCursor(QTextCursor(self.document().findBlockByNumber(line - 1)))
        self.centerCursor()
        self.setFocus()
        return line

    def set_error_line(self, line: int | None) -> None:
        """Tint the line a render error points at (None: no error)."""
        line = None if line is None else clamp_line(line, self.blockCount())
        if line != self._error_line:
            self._error_line = line
            self._update_selections()
            self._gutter.update()

    @property
    def error_line(self) -> int | None:
        return self._error_line

    def set_syntax_problem(self, span: tuple[int, int, int, int] | None) -> None:
        """Underline where the text stops being valid Python: ``(line, column, end_line, end_column)``,
        lines from 1 and columns from 0 (``end_column`` 0: to the end of the line); None clears it."""
        if span != self._syntax:
            self._syntax = span
            self._update_selections()

    @property
    def syntax_problem(self) -> tuple[int, int, int, int] | None:
        return self._syntax

    # -- keys ------------------------------------------------------------------------

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key, mods = event.key(), event.modifiers()
        enter = key in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        if enter and mods & Qt.KeyboardModifier.ControlModifier:
            self._completer.popup().hide()
            self.runRequested.emit()
            return
        if self._completer.popup().isVisible() and key in (
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
            Qt.Key.Key_Escape,
            Qt.Key.Key_Tab,
            Qt.Key.Key_Backtab,
        ):
            event.ignore()  # the popup takes these: it accepts the choice or closes
            return
        if key == Qt.Key.Key_Space and mods & Qt.KeyboardModifier.ControlModifier:
            self.suggest(force=True)
            return
        command = self._key_commands().get((mods & ~Qt.KeyboardModifier.KeypadModifier, key))
        if command is not None:
            command()
            return
        if key == Qt.Key.Key_Backtab or (key == Qt.Key.Key_Tab and mods & Qt.KeyboardModifier.ShiftModifier):
            self._dedent()
            return
        if key == Qt.Key.Key_Escape and self._snippet_stops:
            self._snippet_stops = []
            return
        if self._snippet_stops and key == Qt.Key.Key_Tab and not mods:
            self._next_stop()
            return
        if key == Qt.Key.Key_Tab and not mods & (
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier
        ):
            self._indent()
            return
        if enter and not mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier):
            self._new_line()
            return
        if key == Qt.Key.Key_Backspace and not mods and (self._backspace_pair() or self._backspace_indent()):
            return
        if self._type_pair(event):
            self._completer.popup().hide()
            return
        super().keyPressEvent(event)
        self._after_typing(event)

    # -- suggestions (P13.6) -----------------------------------------------------------------

    def _after_typing(self, event: QKeyEvent) -> None:
        text = event.text()
        if text and (text.isalnum() or text in "_."):
            self.suggest()
        elif self._completer.popup().isVisible() and event.key() not in (
            Qt.Key.Key_Shift,
            Qt.Key.Key_Control,
            Qt.Key.Key_Alt,
            Qt.Key.Key_Backspace,
        ):
            self._completer.popup().hide()

    def suggest(self, force: bool = False) -> list[str]:
        """Offer the names that fit the word at the cursor; returns them (none: the popup closes)."""
        popup = self._completer.popup()
        if not self._settings.suggest_names:
            popup.hide()
            return []
        cursor = self.textCursor()
        text = self.text()
        found = [] if cursor.hasSelection() else completion.suggestions(text, cursor.position(), force=force)
        if not found:
            popup.hide()
            return []
        here = completion.context(text, cursor.position())
        self._names.setStringList(found)
        self._completer.setCompletionPrefix(here.prefix)
        if self._completer.completionCount() == 0:
            popup.hide()
            return found
        popup.setCurrentIndex(self._completer.completionModel().index(0, 0))
        rect = self.cursorRect()
        rect.setWidth(popup.sizeHintForColumn(0) + popup.verticalScrollBar().sizeHint().width())
        self._completer.complete(rect)
        return found

    def _complete_with(self, name: str) -> None:
        cursor = self.textCursor()
        here = completion.context(self.text(), cursor.position())
        cursor.setPosition(here.start)
        cursor.setPosition(here.start + len(here.prefix), QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(name)
        self.setTextCursor(cursor)

    def viewportEvent(self, event) -> bool:
        if event.type() == QEvent.Type.ToolTip and self._settings.suggest_names:
            cursor = self.cursorForPosition(event.pos())
            text = self.text()
            here = completion.context(text, cursor.position())
            end = cursor.position()
            while end < len(text) and (text[end].isalnum() or text[end] == "_"):
                end += 1
            word = text[here.start : end]
            tip = completion.hover(text, word, here.receiver) if word else ""
            if tip:
                QToolTip.showText(event.globalPos(), tip, self)
            else:
                QToolTip.hideText()
            return True
        return super().viewportEvent(event)

    def _key_commands(self) -> dict:
        """(modifiers, key) -> the editing command it runs (VS Code's bindings)."""
        ctrl, shift, alt = (
            Qt.KeyboardModifier.ControlModifier,
            Qt.KeyboardModifier.ShiftModifier,
            Qt.KeyboardModifier.AltModifier,
        )
        key = Qt.Key
        return {
            (ctrl, key.Key_Slash): self.toggle_comment,
            (shift | alt, key.Key_Down): self.duplicate_lines_down,
            (shift | alt, key.Key_Up): self.duplicate_lines_up,
            (alt, key.Key_Down): self.move_lines_down,
            (alt, key.Key_Up): self.move_lines_up,
            (ctrl | shift, key.Key_K): self.delete_lines,
            (ctrl, key.Key_L): self.select_lines,
            (ctrl, key.Key_Equal): self.zoom_in,
            (ctrl, key.Key_Plus): self.zoom_in,
            (ctrl | shift, key.Key_Equal): self.zoom_in,
            (ctrl | shift, key.Key_Plus): self.zoom_in,
            (ctrl, key.Key_Minus): self.zoom_out,
            (ctrl, key.Key_0): self.zoom_reset,
        }

    def _new_line(self) -> None:
        cursor = self.textCursor()
        before = cursor.block().text()[: cursor.positionInBlock()]
        indent = before[: len(before) - len(before.lstrip(" \t"))]
        if before.rstrip().endswith(":"):
            indent += self.indent
        cursor.insertText("\n" + indent)
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    def _backspace_indent(self) -> bool:
        cursor = self.textCursor()
        column = cursor.positionInBlock()
        before = cursor.block().text()[:column]
        if cursor.hasSelection() or column == 0 or before.strip() or column % len(self.indent):
            return False
        cursor.beginEditBlock()
        for _ in self.indent:
            cursor.deletePreviousChar()
        cursor.endEditBlock()
        self.setTextCursor(cursor)
        return True

    def _selected_blocks(self) -> list[QTextBlock]:
        cursor = self.textCursor()
        document = self.document()
        first = document.findBlock(cursor.selectionStart())
        last = document.findBlock(cursor.selectionEnd())
        ends_at_line_start = cursor.selectionEnd() == last.position()  # that line is not in the selection
        if cursor.hasSelection() and last.blockNumber() > first.blockNumber() and ends_at_line_start:
            last = last.previous()
        blocks = []
        block = first
        while block.isValid() and block.blockNumber() <= last.blockNumber():
            blocks.append(block)
            block = block.next()
        return blocks

    def _indent(self) -> None:
        cursor = self.textCursor()
        blocks = self._selected_blocks()
        if len(blocks) < 2 or not cursor.hasSelection():
            column = cursor.positionInBlock()
            cursor.insertText(" " * (len(self.indent) - column % len(self.indent)))
            self.setTextCursor(cursor)
            return
        self._edit_blocks(blocks, lambda text: self.indent + text if text.strip() else text)

    def _dedent(self) -> None:
        def remove(text: str) -> str:
            if text.startswith("\t"):
                return text[1:]
            return text[min(len(self.indent), len(text) - len(text.lstrip(" "))) :]

        self._edit_blocks(self._selected_blocks(), remove)

    def _edit_blocks(self, blocks: list[QTextBlock], change) -> None:
        """Rewrite whole lines as one undo step and keep them selected."""
        document = self.document()
        first, last = blocks[0].blockNumber(), blocks[-1].blockNumber()
        edit = QTextCursor(document)
        edit.beginEditBlock()
        for number in range(first, last + 1):
            block = document.findBlockByNumber(number)
            old = block.text()
            new = change(old)
            if new != old:
                line = QTextCursor(block)
                line.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
                line.insertText(new)
        edit.endEditBlock()
        selection = QTextCursor(document.findBlockByNumber(first))
        end = document.findBlockByNumber(last)
        selection.setPosition(end.position() + end.length() - 1, QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(selection)

    # -- brackets and quotes ------------------------------------------------------------------

    def _char_before(self, cursor: QTextCursor) -> str:
        column = cursor.positionInBlock()
        return cursor.block().text()[column - 1] if column else ""

    def _char_after(self, cursor: QTextCursor) -> str:
        text, column = cursor.block().text(), cursor.positionInBlock()
        return text[column] if column < len(text) else ""

    def _type_pair(self, event: QKeyEvent) -> bool:
        """Auto-closing: a typed opener inserts its pair (or wraps the selection), a typed closer
        over one the editor inserted steps over it. True when the key was handled."""
        text, mods = event.text(), event.modifiers()
        if not self._settings.auto_close_brackets or len(text) != 1:
            return False
        ctrl_alt = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier
        held = mods & ctrl_alt
        if held and held != ctrl_alt:  # Ctrl+Alt together is AltGr on Windows
            return False
        cursor = self.textCursor()
        if text in PAIRS and cursor.hasSelection():
            self._surround(cursor, text)
            return True
        if text in CLOSERS and self._step_over(cursor, text):
            return True
        if text in PAIRS and not cursor.hasSelection() and self._may_pair(cursor, text):
            cursor.insertText(text + PAIRS[text])
            cursor.movePosition(QTextCursor.MoveOperation.Left)
            closer = QTextCursor(self.document())
            closer.setPosition(cursor.position())
            self._auto_closers = [*self._auto_closers[-MAX_TRACKED + 1 :], closer]
            self.setTextCursor(cursor)
            return True
        return False

    def _may_pair(self, cursor: QTextCursor, opener: str) -> bool:
        """VS Code's rule: pair when the next character is blank, a closer or punctuation; a quote never
        right after a word character (``don't``), except a string prefix (``f"``), nor a repeated one."""
        after = self._char_after(cursor)
        if after and not after.isspace() and after not in BEFORE_CLOSER:
            return False
        if opener in "\"'":
            before = cursor.block().text()[: cursor.positionInBlock()]
            if before.endswith(opener):
                return False
            word = re.search(r"\w+$", before)
            if word and word.group().lower() not in STRING_PREFIXES:
                return False
        return True

    def _surround(self, cursor: QTextCursor, opener: str) -> None:
        """Wrap the selection in the pair and keep the same text selected."""
        selected = cursor.selectedText()
        start = cursor.selectionStart()
        cursor.beginEditBlock()
        cursor.insertText(opener + selected + PAIRS[opener])
        cursor.endEditBlock()
        inner = QTextCursor(self.document())
        inner.setPosition(start + 1)
        inner.setPosition(start + 1 + len(selected), QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(inner)

    def _step_over(self, cursor: QTextCursor, closer: str) -> bool:
        """Typing ``closer`` right before one the editor inserted just moves past it."""
        if cursor.hasSelection() or self._char_after(cursor) != closer:
            return False
        position = cursor.position()
        tracked = [c for c in self._auto_closers if c.position() == position]
        if not tracked:
            return False
        self._auto_closers = [c for c in self._auto_closers if c.position() != position]
        cursor.movePosition(QTextCursor.MoveOperation.Right)
        self.setTextCursor(cursor)
        return True

    def _backspace_pair(self) -> bool:
        """Backspace between an empty pair (``(|)``) removes both characters."""
        cursor = self.textCursor()
        if not self._settings.auto_close_brackets or cursor.hasSelection():
            return False
        before, after = self._char_before(cursor), self._char_after(cursor)
        if not before or PAIRS.get(before) != after:
            return False
        cursor.beginEditBlock()
        cursor.deletePreviousChar()
        cursor.deleteChar()
        cursor.endEditBlock()
        self.setTextCursor(cursor)
        return True

    # -- line commands (one undo step each) ----------------------------------------------------------

    def _span(self) -> tuple[int, int]:
        """The first and last (0-based) line numbers the cursor or selection touches."""
        blocks = self._selected_blocks()
        return blocks[0].blockNumber(), blocks[-1].blockNumber()

    def _line_texts(self, first: int, last: int) -> list[str]:
        document = self.document()
        return [document.findBlockByNumber(n).text() for n in range(first, last + 1)]

    def _replace_lines(self, first: int, last: int, lines: list[str]) -> None:
        """Replace lines ``first``..``last`` by ``lines`` (call inside an edit block)."""
        document = self.document()
        edit = QTextCursor(document.findBlockByNumber(first))
        end = document.findBlockByNumber(last)
        edit.setPosition(end.position() + end.length() - 1, QTextCursor.MoveMode.KeepAnchor)
        edit.insertText("\n".join(lines))

    def _select_lines(self, first: int, last: int) -> None:
        document = self.document()
        selection = QTextCursor(document.findBlockByNumber(first))
        end = document.findBlockByNumber(last)
        selection.setPosition(end.position() + end.length() - 1, QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(selection)

    def _put_cursor(self, line: int, column: int) -> None:
        block = self.document().findBlockByNumber(line)
        cursor = QTextCursor(block)
        cursor.setPosition(block.position() + max(0, min(column, len(block.text()))))
        self.setTextCursor(cursor)

    def toggle_comment(self) -> None:
        """Comment the selected lines with ``# `` at their common indent, or uncomment them when every
        non-blank one is already commented (blank lines are left alone)."""
        first, last = self._span()
        texts = self._line_texts(first, last)
        code = [t for t in texts if t.strip()]
        if not code:
            return
        cursor = self.textCursor()
        selected, line, column = cursor.hasSelection(), cursor.blockNumber(), cursor.positionInBlock()
        uncomment = all(t.lstrip().startswith("#") for t in code)
        margin = min(len(t) - len(t.lstrip(" \t")) for t in code)
        new = []
        for text in texts:
            if not text.strip():
                new.append(text)
            elif uncomment:
                lead = len(text) - len(text.lstrip(" \t"))
                body = text[lead + 1 :]
                new.append(text[:lead] + (body[1:] if body.startswith(" ") else body))
            else:
                new.append(text[:margin] + "# " + text[margin:])
        edit = QTextCursor(self.document())
        edit.beginEditBlock()
        self._replace_lines(first, last, new)
        edit.endEditBlock()
        if selected:
            self._select_lines(first, last)
        else:
            delta = len(new[line - first]) - len(texts[line - first])
            self._put_cursor(line, column + delta if uncomment or column >= margin else column)

    def duplicate_lines_down(self) -> None:
        """Copy the selected lines below themselves; the copy is left selected (or holds the cursor)."""
        self._duplicate(down=True)

    def duplicate_lines_up(self) -> None:
        """Copy the selected lines above themselves; the copy (now the upper one) is left selected."""
        self._duplicate(down=False)

    def _duplicate(self, *, down: bool) -> None:
        first, last = self._span()
        texts = self._line_texts(first, last)
        cursor = self.textCursor()
        selected, line, column = cursor.hasSelection(), cursor.blockNumber(), cursor.positionInBlock()
        document = self.document()
        edit = QTextCursor(document)
        edit.beginEditBlock()
        if down:
            end = document.findBlockByNumber(last)
            edit.setPosition(end.position() + end.length() - 1)
            edit.insertText("\n" + "\n".join(texts))
        else:
            edit.setPosition(document.findBlockByNumber(first).position())
            edit.insertText("\n".join(texts) + "\n")
        edit.endEditBlock()
        start = last + 1 if down else first
        if selected:
            self._select_lines(start, start + len(texts) - 1)
        else:
            self._put_cursor(start + (line - first), column)

    def move_lines_up(self) -> None:
        """Swap the selected lines with the one above (nothing happens at the top)."""
        self._move(up=True)

    def move_lines_down(self) -> None:
        """Swap the selected lines with the one below (nothing happens at the bottom)."""
        self._move(up=False)

    def _move(self, *, up: bool) -> None:
        first, last = self._span()
        if (up and first == 0) or (not up and last == self.blockCount() - 1):
            return
        cursor = self.textCursor()
        selected, line, column = cursor.hasSelection(), cursor.blockNumber(), cursor.positionInBlock()
        texts = self._line_texts(first, last)
        edit = QTextCursor(self.document())
        edit.beginEditBlock()
        if up:
            (other,) = self._line_texts(first - 1, first - 1)
            self._replace_lines(first - 1, last, [*texts, other])
        else:
            (other,) = self._line_texts(last + 1, last + 1)
            self._replace_lines(first, last + 1, [other, *texts])
        edit.endEditBlock()
        shift = -1 if up else 1
        if selected:
            self._select_lines(first + shift, last + shift)
        else:
            self._put_cursor(line + shift, column)

    def delete_lines(self) -> None:
        """Remove the selected lines (the cursor's line when nothing is selected)."""
        first, last = self._span()
        document = self.document()
        column = self.textCursor().positionInBlock()
        edit = QTextCursor(document)
        edit.beginEditBlock()
        if last < self.blockCount() - 1:
            edit.setPosition(document.findBlockByNumber(first).position())
            edit.setPosition(document.findBlockByNumber(last + 1).position(), QTextCursor.MoveMode.KeepAnchor)
        else:  # the last lines: take the newline before them instead
            end = document.findBlockByNumber(last)
            edit.setPosition(max(0, document.findBlockByNumber(first).position() - 1))
            edit.setPosition(end.position() + end.length() - 1, QTextCursor.MoveMode.KeepAnchor)
        edit.removeSelectedText()
        edit.endEditBlock()
        self._put_cursor(min(first, self.blockCount() - 1), column)

    def select_lines(self) -> None:
        """Select the whole lines the selection touches, newline included; again: one line more."""
        cursor = self.textCursor()
        document = self.document()
        start = document.findBlock(cursor.selectionStart())
        end = document.findBlock(cursor.selectionEnd())
        ends_at_line_start = (
            cursor.hasSelection() and cursor.selectionEnd() == end.position() > start.position()
        )
        if ends_at_line_start and cursor.selectionStart() != start.position():
            end = end.previous()  # that last line is not in the selection; whole lines selected extend by one
        after = end.next()
        stop = after.position() if after.isValid() else end.position() + end.length() - 1
        selection = QTextCursor(document)
        selection.setPosition(start.position())
        selection.setPosition(stop, QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(selection)

    # -- the find bar's matches ---------------------------------------------------------------------

    def set_search_highlights(self, matches: list[tuple[int, int]], current: int | None = None) -> None:
        """Draw find matches (``(start, length)`` document positions; ``current`` is the index of the one
        in focus), on top of the current-line and error-line tints. An empty list clears them."""
        document = self.document()
        end = document.characterCount() - 1
        shown = set(range(min(len(matches), MAX_HIGHLIGHTS)))
        if current is not None and 0 <= current < len(matches):
            shown.add(current)
        else:
            current = None
        selections = []
        for index in sorted(shown):
            start, length = matches[index]
            if start < 0 or length <= 0 or start + length > end:
                continue
            selection = QTextEdit.ExtraSelection()
            token = theme.THEME.search_current if index == current else theme.THEME.search_match
            selection.format.setBackground(theme.qcolor(token))
            selection.cursor = QTextCursor(document)
            selection.cursor.setPosition(start)
            selection.cursor.setPosition(start + length, QTextCursor.MoveMode.KeepAnchor)
            selections.append(selection)
        self._search_selections = selections
        self._update_selections()

    # -- the gutter and the tinted lines ------------------------------------------------

    def gutter_width(self) -> int:
        """The gutter's width: room for the line numbers, 0 when they are switched off."""
        if not self._settings.line_numbers:
            return 0
        digits = max(3, len(str(self.blockCount())))
        return 12 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_margin(self, *_args) -> None:
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)

    def _update_gutter(self, rect: QRect, dy: int) -> None:
        if dy:
            self._gutter.scroll(0, dy)
        else:
            self._gutter.update(0, rect.y(), self._gutter.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_margin()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place_gutter()

    def _place_gutter(self) -> None:
        area = self.contentsRect()
        self._gutter.setGeometry(QRect(area.left(), area.top(), self.gutter_width(), area.height()))

    def paint_gutter(self, rect: QRect) -> None:
        colours = theme.THEME
        painter = QPainter(self._gutter)
        painter.fillRect(rect, theme.qcolor(colours.panel))
        current = self.textCursor().blockNumber()
        block = self.firstVisibleBlock()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        height = self.fontMetrics().height()
        while block.isValid() and top <= rect.bottom():
            number = block.blockNumber()
            if block.isVisible() and top + height >= rect.top():
                if number + 1 == self._error_line:
                    colour = colours.error_text
                else:
                    colour = colours.text if number == current else colours.muted
                painter.setPen(theme.qcolor(colour))
                painter.drawText(
                    0,
                    top,
                    self._gutter.width() - 6,
                    height,
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                    str(number + 1),
                )
            top += round(self.blockBoundingRect(block).height())
            block = block.next()
        painter.end()

    def _update_selections(self) -> None:
        selections = []
        for tint, block in (
            (theme.THEME.code_line, self.textCursor().block() if self._settings.highlight_line else None),
            (
                theme.THEME.code_error_line,
                self.document().findBlockByNumber(self._error_line - 1) if self._error_line else None,
            ),
        ):
            if block is None or not block.isValid():
                continue
            selection = QTextEdit.ExtraSelection()
            colour: QColor = theme.qcolor(tint)
            selection.format.setBackground(colour)
            selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
            selection.cursor = QTextCursor(block)
            selections.append(selection)
        squiggle = self._syntax_selection()
        self.setExtraSelections([*selections, *([squiggle] if squiggle else []), *self._search_selections])
        self._gutter.update()

    def _syntax_selection(self) -> QTextEdit.ExtraSelection | None:
        if self._syntax is None:
            return None
        line, column, end_line, end_column = self._syntax
        first = self.document().findBlockByNumber(clamp_line(line, self.blockCount()) - 1)
        last = self.document().findBlockByNumber(clamp_line(end_line, self.blockCount()) - 1)
        if not first.isValid() or not last.isValid():
            return None
        start = first.position() + min(column, max(first.length() - 1, 0))
        stop = last.position() + (min(end_column, last.length() - 1) if end_column else last.length() - 1)
        if stop <= start:
            stop = min(start + 1, first.position() + first.length() - 1)
        cursor = QTextCursor(self.document())
        cursor.setPosition(start)
        cursor.setPosition(max(stop, start), QTextCursor.MoveMode.KeepAnchor)
        selection = QTextEdit.ExtraSelection()
        selection.format.setUnderlineStyle(QTextCharFormat.UnderlineStyle.WaveUnderline)
        selection.format.setUnderlineColor(theme.qcolor(theme.THEME.error_text))
        selection.cursor = cursor
        return selection
