"""The Stage card's header strip (Lumen, ADR 0063, 0084): the picture's state as chips and segmented controls.

From the left: the scene's size and frame rate, the **Scene | Game** view (the camera's explanation is its
tooltip and a status-bar hint, never prose over the video), a chip when the camera keeps handles off; then
the quiet mono readout (time, frame, render time, render-ahead), the **Follow playhead** chip, the
**Fit / 75 % / 100 %** control and **full screen**. When the card is narrow the least important items
leave first (readout, camera chip, size chip, Follow, then the zoom and full screen), so the Scene | Game
control always stays.
"""

from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QHBoxLayout, QLabel, QToolButton, QWidget

from ..style import theme
from ..style.card import Chip
from ..style.segmented import Segmented
from ..style.toggle_chip import ToggleChip

SCENE, GAME = 0, 1
FIT, THREE_QUARTERS, ACTUAL = 0, 1, 2
SEG_HEIGHT = 24
READOUT_MIN = 84  # the readout shortens down to this before it leaves
ZOOM_SCALES = {THREE_QUARTERS: 0.75, ACTUAL: 1.0}

GAME_TIP = (
    "Game: the picture through the camera layer, as the video shows it. Scene: the scene unmoved, objects "
    "editable, the camera drawn as the rectangle it sees (G)"
)
GAME_HINT = (
    "Game view: the camera moves the picture here. Switch to Scene view (G) to edit objects and the camera."
)
SCENE_HINT = "Scene view: the scene unmoved; the camera is the rectangle it sees. Press G for the Game view."


def _rules(c: theme.Colours) -> str:
    """Compact segments: the header is 38 px high, the control 24."""
    return """
QWidget#stageHeader QPushButton[seg="true"] {
    padding: 0px 9px; min-height: 18px; max-height: 18px; font-size: 11px; font-weight: 600;
}
QWidget#stageHeader QWidget#segmented { border-radius: 8px; }
"""


theme.register_rules(_rules)


def deselect(segmented: Segmented) -> None:
    """Show no segment as current (a zoom that is none of the presets); a later click still counts."""
    group = segmented.button(0).group()
    group.setExclusive(False)
    for k in range(segmented.count()):
        segmented.button(k).setChecked(False)
    group.setExclusive(True)


class StageHeader(QWidget):
    """The chips and controls after the Stage title. ``readout`` is the window's own label."""

    def __init__(self, canvas, scene_chip: Chip, readout: QLabel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.canvas = canvas
        self.scene_chip = scene_chip
        self.readout = readout
        self.setObjectName("stageHeader")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self.view_seg = Segmented()
        self.view_seg.addItem("Scene", SCENE, "Scene view: the scene unmoved, objects editable (G)")
        self.view_seg.addItem(
            "Game", GAME, "Game view: the picture through the camera, as the video shows it (G)"
        )
        self.view_seg.setToolTip(GAME_TIP)
        self.view_seg.setAccessibleName("Stage view")
        self.view_seg.setCurrentIndex(GAME)
        self.view_seg.setFixedHeight(SEG_HEIGHT)
        self.notice_chip = Chip("Camera view", "warn")
        self.notice_chip.hide()
        self.follow_chip = ToggleChip("Follow playhead")
        self.zoom_seg = Segmented()
        self.zoom_seg.setAccessibleName("Stage zoom")
        self.zoom_seg.addItem("Fit", FIT, "Fit the whole frame in the Stage")
        self.zoom_seg.addItem("75%", THREE_QUARTERS, "Show the frame at 75 % of its exported size")
        self.zoom_seg.addItem(
            "100%", ACTUAL, "Show the frame at its exported size (one screen pixel per pixel)"
        )
        self.zoom_seg.setFixedHeight(SEG_HEIGHT)
        self.fullscreen_button = QToolButton()
        self.fullscreen_button.setObjectName("iconButton")
        self.fullscreen_button.setFixedSize(26, 26)
        self.fullscreen_button.setAutoRaise(True)
        # priority: the first of these to hide is the first in the list
        self._droppable = [
            self.readout,
            self.notice_chip,
            self.scene_chip,
            self.follow_chip,
            self.zoom_seg,
            self.fullscreen_button,
        ]
        row.addWidget(self.scene_chip)
        row.addWidget(self.view_seg)
        row.addWidget(self.notice_chip)
        row.addStretch(1)
        row.addWidget(self.readout)
        row.addWidget(self.follow_chip)
        row.addWidget(self.zoom_seg)
        row.addWidget(self.fullscreen_button)
        for k in range(self.view_seg.count()):
            self.view_seg.button(k).clicked.connect(lambda _c=False, i=k: self.viewChosen(i))
        for k in range(self.zoom_seg.count()):
            self.zoom_seg.button(k).clicked.connect(lambda _c=False, i=k: self._zoom_chosen(i))
        canvas.view_changed.connect(self.sync_zoom)
        self.on_view_chosen = lambda scene: None  # the window: the Game View action
        self.sync_zoom()

    # -- the view (Scene | Game) -----------------------------------------------------------------

    def viewChosen(self, index: int) -> None:
        self.on_view_chosen(index == SCENE)

    def set_scene_view(self, scene: bool) -> None:
        """Follow the Game View action (no feedback loop: only clicks call ``on_view_chosen``)."""
        self.view_seg.setCurrentIndex(SCENE if scene else GAME)

    # -- the zoom (Fit / 75 % / 100 %) -----------------------------------------------------------

    def _zoom_chosen(self, index: int) -> None:
        if index == FIT:
            self.canvas.fit()
        else:
            self.canvas.set_scale(ZOOM_SCALES[index])
        self.sync_zoom()

    def current_zoom(self) -> int | None:
        view = self.canvas.view
        if view.fit:
            return FIT
        for index, scale in ZOOM_SCALES.items():
            if abs(view.scale - scale) < 1e-6:
                return index
        return None

    def sync_zoom(self) -> None:
        current = self.current_zoom()
        if current is None:
            deselect(self.zoom_seg)
        else:
            self.zoom_seg.button(current).setChecked(True)
        label = self.canvas.zoom_label()
        self.zoom_seg.button(FIT).setToolTip(
            f"Fit the whole frame in the Stage ({label})" if label else "Fit"
        )

    def sync_notice(self) -> None:
        """The camera chip: why handles are off right now (the text is its tooltip)."""
        self.notice_chip.setToolTip(self.canvas.notice())
        self._fit_items()

    # -- narrow cards ----------------------------------------------------------------------------

    def minimumSizeHint(self) -> QSize:
        return QSize(0, super().minimumSizeHint().height())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit_items()

    def _width_of(self, widget: QWidget) -> int:
        width = widget.sizeHint().width()
        return (min(width, READOUT_MIN) if widget is self.readout else width) + self.layout().spacing()

    def _fit_items(self) -> None:
        """Hide the droppable items, least important first, until the rest fits the width."""
        wanted = [w for w in self._droppable if w is not self.notice_chip or bool(self.canvas.notice())]
        total = sum(self._width_of(w) for w in (self.view_seg, *wanted))
        shown = set(wanted)
        for widget in wanted:
            if total <= self.width():
                break
            total -= self._width_of(widget)
            shown.discard(widget)
        for widget in self._droppable:
            widget.setVisible(widget in shown)
