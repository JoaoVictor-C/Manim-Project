"""Help > Keyboard Shortcuts (P6d.2, ADR 0044): every shortcut the window has, and the mouse
gestures of the canvas and the timeline, in one searchable table.

The keyboard part is read from the window's own actions, so it can never go stale: a new
menu item with a shortcut shows up here by itself. The gestures are a fixed list.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QAction, QFontMetrics, QKeySequence, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMenuBar,
    QStyle,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from ..style import theme
from ..style.dialog_chrome import DialogFrame


@dataclass(frozen=True)
class Row:
    area: str  # where it works: a menu path, "Canvas", "Timeline"
    what: str
    keys: str


# Mouse and keyboard gestures that are not menu items.
GESTURES: tuple[Row, ...] = (
    Row("Canvas", "Select an object (again: the one behind it with Alt)", "Click, Alt+Click"),
    Row("Canvas", "Add an object to the selection, or take it out", "Shift+Click"),
    Row("Canvas", "Select what a rectangle touches", "Drag on empty canvas (Shift: add)"),
    Row("Canvas", "Move the selection (Shift: one axis, Alt: no snapping)", "Drag"),
    Row("Canvas", "Nudge the selection (Shift: 10 px)", "Arrow keys"),
    Row("Canvas", "Scale / rotate the selected object", "Drag a corner / the knob"),
    Row("Canvas", "Change a size, a line end or a text size", "Drag a round handle"),
    Row("Canvas", "Move the anchor (Shift: snap); centre it", "Ctrl+Drag / Ctrl+Double-click the cross"),
    Row("Canvas", "Select a part of an object; back out", "Double-click / Escape"),
    Row("Canvas", "Cancel a drag", "Escape"),
    Row("Canvas", "Zoom to the selected objects (the whole frame when none)", "F"),
    Row("Canvas", "Select, Hand and Anchor tools", "V, H, P"),
    Row(
        "Canvas",
        "Insert tools: Shape, Line, Text, Math, Media, Graph, 3D (Esc: Select)",
        "R, L, T, E, I, X, D",
    ),
    Row(
        "Canvas",
        "Insert tool with a variant: Circle, Rectangle, Arrow, Number, Tex, SVG, Number line, Sphere",
        "O, Shift+R, Shift+L, Shift+T, Shift+E, Shift+I, Shift+X, Shift+D",
    ),
    Row("Canvas", "Zoom about the cursor / pan", "Ctrl+Wheel / Wheel, Middle-drag"),
    Row("Canvas", "Bend a motion path; smooth or straighten a key", "Drag a handle / Double-click a key"),
    Row("Timeline", "Move or trim a clip, move a key or a marker", "Drag (Alt: no snapping)"),
    Row("Timeline", "Add a clip or a key to the selection, or take it out", "Shift+Click, Ctrl+Click"),
    Row("Timeline", "Select the clips and keys a rectangle touches", "Drag on empty space (Shift/Ctrl: add)"),
    Row("Timeline", "Select every clip and key", "Ctrl+A"),
    Row("Timeline", "Move every selected clip and key together", "Drag one of them (Alt: no snapping)"),
    Row("Timeline", "Move the selected objects whole", "Drag a selected row's lifetime band"),
    Row("Timeline", "Delete every selected clip and key / keep only one", "Delete / Escape"),
    Row("Timeline", "Scrub", "Drag on the ruler"),
    Row("Timeline", "Apply a preset, add clips", "Right-click a row"),
    Row("Timeline", "Show an object's properties as rows", "Click the arrow by its name, Alt+Click the name"),
    Row("Timeline", "Key or unkey one property at the playhead", "Click the diamond in its row"),
    Row("Timeline", "Show a property in the graph (Shift/Ctrl: add, remove)", "Click its name"),
    Row("Animate", "Frame every key in the graph", "A"),
)


def _plain(text: str) -> str:
    return text.replace("&&", "\0").replace("&", "").replace("\0", "&").rstrip(".").strip()


def _menu_rows(menu: QMenu, path: str) -> list[Row]:
    rows = []
    for action in menu.actions():
        if action.isSeparator():
            continue
        name = _plain(action.text())
        if action.menu() is not None:
            rows += _menu_rows(action.menu(), f"{path} > {name}")
        elif action.shortcuts():
            keys = ", ".join(k.toString(QKeySequence.SequenceFormat.NativeText) for k in action.shortcuts())
            rows.append(Row(path, name, keys))
    return rows


def keyboard_rows(menu_bar: QMenuBar, widget: QWidget | None = None) -> list[Row]:
    """Every menu item with a shortcut (by menu), then the other actions of ``widget`` and its
    children that have one (the panels' buttons), each once."""
    rows = []
    for top in menu_bar.actions():
        if top.menu() is not None:
            rows += _menu_rows(top.menu(), _plain(top.text()))
    if widget is not None:
        seen = {(row.what, row.keys) for row in rows}
        for action in widget.findChildren(QAction):
            if not action.shortcuts() or not action.text():
                continue
            keys = ", ".join(k.toString(QKeySequence.SequenceFormat.NativeText) for k in action.shortcuts())
            row = Row("Panels", _plain(action.text()), keys)
            if (row.what, row.keys) not in seen:
                seen.add((row.what, row.keys))
                rows.append(row)
    return rows


def matches(row: Row, query: str) -> bool:
    """Whether every word of ``query`` appears in the row (any column, any case)."""
    text = f"{row.area} {row.what} {row.keys}".lower()
    return all(word in text for word in query.lower().split())


def key_caps(keys: str) -> list[str]:
    """The key combinations in a ``Keys`` cell, or [] when it is a sentence about the mouse ("Drag on empty
    canvas (Shift: add)") that should be drawn as plain text."""
    parts = [part.strip() for part in keys.split(", ") if part.strip()]
    return parts if parts and all(" " not in part for part in parts) else []


class KeysDelegate(QStyledItemDelegate):
    """Draws each key combination as a small rounded keycap (mono type, a hairline) instead of plain text."""

    def paint(self, painter, option, index) -> None:
        caps = key_caps(str(index.data() or ""))
        if not caps:
            super().paint(painter, option, index)
            return
        colours = theme.THEME
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, theme.qcolor(colours.accent_soft))
        font = theme.mono_font(8)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        x, height = option.rect.left() + 6, 18
        top = option.rect.center().y() - height // 2
        for cap in caps:
            width = metrics.horizontalAdvance(cap) + 12
            box = QRectF(x, top, width, height)
            painter.setBrush(theme.qcolor(colours.raised))
            painter.setPen(QPen(theme.qcolor(colours.line_strong), 1))
            painter.drawRoundedRect(box, 5, 5)
            painter.setPen(theme.qcolor(colours.muted))
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter, cap)
            x += width + 4
        painter.restore()

    def sizeHint(self, option, index) -> QSize:
        caps = key_caps(str(index.data() or ""))
        if not caps:
            return super().sizeHint(option, index)
        metrics = QFontMetrics(theme.mono_font(8))
        return QSize(sum(metrics.horizontalAdvance(cap) + 16 for cap in caps) + 10, 26)


