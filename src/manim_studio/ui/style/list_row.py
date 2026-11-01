"""List rows for dialogs (Lumen, ADR 0063, 0084): the row of the design's list component, with chips.

``RowList`` is a list view whose items are ``ListRow`` widgets: a rounded row on the field colour, a hover
tint and an accent tint when chosen. A row has an optional leading widget (a picture, an icon tile), a title
with chips at its right, quiet lines under it (each with an optional coloured ``Dot``) and actions at the
far right. The view is a ``QListWidget`` underneath, so keyboard choice, ``currentRow``, ``item(i).text()``
(the row's plain text, for assistive tools) and ``itemDoubleClicked`` work as usual; the item paints only
its panel, the row widget paints the content. Colours come from the stylesheet and the theme tokens.
"""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QIcon, QPainter, QPaintEvent, QResizeEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from . import theme
from .card import Chip

ROW_PAD = 10  # px: inside a row, at its sides
ROW_GAP = theme.SPACE * 2  # px: between a row's parts
ITEM_GAP = theme.SPACE  # px: between rows


def _rules(c: theme.Colours) -> str:
    return f"""
QListWidget[rows="true"] {{ background: transparent; border: 0; outline: 0; }}
QListWidget[rows="true"]::item {{
    padding: 0; margin: 0; background: {c.field}; border: 1px solid {theme.css(c.line)};
    border-radius: {theme.RADIUS_ROW}px;
}}
QListWidget[rows="true"]::item:hover {{ background: {c.surface_3}; }}
QListWidget[rows="true"]::item:disabled {{ background: transparent; border-color: transparent; }}
QListWidget[rows="true"]::item:selected {{
    background: {theme.css(c.accent_soft)}; border-color: {theme.css(c.accent_line)};
}}
QFrame[listRow="true"], QFrame[listRow="true"] QLabel {{ background: transparent; border: 0; }}
QFrame[listRow="true"] QLabel[chip="true"] {{
    background: {c.raised}; border: 1px solid {theme.css(c.line)}; border-radius: 11px;
}}
QFrame[listRow="true"] QLabel[chip="true"][tone="accent"] {{
    background: {theme.css(c.accent_soft)}; border-color: {theme.css(c.accent_line)};
}}
QLabel[role="rowTitle"] {{ color: {c.text}; font-weight: 600; }}
QLabel[role="rowMono"] {{ color: {c.muted}; }}
"""


theme.register_rules(_rules)


class Dot(QWidget):
    """A small filled circle in a theme colour (``token`` names a field of the theme: ``success``,
    ``accent``, ``sound`` ...); it follows a theme switch because the colour is read when it paints."""

    SIZE = 8

    def __init__(self, token: str = "accent", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.token = token
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme.qcolor(getattr(theme.THEME, self.token)))
        painter.drawEllipse(QRectF(self.rect()))
        painter.end()


