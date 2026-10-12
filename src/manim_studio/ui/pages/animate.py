"""The Animate page (P6b.2, ADR 0041, decision session 35): the viewer and Properties on top,
the graph editor of the selected layer's keys in the middle, the timeline at the bottom.

The graph is as wide as the timeline under it, so both read time the same way. Its legend
switches each curve on and off; a value the layer cannot key (anything but opacity on a
graph that follows its axes, ADR 0024) is greyed out.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QSplitter, QToolButton, QVBoxLayout, QWidget

from .. import graph_model, icons, theme
from ..graph_editor import GraphEditor
from . import Page, Shared


class AnimatePage(Page):
    name = "animate"
    title = "Animate"
    icon = "animate"
    tooltip = "Shape motion: keys as curves of value over time, with the viewer and timeline (Shift+2)"

    def build(self) -> QWidget:
        self.graph: GraphEditor | None = None  # made on the first show: the selection exists then
        self.checks: dict[str, QCheckBox] = {}
        self.outer = QSplitter(Qt.Orientation.Vertical)
        self.top = QSplitter(Qt.Orientation.Horizontal)
        self.panel = QWidget()
        self.panel_layout = QVBoxLayout(self.panel)
        self.panel_layout.setContentsMargins(0, 0, 0, 0)
        self.panel_layout.setSpacing(0)
        self.outer.addWidget(self.top)
        self.outer.addWidget(self.panel)
        self.outer.setChildrenCollapsible(False)
        return self.outer

    def _make_graph(self) -> None:
        window = self.window
        self.graph = GraphEditor(window.document, window.selection, lambda: window.t)
        self.graph.seekRequested.connect(lambda t: (window.pause(), window.seek(t)))
        self.graph.message.connect(lambda text: window.statusBar().showMessage(text, 10000))
        window.playheadMoved.connect(lambda _t: self.graph.update())
        bar = QHBoxLayout()
        s = theme.SPACE
        bar.setContentsMargins(2 * s, s, 2 * s, s)
        bar.setSpacing(3 * s)
        title = QLabel("Graph")
        title.setProperty("role", "section")
        bar.addWidget(title)
        for curve in graph_model.CURVES:
            check = QCheckBox(curve.label)
            check.setChecked(True)
            check.setToolTip(f"Show the {curve.label.lower()} curve")
            colour = theme.css(getattr(theme.THEME, curve.token))
            check.setStyleSheet(  # the legend: each box in its curve's colour
                f"QCheckBox {{ color: {colour}; }}"
                f" QCheckBox::indicator:checked {{ background: {colour}; border-color: {colour}; }}"
                f" QCheckBox:disabled {{ color: {theme.css(theme.THEME.disabled)}; }}"
            )
            check.toggled.connect(lambda on, n=curve.name: self.graph.set_curve_visible(n, on))
            self.checks[curve.name] = check
            bar.addWidget(check)
        bar.addStretch(1)
        frame = QToolButton()
        frame.setIcon(icons.icon("zoom-in"))
        frame.setText("Frame all")
        frame.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        frame.setToolTip("Show every key of the curves shown (F)")
        frame.clicked.connect(self.graph.frame_all)
        self.frame_button = frame
        bar.addWidget(frame)
        self.panel_layout.addLayout(bar)
        self.panel_layout.addWidget(self.graph, 1)
        window.selection.changed.connect(self._update_legend)
        window.document.changed.connect(lambda *_: self._update_legend())
        window.document.reset.connect(lambda *_: self._update_legend())

    def _update_legend(self) -> None:
        layer = self.graph.layer if self.graph is not None else None
        keyable = {c.name for c in graph_model.curves_for(layer)} if layer is not None else set()
        for name, check in self.checks.items():
            check.setEnabled(name in keyable)

    def place(self, shared: Shared) -> None:
        if self.graph is None:
            self._make_graph()
        self.top.insertWidget(0, shared.viewer)
        self.top.insertWidget(1, shared.properties)
        self.outer.insertWidget(2, shared.timeline)
        self.top.setStretchFactor(0, 1)
        self.top.setStretchFactor(1, 0)
        for index, stretch in enumerate((3, 3, 1)):
            self.outer.setStretchFactor(index, stretch)
        self._update_legend()

    def on_show(self) -> None:
        if not getattr(self, "_sized", False):  # first show: a large graph, the timeline's rows
            self._sized = True
            height = max(self.outer.height(), 700)
            timeline = 190
            graph = (height - timeline) * 9 // 20
            self.outer.setSizes([height - timeline - graph, graph, timeline])
            width = max(self.top.width(), 1200)
            self.top.setSizes([width - 320, 320])
            self.graph.frame_all()
        self.graph.update()
