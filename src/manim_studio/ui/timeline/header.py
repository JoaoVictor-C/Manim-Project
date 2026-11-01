"""The Timeline card's header strip (Lumen, ADR 0063, 0084): Snap and Auto-key chips, **+ Clip**, the zoom.

Snap turns the timeline's snapping to clip edges, keys, markers and the playhead on or off (Alt still does it
for one drag); Auto-key follows Edit > Auto-key; **+ Clip** opens the "Add clip" menu for the selected
object at the playhead; the slider zooms the timeline (log scale) and follows the wheel and Fit Timeline.
When the card is narrow the slider and its icons leave first.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QHBoxLayout, QMenu, QPushButton, QSlider, QToolButton, QWidget

from ..style import icons
from ..style.toggle_chip import ToggleChip

SLIDER_STEPS = 1000
SLIDER_WIDTH = 90
ZOOM_STEP = 1.2


class TimelineHeader(QWidget):
    """``selected_layer`` (set by the window) names the object + Clip adds to (None: nothing selected)."""

    def __init__(self, timeline, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.timeline = timeline
        self.selected_layer: Callable[[], str | None] = lambda: None
        self.setObjectName("timelineHeader")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self.snap_chip = ToggleChip("Snap", icon="snap")
        self.snap_chip.setChecked(timeline.snap_enabled)
        self.snap_chip.setToolTip(
            "Snap clip edges, keys and markers to each other and to the playhead (Alt: off for a drag)"
        )
        self.snap_chip.toggled.connect(lambda on: setattr(timeline, "snap_enabled", on))
        self.autokey_chip = ToggleChip("Auto-key", dot=True)
        self.add_clip_button = QPushButton("Clip")
        self.add_clip_button.setIcon(icons.icon("add"))
        self.add_clip_button.setProperty("role", "ghost")
        self.add_clip_button.setFixedHeight(24)
        self.add_clip_button.setToolTip("Add an animation clip to the selected object at the playhead")
        self.add_clip_button.clicked.connect(self.show_clip_menu)
        self.zoom_out = self._zoom_button("zoom-out", "Zoom the timeline out", 1 / ZOOM_STEP)
        self.zoom_in = self._zoom_button("zoom-in", "Zoom the timeline in", ZOOM_STEP)
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(0, SLIDER_STEPS)
        self.zoom_slider.setFixedWidth(SLIDER_WIDTH)
        self.zoom_slider.setToolTip("Zoom the timeline (Ctrl + wheel; Shift+F fits the scene)")
        self.zoom_slider.setAccessibleName("Timeline zoom")
        self.zoom_slider.valueChanged.connect(self._slider_moved)
        row.addWidget(self.snap_chip)
        row.addWidget(self.autokey_chip)
        row.addStretch(1)
        row.addWidget(self.add_clip_button)
        for widget in (self.zoom_out, self.zoom_slider, self.zoom_in):
            row.addWidget(widget)
        self._zoom_items = (self.zoom_out, self.zoom_slider, self.zoom_in)
        timeline.scaleChanged.connect(self.sync_zoom)
        self.sync_zoom()

    # -- zoom ------------------------------------------------------------------------------------

    def _zoom_button(self, icon: str, tip: str, factor: float) -> QToolButton:
        button = QToolButton()
        button.setObjectName("iconButton")
        button.setAutoRaise(True)
        button.setFixedSize(24, 24)
        button.setIcon(icons.icon(icon, "muted"))
        button.setToolTip(tip)
        button.setAccessibleName(tip)
        button.clicked.connect(lambda: self.timeline.zoom(factor, self.timeline.viewport().width() / 2))
        return button

    def _slider_moved(self, value: int) -> None:
        self.timeline.set_zoom_fraction(value / SLIDER_STEPS)

    def sync_zoom(self) -> None:
        value = round(self.timeline.zoom_fraction() * SLIDER_STEPS)
        if value != self.zoom_slider.value():
            self.zoom_slider.blockSignals(True)
            self.zoom_slider.setValue(value)
            self.zoom_slider.blockSignals(False)

    # -- + Clip ----------------------------------------------------------------------------------

    def clip_menu(self) -> QMenu | None:
        """The "Add clip" menu for the selected object at the playhead (None: nothing to add to)."""
        layer_id = self.selected_layer()
        project = self.timeline.project
        if project is None or not layer_id or not any(x.id == layer_id for x in project.layers):
            return None
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        self.timeline.add_clip_menu(menu, project.layer(layer_id), self.timeline.playhead)
        return menu

    def show_clip_menu(self) -> None:
        menu = self.clip_menu()
        if menu is None:
            menu = QMenu(self)
            menu.addAction("Select an object first").setEnabled(False)
        menu.exec(self.add_clip_button.mapToGlobal(self.add_clip_button.rect().bottomLeft()))

    # -- narrow cards ----------------------------------------------------------------------------

    def minimumSizeHint(self) -> QSize:
        return QSize(0, super().minimumSizeHint().height())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        spacing = self.layout().spacing()
        fixed = sum(
            w.sizeHint().width() + spacing for w in (self.snap_chip, self.autokey_chip, self.add_clip_button)
        )
        zoom = sum(w.sizeHint().width() + spacing for w in self._zoom_items)
        for widget in self._zoom_items:
            widget.setVisible(fixed + zoom <= self.width())