class ListRow(QFrame):
    """One row: ``lead``, then ``title`` with chips at its right, quiet lines under it, actions at the end."""

    def __init__(
        self,
        title: str = "",
        *,
        lead: QWidget | None = None,
        subtitle: str = "",
        mono: str = "",
        plain: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setProperty("listRow", True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(ROW_PAD, ROW_GAP, ROW_PAD, ROW_GAP)
        outer.setSpacing(ROW_GAP + 2)
        self.lead = lead
        if lead is not None:
            outer.addWidget(lead, 0, Qt.AlignmentFlag.AlignTop)
        self.column = QVBoxLayout()
        self.column.setSpacing(2)
        self.head = QHBoxLayout()
        self.head.setSpacing(ROW_GAP)
        self.title_label = QLabel(title)
        self.title_label.setProperty(
            "role", "readout" if plain else "rowTitle"
        )  # plain: a sentence, not a name
        self.title_label.setWordWrap(True)
        self.head.addWidget(self.title_label, 1)
        self.mono_label = QLabel(mono)
        self.mono_label.setProperty("role", "rowMono")
        self.mono_label.setFont(theme.mono_font())
        self.mono_label.setVisible(bool(mono))
        self.head.addWidget(self.mono_label)
        self.column.addLayout(self.head)
        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setProperty("role", "muted")
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setVisible(bool(subtitle))
        self.column.addWidget(self.subtitle_label)
        self.column.addStretch(1)  # what is added later goes above it: the lines stay at the top
        outer.addLayout(self.column, 1)
        self.actions = QVBoxLayout()
        self.actions.setSpacing(ROW_GAP)
        outer.addLayout(self.actions)
        self.chips: list[Chip] = []
        self.lines: list[QLabel] = []

    # -- content -------------------------------------------------------------------------------

    def add_head_chip(self, text: str, tone: str = "neutral", tip: str = "") -> Chip:
        """A chip at the right of the title (a kind, a state)."""
        chip = Chip(text, tone)
        if tip:
            chip.setToolTip(tip)
        self.head.addWidget(chip)
        self.chips.append(chip)
        return chip

    def add_chips(self, chips: list[tuple[str, str]], tips: list[str] | None = None) -> list[Chip]:
        """A line of chips under the title; ``chips`` is ``[(text, tone), ...]``."""
        line = QHBoxLayout()
        line.setSpacing(ROW_GAP - 2)
        made = []
        for k, (text, tone) in enumerate(chips):
            chip = Chip(text, tone)
            if tips and k < len(tips) and tips[k]:
                chip.setToolTip(tips[k])
            line.addWidget(chip)
            made.append(chip)
        line.addStretch(1)
        self.column.insertLayout(self.column.count() - 1, line)
        self.chips += made
        return made

    def add_line(self, text: str, dot: str | None = None, label: str = "") -> QLabel:
        """A quiet line under the title, with a coloured dot at its left when ``dot`` names a token; ``label``
        is a small word before the text (``Appears``, ``Says``)."""
        line = QHBoxLayout()
        line.setSpacing(ROW_GAP - 2)
        if dot is not None:
            mark = Dot(dot)
            holder = QVBoxLayout()
            holder.setContentsMargins(0, 4, 0, 0)
            holder.addWidget(mark)
            line.addLayout(holder)
        if label:
            tag = QLabel(label)
            tag.setProperty("role", "hint")
            tag.setMinimumWidth(52)
            line.addWidget(tag, 0, Qt.AlignmentFlag.AlignTop)
        body = QLabel(text)
        body.setProperty("role", "muted")
        body.setWordWrap(True)
        line.addWidget(body, 1)
        self.column.insertLayout(self.column.count() - 1, line)
        self.lines.append(body)
        return body

    def add_action(self, button: QWidget) -> QWidget:
        self.actions.addWidget(button, 0, Qt.AlignmentFlag.AlignTop)
        return button


class _PanelOnly(QStyledItemDelegate):
    """Paints the item's rounded panel (hover, chosen) and nothing else: the row widget draws the content."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        shown = QStyleOptionViewItem(option)
        self.initStyleOption(shown, index)
        shown.text = ""
        shown.icon = QIcon()
        shown.features &= ~(
            QStyleOptionViewItem.ViewItemFeature.HasDisplay
            | QStyleOptionViewItem.ViewItemFeature.HasDecoration
        )
        shown.state &= ~QStyle.StateFlag.State_HasFocus
        style = shown.widget.style() if shown.widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, shown, painter, shown.widget)


class RowList(QListWidget):
    """A scrolling column of ``ListRow`` widgets."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("rows", True)
        self.setItemDelegate(_PanelOnly(self))
        self.setSpacing(ITEM_GAP)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMouseTracking(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setResizeMode(QListWidget.ResizeMode.Adjust)

    def add_row(
        self, row: QWidget, text: str = "", data: object = None, *, selectable: bool = True
    ) -> QListWidgetItem:
        """Add ``row``; ``text`` is the item's plain text (what assistive tools and tests read)."""
        item = QListWidgetItem(text)
        if data is not None:
            item.setData(Qt.ItemDataRole.UserRole, data)
        if not selectable:
            item.setFlags(Qt.ItemFlag.NoItemFlags)
        self.addItem(item)
        self.setItemWidget(item, row)
        self._fit(item)
        return item

    def add_note(self, text: str) -> QListWidgetItem:
        """A line of plain words in the list (an empty state, a section name)."""
        label = QLabel(text)
        label.setProperty("role", "muted")
        label.setWordWrap(True)
        label.setContentsMargins(ROW_PAD, ROW_GAP, ROW_PAD, ROW_GAP)
        return self.add_row(label, text, selectable=False)

    def _fit(self, item: QListWidgetItem) -> None:
        widget = self.itemWidget(item)
        if widget is None:
            return
        width = max(120, self.viewport().width() - 2 * ITEM_GAP - 2)
        widget.ensurePolished()  # the stylesheet's fonts and paddings count in the height
        for child in widget.findChildren(QWidget):
            child.ensurePolished()
        layout = widget.layout()
        if layout is not None:
            layout.invalidate()
        if layout is not None:
            height = layout.totalHeightForWidth(width)
        elif widget.hasHeightForWidth():
            height = widget.heightForWidth(width)
        else:
            height = widget.sizeHint().height()
        item.setSizeHint(QSize(width, height + 2))

    def refit(self) -> None:
        for k in range(self.count()):
            self._fit(self.item(k))

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self.refit()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refit()
        QTimer.singleShot(0, self, self.refit)  # once the first layout pass has given the view its real width
