"""The Compose page (P6b.1, ADR 0041): Layers | the viewer over the timeline | Properties."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QSplitter, QVBoxLayout, QWidget

from ..style import theme
from ..style.card import gutter_splitter, page_margins
from . import Page, Shared

REAL_WIDTH = 600  # a splitter narrower than this has not been laid out in its window yet


def side_widths(total: int) -> tuple[int, int]:
    """Layers and Properties widths for a page ``total`` pixels wide (P6d.4): about a fifth and a
    quarter of it, within limits, so the canvas keeps the rest on a small screen. At the mock-up's
    1440 px they are its 288 and 316 (ADR 0084)."""
    layers = min(max(round(total * 0.205), 240), 288)  # 240: the Layers buttons as icons (P6d.4)
    properties = min(max(round(total * 0.22), 316), 328)  # 316: the Properties card's own minimum
    return layers, properties


class _FirstLayout(QObject):
    """Calls ``then`` once, at the splitter's first resize to a real width."""

    def __init__(self, splitter: QSplitter, then) -> None:
        super().__init__(splitter)
        self.then = then
        splitter.installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:
        if (
            event.type() in (QEvent.Type.Resize, QEvent.Type.Show)
            and watched.width() >= REAL_WIDTH
            and watched.isVisible()
        ):
            watched.removeEventFilter(self)
            self.then()
        return False


class ComposePage(Page):
    name = "compose"
    title = "Compose"
    icon = "compose"
    tooltip = "Build the scene: objects, the canvas, the timeline and properties (Ctrl+1)"

    def build(self) -> QWidget:
        self.outer = gutter_splitter(Qt.Orientation.Horizontal)
        self.centre = gutter_splitter(Qt.Orientation.Vertical)
        self.outer.addWidget(self.centre)
        self._first_layout = _FirstLayout(self.outer, self._size_sides)
        root = QWidget()
        column = QVBoxLayout(root)
        page_margins(column)
        column.addWidget(self.outer)
        return root

    def place(self, shared: Shared) -> None:
        self.centre.insertWidget(0, shared.viewer)
        self.centre.insertWidget(1, shared.timeline)
        self.outer.insertWidget(0, shared.layers)
        self.outer.insertWidget(2, shared.properties)
        self.centre.setStretchFactor(0, 1)
        self.centre.setStretchFactor(1, 0)  # the timeline keeps its height (about six rows)
        self.outer.setStretchFactor(0, 0)
        self.outer.setStretchFactor(1, 1)
        self.outer.setStretchFactor(2, 0)

    def on_show(self) -> None:
        if not getattr(self, "_sized", False):  # first show: panels at their natural widths
            self._sized = True
            self._size_sides()

    def apply_pending(self) -> None:
        if self._pending is not None:  # remembered sizes win over the first-layout ones
            self._first_layout.then = lambda: None
        super().apply_pending()

    def _size_sides(self) -> None:
        if self.outer.width() >= REAL_WIDTH:
            total = self.outer.width()
        else:  # not laid out yet (the welcome is up): the window's own width, at least a laptop's
            total = max(self.window.width() - 2 * theme.GUTTER, 1200)
        total -= 2 * self.outer.handleWidth()  # the gutters take their share of the width
        total = max(total, 1)
        layers, properties = side_widths(total)
        self.outer.setSizes([layers, total - layers - properties, properties])
