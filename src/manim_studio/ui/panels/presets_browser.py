"""Animate > Browse Presets... (P6d.3, ADR 0044): presets as cards with moving previews.

A card shows a preset drawn on a square (``render.preset_thumbs``: the evaluator and Cairo,
the exact frames the preset makes) as a still from the middle of its run, and plays the
run while the pointer is over it. Category tabs and a search field narrow the cards;
a double-click or *Apply* puts the chosen preset on every selected layer at the playhead
(or on one layer at a given time, from the timeline row's menu) through the window's own
``apply_preset``: one undo step, whole or refused. The dialog stays open, so several
presets can be tried; what happened is on its status line and in the status bar.
"""

from __future__ import annotations

from functools import cache

import numpy as np
from PySide6.QtCore import QEvent, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QImage, QKeyEvent, QPainter, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

from ...core.editing import library
from ...render import preset_thumbs
from ..style import icons, theme

PRESET_ROLE = Qt.ItemDataRole.UserRole  # the Preset on a card
USER_ROLE = Qt.ItemDataRole.UserRole + 1  # True for a preset of the user's own
TABS: tuple[tuple[str, str | None], ...] = (
    ("All", None),
    ("Entrance", "entrance"),
    ("Emphasis", "emphasis"),
    ("Exit", "exit"),
    ("Motion", "motion"),
)
FRAME_MS = 110  # a hovered card shows 9 frames a second: its whole run in about a second
CARD = QSize(preset_thumbs.WIDTH + 28, preset_thumbs.HEIGHT + 44)
BADGE_TEXT = "Yours"
NO_LAYER = "Select a layer to animate first"


@cache
def builtin_presets() -> dict[str, library.Preset]:
    """The presets that ship with the editor, by name."""
    return {p.name: p for p in library.load_library([library.BUILTIN_FOLDER]).presets}


def thumb_background() -> str:
    """The colour behind a thumbnail's square: a tile one step above the grid's field."""
    return theme.THEME.surface_3


def is_user_preset(preset: library.Preset) -> bool:
    """True for a preset the user made, or changed from the built-in of its name."""
    return builtin_presets().get(preset.name) != preset


def filter_presets(presets: list[library.Preset], category: str | None, query: str) -> list[library.Preset]:
    """The presets of ``category`` (None: all) whose name or description has every word of ``query``,
    grouped by category in the library's order."""
    words = query.lower().split()
    found = [
        p
        for p in presets
        if (category is None or p.category == category)
        and all(w in f"{p.name} {p.description}".lower() for w in words)
    ]
    return sorted(found, key=lambda p: library.CATEGORIES.index(p.category))


def target_text(layer_names: list[str], at: float | None, fixed: bool) -> str:
    """The line saying what *Apply* will do: a fixed layer and time (from the timeline row), or
    the selected layers at the playhead."""
    if fixed:
        return f"Applies to {layer_names[0]} at {at:.2f} s"
    if not layer_names:
        return NO_LAYER
    if len(layer_names) == 1:
        return f"Applies to {layer_names[0]} at the playhead"
    return f"Applies to {len(layer_names)} selected layers at the playhead"


def to_pixmap(frame: np.ndarray) -> QPixmap:
    """An RGBA frame (height x width x 4) as a pixmap."""
    frame = np.ascontiguousarray(frame)
    height, width, _ = frame.shape
    image = QImage(frame.data, width, height, width * 4, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(image.copy())


def placeholder() -> QPixmap:
    """What a card shows for a preset a square cannot take, so nothing can be drawn."""
    colours = theme.THEME
    pixmap = QPixmap(preset_thumbs.WIDTH, preset_thumbs.HEIGHT)
    pixmap.fill(theme.qcolor(colours.raised))
    painter = QPainter(pixmap)
    painter.setPen(theme.qcolor(colours.muted))
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "No preview")
    painter.end()
    return pixmap


