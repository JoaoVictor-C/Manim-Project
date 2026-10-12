"""The code editor of the Code page (P6b.3, ADR 0041).

A ``QPlainTextEdit`` for Python: the theme's monospace font, a line number gutter,
the current line (and the line a render error points at) tinted, Python highlighting
from ``code_syntax``, auto-indent (a new line keeps the indent and adds four spaces
after a colon), Tab as four spaces (indenting a selection's lines), Shift+Tab
dedenting, Backspace removing a whole indent, and Ctrl+Enter asking to run.
All colours come from the theme's tokens.
"""

from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt, Signal
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
)
from PySide6.QtWidgets import QPlainTextEdit, QTextEdit, QWidget

from . import theme
from .code_drafts import clamp_line
from .code_syntax import NORMAL, scan_line

INDENT = " " * 4
CODE_POINT_SIZE = 10


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

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("codeEditor")
        self.setFont(theme.mono_font(CODE_POINT_SIZE))
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setTabStopDistance(len(INDENT) * self.fontMetrics().horizontalAdvance(" "))
        self.highlighter = PythonHighlighter(self.document())
        self._gutter = _Gutter(self)
        self._error_line: int | None = None
        self.blockCountChanged.connect(self._update_margin)
        self.updateRequest.connect(self._update_gutter)
        self.cursorPositionChanged.connect(self._update_selections)
        self._update_margin()
        self._update_selections()

    # -- text and lines -------------------------------------------------------------

    def text(self) -> str:
        return self.toPlainText()

    def set_text(self, text: str, cursor: int = 0) -> None:
        """Replace everything (the text-undo history starts again) and put the cursor back."""
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

    # -- keys ------------------------------------------------------------------------

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key, mods = event.key(), event.modifiers()
        enter = key in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        if enter and mods & Qt.KeyboardModifier.ControlModifier:
            self.runRequested.emit()
            return
        if key == Qt.Key.Key_Backtab or (key == Qt.Key.Key_Tab and mods & Qt.KeyboardModifier.ShiftModifier):
            self._dedent()
            return
        if key == Qt.Key.Key_Tab and not mods & (
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier
        ):
            self._indent()
            return
        if enter and not mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier):
            self._new_line()
            return
        if key == Qt.Key.Key_Backspace and not mods and self._backspace_indent():
            return
        super().keyPressEvent(event)

    def _new_line(self) -> None:
        cursor = self.textCursor()
        before = cursor.block().text()[: cursor.positionInBlock()]
        indent = before[: len(before) - len(before.lstrip(" \t"))]
        if before.rstrip().endswith(":"):
            indent += INDENT
        cursor.insertText("\n" + indent)
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    def _backspace_indent(self) -> bool:
        cursor = self.textCursor()
        column = cursor.positionInBlock()
        before = cursor.block().text()[:column]
        if cursor.hasSelection() or column == 0 or before.strip() or column % len(INDENT):
            return False
        cursor.beginEditBlock()
        for _ in INDENT:
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
            cursor.insertText(" " * (len(INDENT) - column % len(INDENT)))
            self.setTextCursor(cursor)
            return
        self._edit_blocks(blocks, lambda text: INDENT + text if text.strip() else text)

    def _dedent(self) -> None:
        def remove(text: str) -> str:
            if text.startswith("\t"):
                return text[1:]
            return text[min(len(INDENT), len(text) - len(text.lstrip(" "))) :]

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

    # -- the gutter and the tinted lines ------------------------------------------------

    def gutter_width(self) -> int:
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
            (theme.THEME.code_line, self.textCursor().block()),
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
        self.setExtraSelections(selections)
        self._gutter.update()
