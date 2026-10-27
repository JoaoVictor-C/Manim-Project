"""The Animate page (P6b.2, ADR 0041, decision session 35): on top the viewer, the graph editor of the
selected layer's keys and Properties side by side, the timeline below (Lumen, ADR 0063: the mock-up puts the
curve beside the preview, not under it).

P7.3 (ADR 0047): the timeline's rows expand into property rows, where each property is keyed,
retimed, eased and deleted alone; the graph shows the curves of the properties chosen there
(all of them when none is), named in its colours in the bar. The bar's Record button is
Edit > Auto-key, and A frames every key shown.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget

from ..style import icons, theme
from ..style.card import Card, gutter_splitter, page_margins
from ..style.elided_label import ElidedLabel
from ..timeline import graph_model
from ..timeline.graph_editor import GraphEditor
from ..timeline.view import PROP_LABELS
from . import Page, Shared

ALL_HINT = "All properties: open an object's row in the timeline and click one to show it alone"
CHOSEN_HINT = "Shift+click another property in the timeline to add it, Ctrl+click to take it out"


class AnimatePage(Page):
    name = "animate"
    title = "Animate"
    icon = "animate"
    tooltip = "Shape motion: keys as curves of value over time, with the viewer and timeline (Ctrl+2)"

    def build(self) -> QWidget:
        self.graph: GraphEditor | None = None  # made on the first show: the selection exists then
        self.legend: dict[str, QLabel] = {}
        self.outer = gutter_splitter(Qt.Orientation.Vertical)
        self.top = gutter_splitter(Qt.Orientation.Horizontal)
        self.panel = Card("Curves")
        self.panel_body = QWidget()
        self.panel.set_body(self.panel_body)
        self.panel_layout = QVBoxLayout(self.panel_body)
        self.panel_layout.setContentsMargins(0, 0, 0, 0)
        self.panel_layout.setSpacing(0)
        self.outer.addWidget(self.top)
        root = QWidget()
        column = QVBoxLayout(root)
        page_margins(column)
        column.addWidget(self.outer)
        return root

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
        bar.addWidget(self._record_button(window.auto_key_action))
        for curve in graph_model.CURVES:  # the shown curves' names in their colours
            label = QLabel(curve.label)
            label.setStyleSheet(f"color: {theme.css(getattr(theme.THEME, curve.token))};")
            label.setToolTip(f"The {curve.label.lower()} curve's colour")
            self.legend[curve.name] = label
            bar.addWidget(label)
        self.shown_label = ElidedLabel(ALL_HINT)
        self.shown_label.setProperty("role", "muted")
        bar.addWidget(self.shown_label, 1)
        frame = QToolButton()
        frame.setIcon(icons.icon("zoom-in"))
        frame.setText("Frame all")
        frame.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        frame.setToolTip("Show every key of the curves shown (A)")
        frame.clicked.connect(self.graph.frame_all)
        self.frame_button = frame
        bar.addWidget(frame)
        self.panel_layout.addLayout(bar)
        self.panel_layout.addWidget(self.graph, 1)
        shortcut = QShortcut(QKeySequence("A"), self.outer)  # anywhere on the page (P7.3)
        shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        shortcut.activated.connect(lambda: self.graph.frame_all())
        self.frame_shortcut = shortcut
        window.timeline.propsSelected.connect(self._update_props)
        window.selection.changed.connect(self._update_props)
        window.document.changed.connect(lambda *_: self._update_props())
        window.document.reset.connect(lambda *_: self._update_props())

    def _record_button(self, action) -> QToolButton:
        """Record: Edit > Auto-key as a red-dot toggle, each following the other."""
        button = QToolButton()
        button.setCheckable(True)
        button.setChecked(action.isChecked())
        button.setIcon(icons.icon("record"))
        button.setText("Record")
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        button.setToolTip(
            "Record: moving, scaling, rotating or fading an object keys it at the playhead (Edit > Auto-key)"
        )
        button.toggled.connect(action.setChecked)
        action.toggled.connect(button.setChecked)
        self.record_button = button
        return button

    def _update_props(self) -> None:
        """Show the curves of the properties chosen on the timeline, and say which they are."""
        if self.graph is None:
            return
        layer, timeline = self.graph.layer, self.window.timeline
        props = timeline.selected_props if layer is not None and timeline.prop_layer == layer.id else ()
        self.graph.set_props(props)
        shown = {curve.name for curve in self.graph.curves()}
        for name, label in self.legend.items():
            label.setVisible(name in shown)
        if layer is None:
            self.shown_label.setText("Select an object to see its keys")
        elif props:
            self.shown_label.setText(f"{', '.join(PROP_LABELS[p] for p in props)} - {CHOSEN_HINT}")
        else:
            self.shown_label.setText(ALL_HINT)

    def place(self, shared: Shared) -> None:
        if self.graph is None:
            self._make_graph()
        self.top.insertWidget(0, shared.viewer)
        self.top.insertWidget(1, self.panel)
        self.top.insertWidget(2, shared.properties)
        self.outer.insertWidget(1, shared.timeline)
        for index, stretch in enumerate((2, 3, 0)):
            self.top.setStretchFactor(index, stretch)
        for index, stretch in enumerate((3, 1)):
            self.outer.setStretchFactor(index, stretch)
        self._update_props()

    def on_show(self) -> None:
        if not getattr(self, "_sized", False):  # first show: a large graph, the timeline's rows
            self._sized = True
            height = max(self.outer.height(), 700)
            timeline = 220
            self.outer.setSizes([height - timeline, timeline])
            width = max(self.top.width(), 1200)
            properties = 316
            room = width - properties
            self.top.setSizes([room * 2 // 5, room * 3 // 5, properties])
            self.graph.frame_all()
        self.graph.update()