def with_badge(pixmap: QPixmap) -> QPixmap:
    """``pixmap`` with the "Yours" mark of a user's preset in its corner."""
    colours = theme.THEME
    marked = QPixmap(pixmap)
    painter = QPainter(marked)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    font = painter.font()
    font.setBold(True)
    painter.setFont(font)
    metrics = painter.fontMetrics()
    width, height = metrics.horizontalAdvance(BADGE_TEXT) + 12, metrics.height() + 2
    box = QRectF(marked.width() - width - 4, 4, width, height)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(theme.qcolor(colours.accent))
    painter.drawRoundedRect(box, theme.RADIUS, theme.RADIUS)
    painter.setPen(theme.qcolor(colours.on_accent))
    painter.drawText(box, Qt.AlignmentFlag.AlignCenter, BADGE_TEXT)
    painter.end()
    return marked


def card_icon(pixmap: QPixmap) -> QIcon:
    """An icon that looks the same selected (Qt would tint it with the highlight colour)."""
    icon = QIcon()
    for mode in (QIcon.Mode.Normal, QIcon.Mode.Selected, QIcon.Mode.Active):
        icon.addPixmap(pixmap, mode)
    return icon


def grid_style(c: theme.Colours | None = None) -> str:
    """The cards' look, from the tokens (Lumen: a recessed grid of rounded cards; the chosen one is
    tinted with the accent and ringed, as a selected layer row is)."""
    c = c or theme.THEME
    r, s = theme.RADIUS_ROW, theme.SPACE
    return f"""
QListView#presetGrid {{
    background: {c.field}; padding: {2 * s}px; border: 1px solid {theme.css(c.line)};
    border-radius: {theme.RADIUS_CARD}px;
}}
QListView#presetGrid::item {{
    border-radius: {r}px; padding: {s}px; color: {c.text}; border: 1px solid transparent;
}}
QListView#presetGrid::item:hover {{ background: {c.raised}; border-color: {theme.css(c.line)}; }}
QListView#presetGrid::item:selected {{
    background: {theme.css(c.accent_soft)}; color: {c.text}; border-color: {theme.css(c.accent_line)};
}}
QLineEdit#presetSearch {{ min-height: 24px; }}
"""


theme.register_rules(grid_style)


class PresetGrid(QListWidget):
    """The cards: tells which one the pointer is over, and when it left."""

    hovered = Signal(object)  # the QListWidgetItem under the pointer, or None
    applyRequested = Signal(object)  # a card double-clicked, or Enter on the current one

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("presetGrid")
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setMovement(QListView.Movement.Static)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setUniformItemSizes(True)
        self.setWordWrap(True)
        self.setSpacing(theme.SPACE)
        self.setIconSize(QSize(preset_thumbs.WIDTH, preset_thumbs.HEIGHT))
        self.setGridSize(CARD)
        self.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.viewport().setMouseTracking(True)
        self.itemDoubleClicked.connect(lambda item: self.applyRequested.emit(item))

    def viewportEvent(self, event: QEvent) -> bool:
        if event.type() == QEvent.Type.MouseMove:
            self.hovered.emit(self.itemAt(event.position().toPoint()))
        elif event.type() == QEvent.Type.Leave:
            self.hovered.emit(None)
        return super().viewportEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        item = self.currentItem()
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and item is not None:
            self.applyRequested.emit(item)
            return
        super().keyPressEvent(event)


