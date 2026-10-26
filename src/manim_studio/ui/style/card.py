"""Cards and chips (Lumen, ADR 0063): the containers every panel of the editor sits in.

A ``Card`` is a rounded surface with a hairline border, an optional 38 px header (an uppercase title and the
panel's actions at its right) and one body widget. Cards are separated by the window colour showing through
the gutters between them. A ``Chip`` is a small rounded label for a state or a kind (``tone``: ``neutral``,
``accent``, ``ok``, ``warn``, ``bad``). A ``Pill`` is a card that floats over a view (the transport over the
stage). The colours come from the stylesheet (``QFrame#card``, ``QLabel[chip]``, ``QFrame#pill``), so a theme
switch needs nothing from them.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QFont, QPainterPath, QRegion, QResizeEvent
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLayout, QSplitter, QVBoxLayout, QWidget

from . import theme

HEADER_HEIGHT = 38


class Card(QFrame):
    """A rounded panel: ``Card("Layers")``; content via ``set_body``, header buttons via ``add_action``."""

    titleChanged = Signal(str)

    def __init__(
        self, title: str = "", parent: QWidget | None = None, *, header: bool = True, clip: bool = False
    ) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._clip = clip
        self._body: QWidget | None = None
        self._title = ""
        column = QVBoxLayout(self)
        column.setContentsMargins(1, 1, 1, 1)  # inside the hairline
        column.setSpacing(0)
        self.header = QFrame()
        self.header.setObjectName("cardHeader")
        self.header.setFixedHeight(HEADER_HEIGHT)
        row = QHBoxLayout(self.header)
        row.setContentsMargins(14, 0, 8, 0)
        row.setSpacing(theme.GUTTER)
        self.title_label = QLabel()
        label_font: QFont = theme.font("section")
        label_font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 108)
        self.title_label.setFont(label_font)
        self.title_label.setProperty("role", "muted")
        row.addWidget(self.title_label)
        self.actions = QHBoxLayout()
        self.actions.setContentsMargins(0, 0, 0, 0)
        self.actions.setSpacing(4)
        row.addStretch(1)
        row.addLayout(self.actions)
        self.rule = QFrame()
        self.rule.setObjectName("cardRule")
        self.rule.setFixedHeight(1)
        column.addWidget(self.header)
        column.addWidget(self.rule)
        self.body_layout = QVBoxLayout()
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(0)
        column.addLayout(self.body_layout, 1)
        self.set_title(title)
        self.set_header_visible(header)

    # -- content -------------------------------------------------------------------------------

    def set_title(self, title: str) -> None:
        self._title = title
        self.title_label.setText(title.upper())
        self.title_label.setAccessibleName(title)
        self.titleChanged.emit(title)

    def title(self) -> str:
        return self._title

    def set_header_visible(self, visible: bool) -> None:
        self.header.setVisible(visible)
        self.rule.setVisible(visible)

    def add_action(self, widget: QWidget) -> QWidget:
        """Put ``widget`` (usually a tool button) at the right of the header."""
        self.actions.addWidget(widget)
        return widget

    def add_title_widget(self, widget: QWidget) -> QWidget:
        """Put ``widget`` right after the title (a count chip, a tab strip)."""
        row = self.header.layout()
        row.insertWidget(row.indexOf(self.title_label) + 1, widget)
        return widget

    def set_body(self, widget: QWidget | None) -> None:
        """The card's content (replaces the previous one, which is not deleted)."""
        if self._body is not None:
            self.body_layout.removeWidget(self._body)
            self._body.setParent(None)
        self._body = widget
        if widget is not None:
            self.body_layout.addWidget(widget, 1)

    def body(self) -> QWidget | None:
        return self._body

    # -- rounded clipping for a body that paints edge to edge (the stage) --------------------------

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if self._clip:
            path = QPainterPath()
            path.addRoundedRect(QRectF(self.rect()), theme.RADIUS_CARD, theme.RADIUS_CARD)
            self.setMask(QRegion(path.toFillPolygon().toPolygon()))


class Chip(QLabel):
    """A small rounded label for a state or kind (``tone``: neutral, accent, ok, warn or bad)."""

    def __init__(self, text: str = "", tone: str = "neutral", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setProperty("chip", True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_tone(tone)

    def set_tone(self, tone: str) -> None:
        self.setProperty("tone", tone)
        self.style().unpolish(self)
        self.style().polish(self)


class Pill(QFrame):
    """A rounded bar that floats over a view (children are laid out by the caller)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("pill")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)


def gutter_splitter(orientation: Qt.Orientation = Qt.Orientation.Horizontal) -> QSplitter:
    """A splitter whose handle is the 8 px gutter between cards (invisible until hovered)."""
    splitter = QSplitter(orientation)
    splitter.setHandleWidth(theme.GUTTER)
    splitter.setChildrenCollapsible(False)
    return splitter


def page_margins(layout: QLayout) -> None:
    """The margins every page's root layout uses: a gutter at the left, right and bottom, none above (the
    top bar sits there)."""
    g = theme.GUTTER
    layout.setContentsMargins(g, 0, g, g)
    layout.setSpacing(g)
