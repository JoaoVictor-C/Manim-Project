"""The Parameters tab of the Code page (P13.4): define a Python object's parameters with a form.

A table of what the editor's ``PARAMS`` declares - name, default, minimum, maximum - that can be edited
in place (double-click a cell), with Add, Rename, Remove and Change for the rest. Typed descriptors
show their parsed type and metadata in the name tooltip; edit those declarations in the code editor.
Every form change goes through ``params_edit.edit_params`` on the **editor's text** (not the applied
code): only the
``PARAMS`` entry being changed is rewritten, the new text replaces the editor's as one step of the
editor's own undo, and nothing is applied - Run is still the decision. Why a change cannot be made
(``ParamsEditError.reason``) shows under the table.

The Values tab tries values; this one changes the schema. Code that reads a parameter (``p["name"]``)
is left to the user, and the status line says so when a renamed or removed name is still read.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.assist import diagnostics, params_edit
from ...core.assist.params_edit import AddParam, ChangeParam, ParamsEditError, RemoveParam, RenameParam
from ...core.code import python_object
from . import code_chrome  # noqa: F401 - the stylesheet rules of the status line
from .dialog_frame import DialogFrame

REFRESH_MS = 300  # the pause in typing after which the table reads the editor again
COLUMNS = ("Name", "Default", "Minimum", "Maximum")
NAME, DEFAULT, MINIMUM, MAXIMUM = range(4)

NOT_PYTHON = "Only a Python object has parameters: select one to define them here."
NO_PARAMS = (
    'The code has no PARAMS = {...}: write one (for example PARAMS = {"size": 1.0}) to define parameters '
    "here."
)
SYNTAX = "The code has a syntax error on line {line}: fix it to edit the parameters here."


@dataclass(frozen=True)
class ParamRow:
    """One parameter as the table shows it; ``minimum``/``maximum`` are None without limits."""

    name: str
    default: Any
    minimum: float | None
    maximum: float | None
    comment: str = ""
    plain: bool = True  # False: a value the form cannot edit (shown as written)
    written: str = ""  # the value's own text in the code


def rows_of(source: str) -> list[ParamRow]:
    """The parameters of ``source``'s ``PARAMS`` (raises ``ParamsEditError`` when it cannot be edited;
    an empty list when there is no ``PARAMS``)."""
    layout = params_edit.read_layout(source)
    if layout is None:
        return []
    try:
        declared = {param.name: param for param in python_object.read_params(source)}
    except python_object.CodeProblem:
        declared = {}
    out = []
    for entry in layout.entries:
        try:
            value = ast.literal_eval(entry.value_text)
        except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
            value = None
        if isinstance(value, dict) and entry.key in declared:
            param = declared[entry.key]
            details = [f"Type: {param.kind}"]
            if param.unit:
                details.append(f"Unit: {param.unit}")
            if param.label:
                details.append(f"Label: {param.label}")
            if param.step is not None:
                details.append(f"Step: {param.step:g}")
            if param.choices:
                details.append("Choices: " + ", ".join(param.choices))
            if entry.comment:
                details.append(entry.comment)
            out.append(
                ParamRow(
                    entry.key,
                    param.default,
                    param.minimum,
                    param.maximum,
                    " · ".join(details),
                    False,
                    show_value(param.default),
                )
            )
        elif isinstance(value, tuple) and len(value) == 3 and all(_is_number(v) for v in value):
            out.append(
                ParamRow(entry.key, value[0], value[1], value[2], entry.comment, True, entry.value_text)
            )
        elif isinstance(value, (bool, str)) or _is_number(value):
            out.append(ParamRow(entry.key, value, None, None, entry.comment, True, entry.value_text))
        else:
            out.append(ParamRow(entry.key, None, None, None, entry.comment, False, entry.value_text))
    return out


def show_value(value: Any) -> str:
    """A default as it is typed in the table: ``1.0``, ``5``, ``True``, ``"text"``."""
    if value is None:
        return ""
    try:
        return params_edit.format_value(value)
    except ParamsEditError:
        return repr(value)


def parse_default(text: str, current: Any = None) -> Any:
    """What a typed default means: a number, True/False, or text (with or without quotes). A whole
    number typed for a parameter that holds decimals stays a decimal (``2`` for ``1.5`` is ``2.0``)."""
    text = text.strip()
    if not text:
        raise ParamsEditError("a parameter needs a default")
    try:
        value = ast.literal_eval(text)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return text  # a bare word: text
    if isinstance(value, bool | str):
        return value
    if _is_number(value):
        if isinstance(value, int) and isinstance(current, float):
            return float(value)
        return value
    raise ParamsEditError(f"{text} cannot be a default (use a number, text or True/False)")


def parse_limit(text: str) -> float | None:
    """A typed limit: a number, or None for an empty cell."""
    text = text.strip()
    if not text:
        return None
    try:
        value = ast.literal_eval(text)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        value = None
    if not _is_number(value):
        raise ParamsEditError(f"the limit {text} is not a number")
    return value


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def reads(source: str, name: str) -> bool:
    """Does the code read ``name`` as ``p["name"]`` (or with single quotes)?"""
    return f'["{name}"]' in source or f"['{name}']" in source


class ChangeDialog(QDialog):
    """Default, minimum and maximum of one parameter together (a pair of limits is set at once)."""

    def __init__(self, row: ParamRow, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Change {row.name}")
        self.default_edit = QLineEdit(show_value(row.default))
        self.minimum_edit = QLineEdit("" if row.minimum is None else repr(row.minimum))
        self.maximum_edit = QLineEdit("" if row.maximum is None else repr(row.maximum))
        for edit in (self.minimum_edit, self.maximum_edit):
            edit.setPlaceholderText("no limit")
        form = QFormLayout()
        form.addRow("Default", self.default_edit)
        form.addRow("Minimum", self.minimum_edit)
        form.addRow("Maximum", self.maximum_edit)
        hint = QLabel(
            "A number, True/False or text. Limits fit a number and go in pairs; leave both empty for none."
        )
        hint.setWordWrap(True)
        hint.setProperty("role", "hint")
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        frame = DialogFrame(self, "rename", f"Change {row.name}", "Its default and limits, together")
        frame.body.addLayout(form)
        frame.body.addWidget(hint)
        frame.add_buttons(buttons)

    def texts(self) -> tuple[str, str, str]:
        return self.default_edit.text(), self.minimum_edit.text(), self.maximum_edit.text()


class ParamsDefinitionPanel(QWidget):
    """The Parameters tab: ``editor`` is the Code page's editor (``text()``, ``replace_text()``)."""

    def __init__(self, editor, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.editor = editor
        self.active = False  # the editor shows a Python object
        self.rows: list[ParamRow] = []
        self._shown: tuple | None = None  # what the table was last filled with
        self._loading = False
        self.setObjectName("paramsDefinition")
        # Hook for tests: (row) -> (default, minimum, maximum) texts, or None (cancelled).
        self.ask_change = self._ask_change_dialog

        self.note = QLabel(NOT_PYTHON)
        self.note.setObjectName("paramsNote")
        self.note.setWordWrap(True)
        self.note.setProperty("role", "hint")
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setObjectName("paramsTable")
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.AnyKeyPressed
        )
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.currentCellChanged.connect(lambda *_: self._refresh_buttons())

        self.add_button = self._button(
            "Add", "Add a parameter to PARAMS (then type its name)", self.add_param
        )
        self.rename_button = self._button(
            "Rename", "Rename the chosen parameter (p[...] in build is left to you)", self.start_rename
        )
        self.change_button = self._button(
            "Change…", "Change the chosen parameter's default and limits together", self.change_chosen
        )
        self.remove_button = self._button(
            "Remove", "Remove the chosen parameter from PARAMS", self.remove_chosen
        )
        buttons = QHBoxLayout()
        for button in (self.add_button, self.rename_button, self.change_button, self.remove_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        self.status = QLabel("")
        self.status.setObjectName("paramsStatus")
        self.status.setWordWrap(True)

        self.body = QWidget()
        body_column = QVBoxLayout(self.body)
        body_column.setContentsMargins(0, 0, 0, 0)
        body_column.addWidget(self.table, 1)
        body_column.addLayout(buttons)
        column = QVBoxLayout(self)
        column.addWidget(self.note)
        column.addWidget(self.body, 1)
        column.addWidget(self.status)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(REFRESH_MS)
        self._timer.timeout.connect(self.refresh)
        editor.textChanged.connect(self._on_text_changed)
        self.refresh()

    def _button(self, text: str, tip: str, slot) -> QPushButton:
        button = QPushButton(text)
        button.setToolTip(tip)
        button.clicked.connect(slot)
        return button

    # -- following the editor -------------------------------------------------------------------

    def set_active(self, active: bool) -> None:
        """The editor shows a Python object (True) or something else."""
        if active != self.active:
            self.active = active
            self.status.clear()
            self.refresh()

    def editable(self) -> bool:
        """Can the parameters be edited here right now?"""
        return not self.body.isHidden()

    def _on_text_changed(self) -> None:
        if self.active:
            self._timer.start()

    def refresh(self) -> None:
        """Read the editor's ``PARAMS`` again; the table is rebuilt only when it changed."""
        self._timer.stop()
        if not self.active:
            self._show_note(NOT_PYTHON)
            return
        text = self.editor.text()
        try:
            layout = params_edit.read_layout(text)
            rows = rows_of(text) if layout is not None else []
        except ParamsEditError as error:
            self._show_note(error.reason)
            return
        if layout is None:
            problem = diagnostics.syntax_problem(text)
            self._show_note(SYNTAX.format(line=problem.line) if problem is not None else NO_PARAMS)
            return
        self.note.hide()
        self.body.show()
        self.rows = rows
        key = tuple(rows)
        if key != self._shown:
            self._fill(rows)
            self._shown = key
        self._refresh_buttons()

    def _show_note(self, text: str) -> None:
        self.rows = []
        self._shown = None
        self.note.setText(text)
        self.note.show()
        self.body.hide()

    def _fill(self, rows: list[ParamRow]) -> None:
        chosen = self.chosen()
        self._loading = True
        try:
            self.table.setRowCount(len(rows))
            for index, row in enumerate(rows):
                cells = (
                    row.name,
                    show_value(row.default) if row.plain else row.written,
                    "" if row.minimum is None else repr(row.minimum),
                    "" if row.maximum is None else repr(row.maximum),
                )
                for column, text in enumerate(cells):
                    item = QTableWidgetItem(text)
                    if not row.plain and column != NAME:
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                        item.setToolTip("Structured parameter: edit its type and metadata in the code")
                    elif column == NAME and row.comment:
                        item.setToolTip(row.comment)
                    if (
                        column != NAME
                        and row.plain
                        and isinstance(row.default, bool | str)
                        and column > DEFAULT
                    ):
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                        item.setToolTip("Only a number has limits")
                    self.table.setItem(index, column, item)
        finally:
            self._loading = False
        if chosen is not None:
            self.choose(chosen)

    def _refresh_buttons(self) -> None:
        has = self.chosen() is not None
        self.rename_button.setEnabled(has)
        self.remove_button.setEnabled(has)
        row = self.chosen_row()
        self.change_button.setEnabled(row is not None and row.plain)

    # -- choosing -------------------------------------------------------------------------------

    def chosen(self) -> str | None:
        """The name of the chosen parameter."""
        row = self.chosen_row()
        return None if row is None else row.name

    def chosen_row(self) -> ParamRow | None:
        index = self.table.currentRow()
        return self.rows[index] if 0 <= index < len(self.rows) else None

    def choose(self, name: str) -> None:
        for index, row in enumerate(self.rows):
            if row.name == name:
                self.table.setCurrentCell(index, NAME)
                return

    def _row(self, name: str) -> ParamRow:
        for row in self.rows:
            if row.name == name:
                return row
        raise ParamsEditError(f"PARAMS has no parameter {name!r}")

    # -- changing -------------------------------------------------------------------------------

    def apply(self, op, done: str = "") -> bool:
        """Apply ``op`` to the editor's text as one editor-undo step; the reason shows when it cannot."""
        text = self.editor.text()
        try:
            new = params_edit.edit_params(text, op)
        except ParamsEditError as error:
            self._say(error.reason, error=True)
            self._shown = None  # put back what an inline edit typed over
            self.refresh()
            return False
        if new != text:
            cursor = self.editor.cursor_position()
            self.editor.replace_text(new)
            self.editor.set_cursor(min(cursor, len(new)))
        self.refresh()
        self._say(done or "Changed: Run applies it (Ctrl+Z in the editor undoes)")
        return True

    def add_param(self) -> bool:
        """Add a parameter with a free name and the default 1.0; its name cell opens for typing."""
        names = {row.name for row in self.rows}
        name, number = "new_param", 2
        while name in names:
            name, number = f"new_param_{number}", number + 1
        if not self.apply(AddParam(name, 1.0), f"Added {name}: type its name and default"):
            return False
        self.choose(name)
        item = self.table.item(self.table.currentRow(), NAME)
        if item is not None and self.isVisible():
            self.table.editItem(item)
        return True

    def remove_param(self, name: str) -> bool:
        done = f"Removed {name}"
        if reads(self.editor.text(), name):
            done += f' - the code still reads p["{name}"]: change it too'
        return self.apply(RemoveParam(name), done)

    def rename_param(self, old: str, new: str) -> bool:
        new = new.strip()
        done = f"Renamed {old} to {new}"
        if reads(self.editor.text(), old):
            done += f' - the code still reads p["{old}"]: change it too'
        ok = self.apply(RenameParam(old, new), done)
        if ok:
            self.choose(new)
        return ok

    def change_param(self, name: str, **fields: Any) -> bool:
        """``ChangeParam`` with ``default``, ``minimum``, ``maximum`` (left out: unchanged)."""
        ok = self.apply(ChangeParam(name, **fields), f"Changed {name}: Run applies it")
        if ok:
            self.choose(name)
        return ok

    def remove_chosen(self) -> None:
        name = self.chosen()
        if name is not None:
            self.remove_param(name)

    def start_rename(self) -> None:
        index = self.table.currentRow()
        item = self.table.item(index, NAME) if index >= 0 else None
        if item is not None:
            self.table.setFocus()
            self.table.editItem(item)

    def change_chosen(self) -> None:
        row = self.chosen_row()
        if row is None or not row.plain:
            return
        texts = self.ask_change(row)
        if texts is None:
            return
        try:
            default = parse_default(texts[0], row.default)
            minimum, maximum = parse_limit(texts[1]), parse_limit(texts[2])
        except ParamsEditError as error:
            self._say(error.reason, error=True)
            return
        self.change_param(row.name, default=default, minimum=minimum, maximum=maximum)

    def set_cell(self, index: int, column: int, text: str) -> bool:
        """What typing ``text`` in a cell does (the table's inline editing calls this)."""
        if not 0 <= index < len(self.rows):
            return False
        row = self.rows[index]
        try:
            if column == NAME:
                if text.strip() == row.name:
                    return False
                return self.rename_param(row.name, text)
            if column == DEFAULT:
                return self.change_param(row.name, default=parse_default(text, row.default))
            limit = parse_limit(text)
        except ParamsEditError as error:
            self._say(error.reason, error=True)
            self._shown = None
            self.refresh()
            return False
        if limit is None:  # an empty limit: no limits at all (they go in pairs)
            return self.change_param(row.name, minimum=None, maximum=None)
        if column == MINIMUM:
            other = row.maximum if row.maximum is not None else max(limit, _number(row.default, limit))
            return self.change_param(row.name, minimum=limit, maximum=other)
        other = row.minimum if row.minimum is not None else min(limit, _number(row.default, limit))
        return self.change_param(row.name, minimum=other, maximum=limit)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading:
            return
        index, column = item.row(), item.column()
        text = item.text()
        QTimer.singleShot(0, lambda: self.set_cell(index, column, text))  # not under the item's own edit

    def _say(self, text: str, error: bool = False) -> None:
        tone = "bad" if error else ""
        if self.status.property("tone") != tone:  # the colour is the stylesheet's (code_chrome.rules)
            self.status.setProperty("tone", tone)
            self.status.style().unpolish(self.status)
            self.status.style().polish(self.status)
        self.status.setText(text)

    def _ask_change_dialog(self, row: ParamRow) -> tuple[str, str, str] | None:
        dialog = ChangeDialog(row, self)
        return dialog.texts() if dialog.exec() == QDialog.DialogCode.Accepted else None


def _number(value: Any, fallback: float) -> float:
    return value if _is_number(value) else fallback