class PresetsBrowser(QDialog):
    """The presets browser. ``editor`` is the main window (its ``library``, ``selection`` and
    ``apply_preset``); the dialog is not modal and is kept by the window between openings."""

    def __init__(self, editor) -> None:
        super().__init__(editor)
        self.editor = editor
        self.setWindowTitle("Presets")
        self.resize(760, 540)
        self.fixed_layer: str | None = None  # a layer and time from the timeline row's menu
        self.fixed_time: float | None = None
        self.playing: str | None = None  # the name of the card that is playing
        self.frame = 0  # the frame it shows
        self._presets: list[library.Preset] = []
        self._user: set[str] = set()
        self._pixmaps: dict[tuple[str, bool], list[QPixmap]] = {}

        self.search = QLineEdit()
        self.search.setObjectName("presetSearch")
        self.search.addAction(icons.icon("search", tint="faint"), QLineEdit.ActionPosition.LeadingPosition)
        self.search.setPlaceholderText("Search presets by name or description")
        self.search.setClearButtonEnabled(True)
        self.search.setToolTip("Only the presets whose name or description has every word typed")
        self.search.textChanged.connect(self._refill)
        self.tabs = QTabBar()
        self.tabs.setDrawBase(False)
        self.tabs.setExpanding(False)
        for title, category in TABS:
            self.tabs.setTabData(self.tabs.addTab(title), category)
        self.tabs.currentChanged.connect(self._refill)
        self.grid = PresetGrid()
        self.grid.hovered.connect(self._hover)
        self.grid.applyRequested.connect(self._apply_item)
        self.grid.currentItemChanged.connect(self._on_current)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setProperty("role", "muted")
        self.apply_button = QPushButton("Apply")
        self.apply_button.setToolTip("Put the chosen preset on the selected layers (one undo step)")
        self.apply_button.setAutoDefault(False)
        self.apply_button.setProperty("role", "primary")  # the one primary action of the dialog
        self.apply_button.clicked.connect(self.apply_current)
        self.close_button = QPushButton("Close")
        self.close_button.setToolTip("Close the browser; what was applied stays")
        self.close_button.setAutoDefault(False)
        self.close_button.setProperty("role", "ghost")
        self.close_button.clicked.connect(self.close)

        # Lumen dialog: the search and the tabs on top, the cards, then the status and the actions
        # (right-aligned, the primary last).
        head = QHBoxLayout()
        head.setSpacing(3 * theme.SPACE)
        head.addWidget(self.tabs, 1)
        head.addWidget(self.search, 1)
        buttons = QHBoxLayout()
        buttons.setSpacing(2 * theme.SPACE)
        buttons.addWidget(self.status, 1)
        buttons.addWidget(self.close_button)
        buttons.addWidget(self.apply_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(3 * theme.SPACE)
        layout.addLayout(head)
        layout.addWidget(self.grid, 1)
        layout.addLayout(buttons)

        self.timer = QTimer(self)
        self.timer.setInterval(FRAME_MS)
        self.timer.timeout.connect(self._tick)
        editor.selection.changed.connect(self._update_hint)
        self.reload()

    # -- what is shown ---------------------------------------------------------------------

    @property
    def category(self) -> str | None:
        """The category of the tab shown (None: All)."""
        return self.tabs.tabData(self.tabs.currentIndex())

    def reload(self) -> None:
        """Read the window's library again and draw the thumbnails of any preset not yet drawn
        (the frames are kept per preset, so this costs nothing for unchanged ones)."""
        self._presets = list(self.editor.library.presets)
        self._user = {p.name for p in self._presets if is_user_preset(p)}
        self._refill()

    def names(self) -> list[str]:
        """The names on the cards, in order."""
        return [self.grid.item(i).text() for i in range(self.grid.count())]

    def item(self, name: str) -> QListWidgetItem:
        """The card of preset ``name`` (``KeyError`` when it is not shown)."""
        for i in range(self.grid.count()):
            if self.grid.item(i).text() == name:
                return self.grid.item(i)
        raise KeyError(name)

    def _frames(self, preset: library.Preset) -> list[QPixmap]:
        user = preset.name in self._user
        key = (preset.model_dump_json(), user)
        if key not in self._pixmaps:
            frames = preset_thumbs.thumbnails(preset, thumb_background())
            pixmaps = [to_pixmap(f) for f in frames] or [placeholder()]
            self._pixmaps[key] = [with_badge(p) for p in pixmaps] if user else pixmaps
        return self._pixmaps[key]

    def _still(self, preset: library.Preset) -> QIcon:
        frames = self._frames(preset)
        return card_icon(frames[min(preset_thumbs.STILL, len(frames) - 1)])

    def _refill(self, *_args) -> None:
        self._stop()
        chosen = self.grid.currentItem().text() if self.grid.currentItem() is not None else None
        shown = filter_presets(self._presets, self.category, self.search.text())
        self.grid.clear()
        for preset in shown:
            item = QListWidgetItem(self._still(preset), preset.name)
            item.setToolTip(preset.description or preset.name)
            item.setData(PRESET_ROLE, preset)
            item.setData(USER_ROLE, preset.name in self._user)
            self.grid.addItem(item)
            if preset.name == chosen:
                self.grid.setCurrentItem(item)
        self.apply_button.setEnabled(self.grid.currentItem() is not None)
        if shown:
            self._update_hint()
        else:
            self.status.setText("No presets match" if self._presets else "There are no presets")

    # -- hover: the preset plays ------------------------------------------------------------

    def _hover(self, item: QListWidgetItem | None) -> None:
        if item is None:
            self._stop()
        elif item.text() != self.playing:
            self._stop()
            frames = self._frames(item.data(PRESET_ROLE))
            if len(frames) > 1:  # a card with no preview stays still
                self.playing, self.frame = item.text(), 0
                item.setIcon(card_icon(frames[0]))
                self.timer.start()

    def _tick(self) -> None:
        """Show the next frame of the playing card (the run repeats)."""
        if self.playing is None:
            self.timer.stop()
            return
        item = self.item(self.playing)
        frames = self._frames(item.data(PRESET_ROLE))
        self.frame = (self.frame + 1) % len(frames)
        item.setIcon(card_icon(frames[self.frame]))

    def _stop(self) -> None:
        """Stop playing and put the still back."""
        self.timer.stop()
        name, self.playing = self.playing, None
        if name is not None:
            try:
                item = self.item(name)
            except KeyError:
                return
            item.setIcon(self._still(item.data(PRESET_ROLE)))

    def hideEvent(self, event) -> None:
        self._stop()
        super().hideEvent(event)

    # -- applying -------------------------------------------------------------------------------

    def set_target(self, layer_id: str | None, at: float | None) -> None:
        """Apply to one layer at a time (from the timeline row), or to the selection at the
        playhead (both None)."""
        self.fixed_layer, self.fixed_time = layer_id, at
        self._update_hint()

    def _layer_names(self) -> list[str]:
        project = self.editor.project
        if project is None:
            return []
        ids = [self.fixed_layer] if self.fixed_layer else list(self.editor.selection.layer_ids)
        present = {layer.id: layer for layer in project.layers}
        return [present[i].name or i for i in ids if i in present]

    def _update_hint(self) -> None:
        if self.grid.count() == 0 and self._presets:
            return  # "No presets match" stays until the search changes
        names = self._layer_names()
        if self.fixed_layer is not None and not names:  # the row's layer is gone: the selection again
            self.fixed_layer = self.fixed_time = None
            names = self._layer_names()
        self.status.setText(target_text(names, self.fixed_time, self.fixed_layer is not None))

    def _on_current(self, *_args) -> None:
        self.apply_button.setEnabled(self.grid.currentItem() is not None)

    def apply_current(self) -> bool:
        """Apply the chosen card; the dialog's line says what happened."""
        item = self.grid.currentItem()
        if item is None:
            self.status.setText("Choose a preset first")
            return False
        return self._apply_item(item)

    def _apply_item(self, item: QListWidgetItem) -> bool:
        preset = item.data(PRESET_ROLE)
        if self.fixed_layer is not None and not self._layer_names():  # deleted since the menu
            self.set_target(None, None)
            self.status.setText("That layer is gone: select the layers to animate")
            return False
        applied = self.editor.apply_preset(preset, self.fixed_layer, self.fixed_time)
        self.status.setText(self.editor.statusBar().currentMessage())
        return applied
