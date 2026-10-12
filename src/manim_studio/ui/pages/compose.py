"""The Compose page (P6b.1, ADR 0041): Layers | the viewer over the timeline | Properties."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSplitter, QWidget

from . import Page, Shared


class ComposePage(Page):
    name = "compose"
    title = "Compose"
    icon = "compose"
    tooltip = "Build the scene: objects, the canvas, the timeline and properties (Shift+1)"

    def build(self) -> QWidget:
        self.outer = QSplitter(Qt.Orientation.Horizontal)
        self.centre = QSplitter(Qt.Orientation.Vertical)
        self.outer.addWidget(self.centre)
        self.outer.setChildrenCollapsible(False)
        return self.outer

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
            total = max(self.outer.width(), 1200)
            layers, properties = 240, 320
            self.outer.setSizes([layers, total - layers - properties, properties])