class ShortcutsDialog(QDialog):
    """The table: Where, What, Keys; a search field filters it."""

    def __init__(self, rows: list[Row], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Keyboard Shortcuts")
        self.rows = rows
        self.frame = DialogFrame(
            self,
            "keyboard",
            "Keyboard shortcuts",
            "Every shortcut of the menus and every mouse gesture of the canvas and the timeline.",
        )
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search: a word, a key (Ctrl, Shift+1, Delete...)")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        self.table = QTableWidget(len(rows), 3)
        self.table.setHorizontalHeaderLabels(["Where", "What", "Keys"])
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setItemDelegateForColumn(2, KeysDelegate(self.table))
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        for index, row in enumerate(rows):
            for column, text in enumerate((row.area, row.what, row.keys)):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                self.table.setItem(index, column, item)
        self.frame.body.addWidget(self.search)
        self.frame.body.addWidget(self.table, 1)
        self.count = self.frame.add_left(QLabel())
        self.count.setProperty("role", "hint")
        close = self.frame.add_button("Close", "primary")
        close.clicked.connect(self.close)
        self.resize(760, 600)
        self._filter("")

    def visible_rows(self) -> list[Row]:
        return [row for index, row in enumerate(self.rows) if not self.table.isRowHidden(index)]

    def _filter(self, query: str) -> None:
        shown = 0
        for index, row in enumerate(self.rows):
            hide = not matches(row, query)
            self.table.setRowHidden(index, hide)
            shown += not hide
        self.count.setText(f"{shown} of {len(self.rows)}")
        self.count.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
