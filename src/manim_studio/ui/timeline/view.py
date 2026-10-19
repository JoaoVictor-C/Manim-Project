"""The timeline widget (S1.4, S1.5): rows, clip bars, ruler, playhead, drags.

A thin Qt layer over ``timeline.model`` (geometry and drag rules) and the
``Document`` (snapshots and undo):

* one row per layer, front-most layer on top (as in the Layers panel), with its
  lifetime band and clip bars coloured by category;
* the ruler at the top scrubs the playhead (``seekRequested``);
* dragging a clip's body moves it, dragging within ``EDGE_PX`` of an edge trims it;
  Alt disables snapping, Escape cancels, release records one undo step;
* mouse moves are coalesced: only the latest position is applied per event-loop
  turn, so a slow frame drops positions instead of queueing them (ADR 0009);
* Ctrl+wheel zooms about the cursor;
* right-click adds a clip at that time (or deletes the clip under the cursor);
  Delete removes the selected clip (S2.6);
* keyframes (P2b): one diamond per key time on the bottom of the row; click
  selects, drag retimes every key at that time, Delete removes them; the row
  menu adds a key at the playhead. Diamonds win over clip bars within 5 px.
* subtitles (P5a, ADR 0035): one row under the layers with a bar per cue showing
  its text; drag to move, drag an edge to trim (cues never overlap), Delete or
  the row menu removes one, the row menu adds one where it was clicked;
* sounds (P4d, ADR 0034): one row per sound under the subtitles, with its waveform;
  drag to move, drag an edge to trim (the left edge trims the file's start),
  Delete or the row menu removes it.
* property rows (P7.3, ADR 0047): the arrow by a row's name (or Alt+click on the name)
  expands it into one sub-row per property it can key, each with its value at the
  playhead, a diamond that adds or removes that property's key there, and that
  property's keys - dragged, deleted and eased alone. A click on a property's name
  chooses it for the graph (Shift/Ctrl add); expanded rows are editor state.
* multi-selection (U4b): Shift/Ctrl+click toggles clips and keys into the picks, a drag from
  empty space draws a rubber band that picks what it touches, Ctrl+A picks every clip and key;
  dragging any picked item moves them all by one snapped delta (``shift_timing``, one undo
  step), Delete removes them all, Escape drops back to the primary one (the one Properties
  shows). The lifetime band of selected rows drags those layers whole. Editor state only.
"""

from __future__ import annotations

import contextlib
import threading
from bisect import bisect_right
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from pydantic import ValidationError
from PySide6.QtCore import QObject, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QKeySequence, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QFileDialog,
    QGraphicsPolygonItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QInputDialog,
    QMenu,
    QStyleOptionGraphicsItem,
    QWidget,
)

from ...core import adapter, audio, edits, scene_length, shift_timing, subtitles
from ...core.evaluator import layer_transform
from ...core.layer_index import LayerIndex
from ...core.schema import (
    CLIP_KIND_INFO,
    CODE_TYPES,
    CONNECTOR_TYPES,
    PART_PARENT_TYPES,
    TRACE_TYPES,
    AudioClip,
    Clip,
    Cue,
    Easing,
    Layer,
    Marker,
    Project,
    keyable_props,
    new_clip_params,
)
from ...logging_config import get_logger
from .. import curve_editor, graph_model, theme
from ..document import Document
from .model import (
    Edge,
    TimeScale,
    depth,
    drag_keys,
    drag_marker,
    drag_move,
    drag_trim,
    fit_scale,
    group_delta,
    key_times,
    obstacles,
    place_new_clip,
    snap,
    snap_candidates,
    snapped,
)

log = get_logger(__name__)

ROW_HEIGHT = 28
RULER_HEIGHT = 26
HEADER_WIDTH = 140
WIDE_HEADER_WIDTH = 200  # while a row is expanded: room for a property's name, value, diamond (P7.3)
SUB_ROW_HEIGHT = 22  # a property row under an expanded object (P7.3)
TWIRL_X = 9  # the expand arrow's middle in the header, at depth 0
TWIRL_GRAB = 7
NAME_X = 18  # a row's name starts after the arrow
KEY_BUTTON_X = WIDE_HEADER_WIDTH - 14  # a property row's diamond: add or remove its key at the playhead
KEY_BUTTON_GRAB = 8
PROP_LABELS = {"position": "Position", "scale": "Scale", "rotation": "Rotation", "opacity": "Opacity"}
FIT_MIN_WIDTH = 200  # narrower: not laid out yet, the fit waits
INDENT_PX = 14  # per level of part layers (ADR 0012)
EDGE_PX = 6
CLIP_MARGIN = 4
KEY_HALF = 4.5  # diamond half size, px
KEY_GRAB_PX = 5.0
KEY_OFFSET = ROW_HEIGHT - 6  # diamond centre below the row top
TRANSFORM_PROPS = ("position", "scale", "rotation", "opacity")

CATEGORY_COLORS = {  # clip categories (ADR 0022), from the theme (ADR 0040)
    "content": theme.THEME.content,
    "emphasis": theme.THEME.emphasis,
    "motion": theme.THEME.motion,
    "morph": theme.THEME.morph,
}
AUDIO_COLOR = theme.qcolor(theme.THEME.sound)
CUE_COLOR = theme.qcolor(theme.THEME.cue)
WAVE_COLOR = theme.qcolor(theme.THEME.wave)
PEAKS_PER_SECOND = 100
# a shorter sound's waveform is made at once (~0.1 s), a longer one in the background (B70)
SYNC_PEAKS_SECONDS = 60.0
LIFETIME_COLOR = theme.qcolor(theme.THEME.lifetime)
PLAYHEAD_COLOR = theme.qcolor(theme.THEME.playhead)
BACKGROUND = theme.qcolor(theme.THEME.track)
RULER_BACKGROUND = theme.qcolor(theme.THEME.ruler)
TEXT_COLOR = theme.qcolor(theme.THEME.text)
BAR_TEXT = theme.qcolor(theme.THEME.bar_text)
SELECTED_EDGE = theme.qcolor(theme.THEME.bar_selected)
BAR_EDGE = theme.qcolor(theme.THEME.bar_edge)
KEY_COLOR = theme.qcolor(theme.THEME.key)
KEY_SELECTED = theme.qcolor(theme.THEME.key_selected)
KEY_EDGE = theme.qcolor(theme.THEME.key_edge)
MARKER_GRAB_PX = 6.0  # how near a marker's line a ruler click picks it (ADR 0037)
GUIDE_COLOR = theme.qcolor(theme.THEME.guide)  # the line a snapped drag rests on
END_COLOR = GUIDE_COLOR  # the scene's end on the timeline, draggable (P7.1)
SHADE_COLOR = QColor(RULER_BACKGROUND)  # past the scene's end
SHADE_COLOR.setAlpha(150)
MUTED_COLOR = theme.qcolor(theme.THEME.muted)
SUB_BAND = QColor(RULER_BACKGROUND)  # behind a property row (P7.3)
SUB_BAND.setAlpha(110)
SUB_CHOSEN = theme.qcolor(theme.THEME.accent)  # behind a property row chosen for the graph
SUB_CHOSEN.setAlpha(70)
RUBBER_FILL = QColor(SELECTED_EDGE)  # the rubber band being drawn (U4b)
RUBBER_FILL.setAlpha(40)
RUBBER_PX = 4  # a press on empty space moved further than this draws a rubber band


def _number(value: float) -> str:
    return f"{round(float(value), 2) + 0.0:g}"


def format_value(prop: str, value) -> str:
    """A property's value as a property row shows it: x, y; scale; degrees; percent."""
    if prop == "position":
        return f"{_number(value[0])}, {_number(value[1])}"
    if prop == "rotation":
        return f"{_number(value)}\u00b0"
    if prop == "opacity":
        return f"{round(float(value) * 100) + 0:g}%"
    return _number(value)


@dataclass
class _Layout:
    """Where the layer rows are: each one's top (scene y) and the property rows under it."""

    tops: list[float] = field(default_factory=list)
    subs: list[tuple[str, ...]] = field(default_factory=list)  # empty: collapsed
    bottom: float = RULER_HEIGHT  # under the last layer row: the Subtitles row


class ClipItem(QGraphicsRectItem):
    def __init__(self, layer_id: str, clip: Clip, rect: QRectF, selected: bool) -> None:
        super().__init__(rect)
        self.layer_id, self.clip_id, self.kind = layer_id, clip.id, clip.kind
        self.selected = selected
        self.setBrush(QBrush(theme.qcolor(CATEGORY_COLORS[clip.info.category])))
        self.setPen(QPen(SELECTED_EDGE if selected else BAR_EDGE, 2 if selected else 1))
        self.setZValue(2)

    def paint(
        self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None
    ) -> None:
        rect = self.rect()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(self.brush())
        painter.setPen(self.pen())
        painter.drawRoundedRect(rect, 4, 4)
        if rect.width() > 24:
            painter.setPen(BAR_TEXT)
            painter.drawText(rect.adjusted(6, 0, -4, 0), Qt.AlignmentFlag.AlignVCenter, self.kind)


class BandItem(QGraphicsRectItem):
    """A layer's lifetime band, behind its clips; a selected row's band drags the layer (U4b)."""

    def __init__(self, layer_id: str, rect: QRectF, selected: bool) -> None:
        super().__init__(rect)
        self.layer_id = layer_id
        self.setPen(QPen(SELECTED_EDGE, 1) if selected else QPen(Qt.PenStyle.NoPen))
        self.setBrush(QBrush(LIFETIME_COLOR))
        self.setZValue(1)


class _PeaksLoader(QObject):
    """Scans long sounds for their waveforms on a background thread (B70): the first sync of a
    15-minute sound no longer decodes it on the GUI thread; its row is flat until ``ready``."""

    ready = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.busy: set[str] = set()  # paths being scanned; the view takes them out when ready

    def request(self, path: str) -> None:
        if path not in self.busy:
            self.busy.add(path)
            threading.Thread(target=self._scan, args=(path,), daemon=True).start()

    def _scan(self, path: str) -> None:
        try:
            audio.scan(path)
        finally:
            with contextlib.suppress(RuntimeError):  # the timeline was closed meanwhile
                self.ready.emit(path)


class AudioItem(QGraphicsRectItem):
    """A sound's bar (ADR 0034): its waveform over the part of the file it plays."""

    def __init__(self, clip: AudioClip, rect: QRectF, peaks, selected: bool) -> None:
        super().__init__(rect)
        self.audio_id, self.name = clip.id, clip.name or clip.id
        self.peaks, self.selected = peaks, selected
        self.setPen(QPen(SELECTED_EDGE if selected else BAR_EDGE, 2 if selected else 1))
        self.setZValue(2)

    def paint(
        self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None
    ) -> None:
        rect = self.rect()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(AUDIO_COLOR)
        painter.setPen(self.pen())
        painter.drawRoundedRect(rect, 4, 4)
        if len(self.peaks):
            painter.setPen(QPen(WAVE_COLOR, 1))
            middle, half = rect.center().y(), rect.height() / 2 - 2
            columns = max(1, int(rect.width()))
            for i in range(columns):
                peak = float(self.peaks[min(len(self.peaks) - 1, i * len(self.peaks) // columns)])
                x = rect.left() + i + 0.5
                painter.drawLine(QPointF(x, middle - peak * half), QPointF(x, middle + peak * half))
        if rect.width() > 24:
            painter.setPen(BAR_TEXT)
            painter.drawText(rect.adjusted(6, 0, -4, 0), Qt.AlignmentFlag.AlignVCenter, self.name)


class CueItem(QGraphicsRectItem):
    """A subtitle's bar (ADR 0035), showing its text."""

    def __init__(self, cue: Cue, rect: QRectF, selected: bool) -> None:
        super().__init__(rect)
        self.cue_id, self.text = cue.id, " ".join(cue.text.split())
        self.setPen(QPen(SELECTED_EDGE if selected else BAR_EDGE, 2 if selected else 1))
        self.setToolTip(cue.text)
        self.setZValue(2)

    def paint(
        self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None
    ) -> None:
        rect = self.rect()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(CUE_COLOR)
        painter.setPen(self.pen())
        painter.drawRoundedRect(rect, 4, 4)
        if rect.width() > 24:
            painter.setPen(BAR_TEXT)
            label = painter.fontMetrics().elidedText(
                self.text, Qt.TextElideMode.ElideRight, int(rect.width() - 10)
            )
            painter.drawText(rect.adjusted(6, 0, -4, 0), Qt.AlignmentFlag.AlignVCenter, label)


class KeyItem(QGraphicsPolygonItem):
    """Every key of one layer at one time (P2b)."""

    prop: str | None = None  # every property keyed there

    def __init__(
        self, layer_id: str, t: float, props: tuple[str, ...], center: QPointF, selected: bool
    ) -> None:
        h = KEY_HALF
        diamond = QPolygonF([QPointF(0, -h), QPointF(h, 0), QPointF(0, h), QPointF(-h, 0)])
        super().__init__(diamond)
        self.setPos(center)
        self.layer_id, self.t, self.props, self.selected = layer_id, t, props, selected
        self.setBrush(QBrush(KEY_SELECTED if selected else KEY_COLOR))
        self.setPen(QPen(SELECTED_EDGE if selected else KEY_EDGE, 1.5 if selected else 1))
        self.setToolTip(f"{t:g} s: {', '.join(props)}")
        self.setZValue(3)


class PropKeyItem(KeyItem):
    """One property's key, on its property row (P7.3)."""

    def __init__(self, layer_id: str, t: float, prop: str, center: QPointF, selected: bool) -> None:
        super().__init__(layer_id, t, (prop,), center, selected)
        self.prop = prop


@dataclass
class _KeyDrag:
    layer_id: str
    t: float
    press_x: float
    base: Project
    prop: str | None = None  # one property's key (P7.3); None: every key at that time


class LayerHeader(QWidget):
    """Layer names, drawn in the view's left margin and scrolled with the rows."""

    def __init__(self, view: TimelineView) -> None:
        super().__init__(view)
        self._view = view

    def mousePressEvent(self, event) -> None:
        """A click on a name selects that object (Shift or Ctrl adds), a sound's name that sound;
        the arrow (or Alt+click) expands an object into its property rows, where a click on a
        name chooses that property and one on the diamond keys it at the playhead (P7.3)."""
        view = self._view
        if event.button() != Qt.MouseButton.LeftButton or view.project is None:
            super().mousePressEvent(event)
            return
        pos = event.position()
        if pos.y() < RULER_HEIGHT:
            return
        modifiers = event.modifiers()
        extend = bool(modifiers & (Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.ControlModifier))
        where = view.locate(pos.y() + view.verticalScrollBar().value())
        if where is None:
            return
        kind, row, sub = where
        rows = view.rows()
        if kind == "layer":
            layer = rows[row]
            twirl = INDENT_PX * depth(view.project, layer, view.layer_index()) + TWIRL_X
            if abs(pos.x() - twirl) <= TWIRL_GRAB or modifiers & Qt.KeyboardModifier.AltModifier:
                view.toggle_expanded(layer.id)
            else:
                view.pick_layer(layer.id, extend)
        elif kind == "prop":
            layer, prop = rows[row], view.layout().subs[row][sub]
            if abs(pos.x() - KEY_BUTTON_X) <= KEY_BUTTON_GRAB:
                view.toggle_key(layer.id, prop)
            else:
                view.pick_prop(layer.id, prop, extend)
        elif kind == "audio":
            view.select_audio_row(view.project.audio[row].id)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), RULER_BACKGROUND)
        view = self._view
        project = view.project
        if project is None:
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = view.header_width
        scroll = view.verticalScrollBar().value()
        rows = view.rows()
        index = view.layer_index()
        layout = view.layout()
        first = max(0, bisect_right(layout.tops, scroll + RULER_HEIGHT) - 1)
        for row in range(first, len(rows)):
            top = layout.tops[row] - scroll
            if top > self.height():
                break
            layer = rows[row]
            indent = INDENT_PX * depth(project, layer, index)
            self._draw_twirl(painter, indent + TWIRL_X, top + ROW_HEIGHT / 2, bool(layout.subs[row]))
            text = layer.label
            if indent:
                text = "\u21b3 " + text
            painter.setPen(TEXT_COLOR)
            rect = QRectF(NAME_X + indent, top, width - NAME_X - 4 - indent, ROW_HEIGHT)
            painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter, text)
            for i, prop in enumerate(layout.subs[row]):
                self._draw_prop_row(painter, layer, prop, indent, top + ROW_HEIGHT + i * SUB_ROW_HEIGHT)
        painter.setPen(TEXT_COLOR)
        y = layout.bottom - scroll  # the subtitles (ADR 0035)
        if y + ROW_HEIGHT >= RULER_HEIGHT:
            painter.drawText(QRectF(8, y, width - 12, ROW_HEIGHT), Qt.AlignmentFlag.AlignVCenter, "Subtitles")
        for i, clip in enumerate(project.audio):  # sounds under the subtitles (ADR 0034)
            y = layout.bottom + (1 + i) * ROW_HEIGHT - scroll
            if y + ROW_HEIGHT >= RULER_HEIGHT:
                rect = QRectF(8, y, width - 12, ROW_HEIGHT)
                painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter, "\u266a " + (clip.name or clip.id))
        painter.fillRect(0, 0, width, RULER_HEIGHT, RULER_BACKGROUND)

    @staticmethod
    def _draw_twirl(painter: QPainter, x: float, y: float, expanded: bool) -> None:
        """The arrow that expands a row: pointing right when closed, down when open."""
        h = 3.5
        if expanded:
            shape = [QPointF(x - h, y - h / 2), QPointF(x + h, y - h / 2), QPointF(x, y + h)]
        else:
            shape = [QPointF(x - h / 2, y - h), QPointF(x + h, y), QPointF(x - h / 2, y + h)]
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(MUTED_COLOR)
        painter.drawPolygon(QPolygonF(shape))
        painter.setBrush(Qt.BrushStyle.NoBrush)

    def _draw_prop_row(self, painter: QPainter, layer: Layer, prop: str, indent: float, y: float) -> None:
        """A property row's header: its name, its value at the playhead and its key diamond,
        filled when the property has a key on the playhead's frame."""
        view = self._view
        chosen = view.prop_layer == layer.id and prop in view.selected_props
        painter.fillRect(QRectF(0, y, view.header_width, SUB_ROW_HEIGHT), SUB_CHOSEN if chosen else SUB_BAND)
        left = NAME_X + indent + 8
        font = painter.font()
        painter.setPen(TEXT_COLOR)
        label = QRectF(left, y, 64, SUB_ROW_HEIGHT)
        painter.drawText(label, Qt.AlignmentFlag.AlignVCenter, PROP_LABELS[prop])
        small = QFont(font)
        small.setPointSizeF(max(font.pointSizeF() - 1, 7))
        painter.setFont(small)
        painter.setPen(MUTED_COLOR)
        value = QRectF(left + 60, y, KEY_BUTTON_X - KEY_BUTTON_GRAB - left - 62, SUB_ROW_HEIGHT)
        text = painter.fontMetrics().elidedText(
            view.value_text(layer, prop), Qt.TextElideMode.ElideLeft, int(max(value.width(), 0))
        )
        painter.drawText(value, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, text)
        painter.setFont(font)
        h, cx, cy = KEY_HALF, KEY_BUTTON_X, y + SUB_ROW_HEIGHT / 2
        keyed = view.keyed_at_playhead(layer, prop)
        painter.setPen(QPen(KEY_EDGE if keyed else MUTED_COLOR, 1))
        painter.setBrush(KEY_COLOR if keyed else Qt.BrushStyle.NoBrush)
        painter.drawPolygon(
            QPolygonF([QPointF(cx, cy - h), QPointF(cx + h, cy), QPointF(cx, cy + h), QPointF(cx - h, cy)])
        )
        painter.setBrush(Qt.BrushStyle.NoBrush)


@dataclass
class _CueDrag:
    cue_id: str
    mode: Edge | None  # None = move
    press_x: float
    base: Project
    cue: Cue


@dataclass
class _MarkerDrag:
    marker_id: str
    press_x: float
    base: Project
    marker: Marker
    last: float  # the last free frame it was dragged to (ADR 0037)


@dataclass
class _AudioDrag:
    audio_id: str
    mode: Edge | None  # None = move
    press_x: float
    base: Project
    clip: AudioClip


KeyPick = tuple  # (layer id, frame, property or None: every key there) - a picked key (U4b)


@dataclass
class _GroupDrag:
    """The picks (or whole selected layers) dragged by one of them (U4b)."""

    press_x: float
    base: Project
    anchors: list[float]  # the dragged item's times, which snap
    clips: frozenset  # picked at press
    keys: frozenset  # KeyPicks at press
    primary_key: tuple[str, float, str | None] | None  # the primary key at press: it follows
    layers: tuple[str, ...] = ()  # whole layers (their band dragged)
    row: str | None = None  # the band's row: a click without moving picks it
    extend: bool = False
    refused: str | None = None  # the last reason shown, said once


@dataclass
class _EmptyPress:
    """A press on empty row space: a click picks the row, a drag draws a rubber band (U4b)."""

    pos: QPointF  # viewport
    origin: QPointF  # scene
    extend: bool
    clips: set  # the picks before the band (Shift/Ctrl adds to them)
    keys: set
    primary: tuple  # (selected, selected_key, selected_key_prop) before the band
    banding: bool = False

    @property
    def layer(self) -> str | None:
        """The primary item's object before the band."""
        item = self.primary[0] or self.primary[1]
        return item[0] if item else None


@dataclass
class _Drag:
    layer_id: str
    clip_id: str
    mode: Edge | None  # None = move
    press_x: float  # scene x at press
    base: Project  # snapshot at press: neighbours and the clip as they were
    clip: Clip


class TimelineView(QGraphicsView):
    seekRequested = Signal(float)
    clipSelected = Signal(str, str)  # layer id, clip id
    keySelected = Signal(str, float)  # layer id, key time
    audioSelected = Signal(str)  # a sound's id (ADR 0034)
    subtitleSelected = Signal(str)  # a cue's id (ADR 0035)
    markerSelected = Signal(str)  # a marker's id (ADR 0037)
    layerPicked = Signal(
        str, bool
    )  # a row's name or empty space was clicked: layer id, add to selection (P7.1)
    propsSelected = Signal()  # the properties chosen for the graph changed (P7.3)
    message = Signal(str)  # refused edits, for the status bar

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.setBackgroundBrush(BACKGROUND)
        self.header_width = HEADER_WIDTH  # wider while a row is expanded (P7.3)
        self.setViewportMargins(HEADER_WIDTH, 0, 0, 0)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumHeight(RULER_HEIGHT + 2 * ROW_HEIGHT)
        self.header = LayerHeader(self)
        self.verticalScrollBar().valueChanged.connect(self.header.update)

        self.document: Document | None = None
        self._index: LayerIndex | None = None
        self._rows: list[Layer] = []
        # property rows (P7.3, ADR 0047): editor state, never saved in the project
        self.expanded: set[str] = set()  # objects whose rows show their properties
        self.prop_layer: str | None = None  # the object whose properties are chosen for the graph
        self.selected_props: tuple[str, ...] = ()  # those properties, in the order chosen
        self.selected_key_prop: str | None = None  # the selected key is this property's only
        self.edit_curve = curve_editor.edit_curve  # a key's custom ease; replaced in tests
        self._layout: _Layout | None = None
        self._layer_id: str | None = None  # the selected object, as the shared selection says
        self.scale = TimeScale(px_per_second=120.0)
        self.playhead = 0.0
        self.follow_playhead = True  # the view stays on the playhead (U3); View > Follow Playhead
        self.selected: tuple[str, str] | None = None
        self.selected_key: tuple[str, float] | None = None
        self.selected_audio: str | None = None
        self.selected_cue: str | None = None
        self.selected_marker: str | None = None
        # the multi-selection (U4b): editor state, never saved; the primary item (selected or
        # selected_key, the one Properties shows) is always one of the picks
        self.picked_clips: set[tuple[str, str]] = set()
        self.picked_keys: set[KeyPick] = set()
        self.picked_rows: tuple[str, ...] = ()  # the selected layers (their bands drag them whole)
        self.rubber: QRectF | None = None  # the rubber band being drawn, scene coordinates
        self._empty_press: _EmptyPress | None = None
        self._group_drag: _GroupDrag | None = None
        self.guide: float | None = None  # where a snapped drag rests (ADR 0037)
        # Fills an "Apply preset" menu for a row and a time (ADR 0039); set by the window.
        self.preset_menu = None
        self.browse_presets = None  # opens the presets browser for a row and a time (ADR 0044)
        self._marker_drag: _MarkerDrag | None = None
        self._drag: _Drag | None = None
        self._audio_drag: _AudioDrag | None = None
        self._cue_drag: _CueDrag | None = None
        self._key_drag: _KeyDrag | None = None
        self._last_key_t = 0.0
        self._scrubbing = False
        self._end_drag: Project | None = (
            None  # the scene's end dragged on the ruler: the project at press (P7.1)
        )
        self._pending: tuple[float, bool] | None = None  # (scene x, snapping)
        self._apply_scheduled = False
        self._peaks_loader = _PeaksLoader(self)
        self._peaks_loader.ready.connect(self._on_peaks_ready)  # queued: a bound method of the view

    # -- document ----------------------------------------------------------------

    @property
    def project(self) -> Project | None:
        return self.document.project if self.document is not None else None

    def set_document(self, document: Document) -> None:
        self.document = document
        document.changed.connect(lambda *_: self.sync())
        document.reset.connect(lambda *_: self._on_reset())
        self.sync()

    def _on_reset(self) -> None:
        self.selected = None
        self.selected_key = None
        self.selected_audio = None
        self.selected_cue = None
        self.selected_marker = None
        self.guide = None
        self._audio_drag = None
        self._cue_drag = None
        self._marker_drag = None
        self._drag = None
        self._key_drag = None
        self._group_drag = self._empty_press = self.rubber = None
        self.picked_clips, self.picked_keys, self.picked_rows = set(), set(), ()
        self.expanded.clear()
        self._layout = None
        self._fit_header()
        self.selected_key_prop = None
        if self.prop_layer is not None:
            self.prop_layer, self.selected_props = None, ()
            self.propsSelected.emit()
        self._fit_pending = True  # an opened project shows whole (P6d.4)
        self.fit_to_width()
        self.sync()

    def fit_to_width(self) -> None:
        """Zoom so the whole scene fills the visible width (View > Fit Timeline). Before the view
        has its real width, the fit waits for its first resize."""
        project = self.project
        width = self.viewport().width()
        if project is None or width < FIT_MIN_WIDTH or not self.isVisible():
            return
        self._fit_pending = False
        self.scale = fit_scale(project.canvas.duration, width)
        self.horizontalScrollBar().setValue(0)
        self.sync()

    def set_selected(self, layer_id: str | None, clip_id: str | None, key_time: float | None = None) -> None:
        """Highlight a clip or a key time chosen elsewhere (the shared selection), or none. One of
        the picks (the window echoing the primary) keeps the multi-selection; anything else
        replaces it (``sync``)."""
        if self._group_drag is not None:  # moved keys leave the shared selection mid-drag
            return
        selected = (layer_id, clip_id) if layer_id and clip_id else None
        selected_key = (layer_id, key_time) if layer_id and key_time is not None else None
        self._layer_id = layer_id
        dropped = self.prop_layer is not None and layer_id != self.prop_layer
        if dropped:  # another object: its properties were not chosen (P7.3)
            self.prop_layer, self.selected_props = None, ()
            self.propsSelected.emit()
        if selected_key != self.selected_key:
            self.selected_key_prop = None  # chosen elsewhere: every key at that time
        if (selected, selected_key) != (self.selected, self.selected_key) or dropped:
            self.selected, self.selected_key = selected, selected_key
            self.sync()

    def set_selected_layers(self, layer_ids) -> None:
        """The selected layers (the shared selection's ``layer_ids``): with no clip or key picked,
        their lifetime bands drag them whole (U4b)."""
        ids = tuple(layer_ids)
        if ids != self.picked_rows:
            self.picked_rows = ids
            self.sync()

    def rows_draggable(self) -> set[str]:
        """The layers whose band drags them: the selected rows, while no clip or key is picked."""
        if (
            self.selected is not None
            or self.selected_key is not None
            or self.picked_clips
            or self.picked_keys
        ):
            return set()
        return set(self.picked_rows)

    def set_selected_subtitle(self, cue_id: str | None) -> None:
        if cue_id != self.selected_cue:
            self.selected_cue = cue_id
            self.sync()

    def set_selected_marker(self, marker_id: str | None) -> None:
        if marker_id != self.selected_marker:
            self.selected_marker = marker_id
            self.viewport().update()

    def marker_at(self, viewport_x: float) -> Marker | None:
        """The marker whose line is nearest ``viewport_x`` within MARKER_GRAB_PX, if any."""
        if self.project is None:
            return None
        near = [(abs(self._viewport_x(m.t) - viewport_x), m) for m in self.project.markers]
        near = [(d, m) for d, m in near if d <= MARKER_GRAB_PX]
        return min(near, key=lambda dm: dm[0])[1] if near else None

    def subtitle_row_at(self, viewport_y: float) -> bool:
        """Whether this height is the Subtitles row."""
        if self.project is None or viewport_y < RULER_HEIGHT:
            return False
        where = self.locate(self.mapToScene(0, int(viewport_y)).y())
        return where is not None and where[0] == "subtitles"

    def set_selected_audio(self, audio_id: str | None) -> None:
        if audio_id != self.selected_audio:
            self.selected_audio = audio_id
            self.sync()

    def audio_at(self, viewport_y: float) -> AudioClip | None:
        """The sound whose row is at this height (rows under the layers)."""
        if self.project is None or viewport_y < RULER_HEIGHT:
            return None
        where = self.locate(self.mapToScene(0, int(viewport_y)).y())
        return self.project.audio[where[1]] if where is not None and where[0] == "audio" else None

    def layer_index(self) -> LayerIndex:
        """The current snapshot's tree maps, built once per snapshot (snapshots are replaced by
        edits, never changed in place) instead of one scan per layer and row (B66)."""
        project = self.project
        if project is None:
            raise ValueError("no document")
        if self._index is None or self._index.project is not project:
            self._index = LayerIndex(project)
            self._rows = self._index.rows()
            self._layout = None
        return self._index

    def rows(self) -> list[Layer]:
        """Layers in row order: the front-most object first, each followed by its parts."""
        if self.project is None:
            return []
        self.layer_index()
        return self._rows

    def row_of(self, layer_id: str) -> int:
        return [layer.id for layer in self.rows()].index(layer_id)

    def layer_at(self, viewport_y: float) -> Layer | None:
        """The object whose own row is at this height (not one of its property rows)."""
        if self.project is None or viewport_y < RULER_HEIGHT:
            return None
        where = self.locate(self.mapToScene(0, int(viewport_y)).y())
        return self.rows()[where[1]] if where is not None and where[0] == "layer" else None

    # -- property rows (P7.3, ADR 0047) ------------------------------------------------

    def layout(self) -> _Layout:
        """Each layer row's top and its property rows: one pass over the rows, kept until the
        snapshot or the expanded rows change."""
        self.layer_index()
        if self._layout is None:
            layout, y = _Layout(), float(RULER_HEIGHT)
            for layer in self._rows:
                subs = tuple(keyable_props(layer)) if layer.id in self.expanded else ()
                layout.tops.append(y)
                layout.subs.append(subs)
                y += ROW_HEIGHT + len(subs) * SUB_ROW_HEIGHT
            layout.bottom = y
            self._layout = layout
        return self._layout

    def locate(self, scene_y: float) -> tuple[str, int | None, int | None] | None:
        """What is at a scene height: ("layer", row, None), ("prop", row, property index),
        ("subtitles", None, None), ("audio", sound index, None), or None."""
        if self.project is None or scene_y < RULER_HEIGHT:
            return None
        layout = self.layout()
        if scene_y >= layout.bottom:
            below = int((scene_y - layout.bottom) // ROW_HEIGHT)
            if below == 0:
                return ("subtitles", None, None)
            return ("audio", below - 1, None) if below - 1 < len(self.project.audio) else None
        row = bisect_right(layout.tops, scene_y) - 1
        offset = scene_y - layout.tops[row]
        if offset < ROW_HEIGHT:
            return ("layer", row, None)
        return ("prop", row, min(int((offset - ROW_HEIGHT) // SUB_ROW_HEIGHT), len(layout.subs[row]) - 1))

    def row_top(self, layer_id: str) -> float:
        return self.layout().tops[self.row_of(layer_id)]

    def sub_rows(self, layer_id: str) -> tuple[str, ...]:
        """The properties an expanded object's rows show (those it can key, ADR 0024)."""
        return tuple(keyable_props(self.layer_index().layer(layer_id)))

    def prop_row_top(self, layer_id: str, prop: str) -> float:
        row = self.row_of(layer_id)
        layout = self.layout()
        return layout.tops[row] + ROW_HEIGHT + layout.subs[row].index(prop) * SUB_ROW_HEIGHT

    def prop_row_at(self, viewport_y: float) -> tuple[Layer, str] | None:
        """The object and property whose row is at this height."""
        if self.project is None or viewport_y < RULER_HEIGHT:
            return None
        where = self.locate(self.mapToScene(0, int(viewport_y)).y())
        if where is None or where[0] != "prop":
            return None
        return self.rows()[where[1]], self.layout().subs[where[1]][where[2]]

    def set_expanded(self, layer_id: str, expanded: bool) -> None:
        if (layer_id in self.expanded) == expanded:
            return
        (self.expanded.add if expanded else self.expanded.discard)(layer_id)
        self._layout = None
        self._fit_header()
        self.sync()

    def _fit_header(self) -> None:
        """The names column widens while any row is expanded, for the property rows' values;
        collapsed, the timeline is as it always was."""
        width = WIDE_HEADER_WIDTH if self.expanded else HEADER_WIDTH
        if width != self.header_width:
            self.header_width = width
            self.setViewportMargins(width, 0, 0, 0)
            self.header.setGeometry(0, 0, width, self.height())

    def toggle_expanded(self, layer_id: str) -> None:
        self.set_expanded(layer_id, layer_id not in self.expanded)

    def pick_prop(self, layer_id: str, prop: str, extend: bool = False) -> None:
        """Choose a property for the graph (``extend``: add it, or take it out again); a property
        of another object starts over. The object is selected with it."""
        if extend and self.prop_layer == layer_id:
            props = [p for p in self.selected_props if p != prop]
            if prop not in self.selected_props:
                props.append(prop)
        else:
            props = [prop]
        self.prop_layer = layer_id if props else None
        self.selected_props = tuple(props)
        if self._layer_id != layer_id:
            self.layerPicked.emit(layer_id, False)
            self._layer_id = layer_id
        self.propsSelected.emit()
        self.sync()

    def playhead_frame(self) -> float:
        fps = self.project.canvas.fps
        return round(self.playhead * fps) / fps

    def _key_on_playhead(self, layer: Layer, prop: str):
        t, half = self.playhead_frame(), 0.5 / self.project.canvas.fps
        return next((key for key in layer.tracks.get(prop, []) if abs(key.t - t) < half), None)

    def keyed_at_playhead(self, layer: Layer, prop: str) -> bool:
        return self._key_on_playhead(layer, prop) is not None

    def has_key_at_playhead(self, layer_id: str, prop: str) -> bool:
        return self.keyed_at_playhead(self.layer_index().layer(layer_id), prop)

    def value_text(self, layer: Layer, prop: str) -> str:
        return format_value(prop, getattr(layer_transform(layer, self.playhead), prop))

    def prop_value(self, layer_id: str, prop: str) -> str:
        """A property's value at the playhead, as its row shows it."""
        return self.value_text(self.layer_index().layer(layer_id), prop)

    def toggle_key(self, layer_id: str, prop: str) -> None:
        """A property row's diamond: key that property at the playhead's frame, holding the value
        played there, or remove its key there."""
        key = self._key_on_playhead(self.layer_index().layer(layer_id), prop)
        if key is not None:
            self.delete_keys(layer_id, key.t, [prop])
            return
        t = self.playhead_frame()
        before = self.project

        def op(project: Project) -> edits.Edit:
            value = getattr(layer_transform(project.layer(layer_id), t), prop)
            after = edits.set_key(project, layer_id, prop, t, value).project
            return edits.Edit(after, *edits.classify(before, after))

        self._apply(op, f"Add {prop} key")
        if self._key_on_playhead(self.layer_index().layer(layer_id), prop) is not None:
            self.selected, self.selected_key, self.selected_key_prop = None, (layer_id, t), prop
            self.sync()
            self.keySelected.emit(layer_id, t)

    def pick_layer(self, layer_id: str, extend: bool = False) -> None:
        """A row was clicked: select its object (``extend``: add it to the selection)."""
        self.selected = self.selected_key = self.selected_audio = self.selected_cue = None
        self.selected_marker = self.selected_key_prop = None
        self.layerPicked.emit(layer_id, extend)
        self.sync()

    # -- the multi-selection (U4b) ---------------------------------------------------------

    def _follow_primary(self, fps: int) -> set[tuple[str, int]]:
        """Keep the primary item among the picks: a primary that is not one of them (a plain
        click, or chosen elsewhere) replaces them, none clears them. Returns the picked keys'
        (layer, frame) lookups for drawing."""
        frames = {(layer_id, frame) for layer_id, frame, _ in self.picked_keys}
        if self.selected is not None:
            if self.selected not in self.picked_clips:
                self.picked_clips, self.picked_keys, frames = {self.selected}, set(), set()
        elif self.selected_key is not None:
            layer_id, frame = self.selected_key[0], round(self.selected_key[1] * fps)
            if (layer_id, frame) not in frames:
                self.picked_clips, frames = set(), {(layer_id, frame)}
                self.picked_keys = {(layer_id, frame, self.selected_key_prop)}
        else:
            self.picked_clips, self.picked_keys, frames = set(), set(), set()
        return frames

    def picked_key_times(self) -> set[tuple[str, float, str | None]]:
        """The picked keys as (layer, time, property or None)."""
        fps = self.project.canvas.fps
        return {(layer_id, frame / fps, prop) for layer_id, frame, prop in self.picked_keys}

    def picked_count(self) -> int:
        return len(self.picked_clips) + len(self.picked_keys)

    def _say_count(self) -> None:
        """'3 clips, 2 keys selected' in the status bar, for two picks or more."""
        clips, keys = len(self.picked_clips), len(self.picked_keys)
        if clips + keys < 2:
            return
        parts = [f"{n} {word}{'s' if n != 1 else ''}" for n, word in ((clips, "clip"), (keys, "key")) if n]
        self.message.emit(", ".join(parts) + " selected")

    def _key_pick(self, key: KeyItem) -> KeyPick:
        return (key.layer_id, round(key.t * self.project.canvas.fps), key.prop)

    def _make_primary(self, clip: tuple[str, str] | None = None, key: KeyPick | None = None) -> None:
        """Make one of the picks the primary item and tell the shared selection (Properties shows
        it); with neither, the primary goes and the object stays selected."""
        fps = self.project.canvas.fps
        if clip is not None:
            self.selected, self.selected_key, self.selected_key_prop = clip, None, None
            self.sync()
            self.clipSelected.emit(*clip)
        elif key is not None:
            layer_id, frame, prop = key
            self.selected, self.selected_key, self.selected_key_prop = None, (layer_id, frame / fps), prop
            self.sync()
            self.keySelected.emit(layer_id, frame / fps)
        else:
            layer_id = (
                self.selected[0] if self.selected else self.selected_key[0] if self.selected_key else None
            )
            self.selected = self.selected_key = self.selected_key_prop = None
            self.sync()
            if layer_id is not None:
                self.layerPicked.emit(layer_id, False)

    def _another_primary(self) -> None:
        """The primary was taken out: another pick takes its place (or none)."""
        if self.picked_clips:
            self._make_primary(clip=min(self.picked_clips))
        elif self.picked_keys:
            self._make_primary(key=min(self.picked_keys, key=lambda k: (k[0], k[1], k[2] or "")))
        else:
            self._make_primary()

    def toggle_clip_pick(self, layer_id: str, clip_id: str) -> None:
        """Shift/Ctrl+click on a clip: add it to the picks (it becomes the primary) or take it out."""
        clip = (layer_id, clip_id)
        if clip in self.picked_clips:
            self.picked_clips.discard(clip)
            if self.selected == clip:
                self._another_primary()
            else:
                self.sync()
        else:
            self.picked_clips.add(clip)
            self._make_primary(clip=clip)
        self._say_count()

    def toggle_key_pick(self, pick: KeyPick) -> None:
        """Shift/Ctrl+click on a key diamond (or a property's key): add it or take it out."""
        layer_id, frame, _prop = pick
        covering = {(layer_id, frame, None), pick} & self.picked_keys
        if covering:
            self.picked_keys -= covering
            fps = self.project.canvas.fps
            primary = self.selected_key
            if primary is not None and (primary[0], round(primary[1] * fps)) == (layer_id, frame):
                if not any(k[:2] == (layer_id, frame) for k in self.picked_keys):
                    self._another_primary()
                else:
                    self.sync()
            else:
                self.sync()
        else:
            self.picked_keys.add(pick)
            self._make_primary(key=pick)
        self._say_count()

    def select_all_items(self) -> None:
        """Ctrl+A: pick every clip and key diamond."""
        project = self.project
        if project is None:
            return
        fps = project.canvas.fps
        self.picked_clips = {(layer.id, c.id) for layer in project.layers for c in layer.clips}
        self.picked_keys = {
            (layer.id, round(t * fps), None) for layer in project.layers for t, _ in key_times(layer, fps)
        }
        frames = {(layer_id, frame) for layer_id, frame, _ in self.picked_keys}
        if self.selected in self.picked_clips or (
            self.selected_key is not None
            and (self.selected_key[0], round(self.selected_key[1] * fps)) in frames
        ):
            self.sync()
        elif self.picked_clips or self.picked_keys:
            self._another_primary()
        self._say_count()

    def collapse_picks(self) -> None:
        """Escape: drop the multi-selection down to the primary item."""
        if self.picked_count() < 2:
            return
        fps = self.project.canvas.fps
        if self.selected is not None:
            self.picked_clips, self.picked_keys = {self.selected}, set()
        elif self.selected_key is not None:
            layer_id, frame = self.selected_key[0], round(self.selected_key[1] * fps)
            self.picked_clips = set()
            self.picked_keys = {k for k in self.picked_keys if k[:2] == (layer_id, frame)}
        self.sync()

    def timing_selection(self, clips=None, keys=None, layers: tuple[str, ...] = ()) -> shift_timing.Selection:
        """The picks as the timing edits want them: a property's key under a picked diamond (every
        key at that time) is not listed twice; several properties at one time share one entry."""
        clips = self.picked_clips if clips is None else clips
        keys = self.picked_keys if keys is None else keys
        fps = self.project.canvas.fps
        whole = {(layer_id, frame) for layer_id, frame, prop in keys if prop is None}
        props: dict[tuple[str, int], set[str]] = {}
        for layer_id, frame, prop in keys:
            if prop is not None and (layer_id, frame) not in whole:
                props.setdefault((layer_id, frame), set()).add(prop)
        picks = [(layer_id, frame / fps, None) for layer_id, frame in sorted(whole)]
        picks += [(layer_id, frame / fps, tuple(sorted(p))) for (layer_id, frame), p in sorted(props.items())]
        return shift_timing.Selection(layers=tuple(layers), clips=tuple(sorted(clips)), keys=tuple(picks))

    def delete_picks(self) -> None:
        """Delete every picked clip and key in one undo step."""
        before = self.project
        selection = self.timing_selection()
        self._apply(lambda p: shift_timing.remove_items(p, selection), "Delete selection")
        if self.project is not before:
            self._make_primary()

    def _band_hit(self, pos: QPointF) -> BandItem | None:
        """The lifetime band of a draggable (selected) row under the cursor, if any."""
        draggable = self.rows_draggable()
        if not draggable:
            return None
        return next(
            (i for i in self.items(pos.toPoint()) if isinstance(i, BandItem) and i.layer_id in draggable),
            None,
        )

    def _begin_group_drag(
        self,
        pos: QPointF,
        anchors: list[float],
        layers: tuple[str, ...] = (),
        row: str | None = None,
        extend=False,
    ) -> None:
        primary_key = None
        if self.selected_key is not None:
            primary_key = (self.selected_key[0], self.selected_key[1], self.selected_key_prop)
        self._group_drag = _GroupDrag(
            self.mapToScene(pos.toPoint()).x(),
            self.project,
            anchors,
            frozenset(self.picked_clips),
            frozenset(self.picked_keys),
            primary_key,
            layers,
            row,
            extend,
        )
        self.document.begin_preview()

    def _update_rubber(self, viewport_pos: QPointF) -> None:
        """Grow the rubber band to the cursor and pick every clip and key diamond it touches."""
        press = self._empty_press
        current = self.mapToScene(viewport_pos.toPoint())
        self.rubber = QRectF(press.origin, QPointF(current)).normalized()
        clips = set(press.clips) if press.extend else set()
        keys = set(press.keys) if press.extend else set()
        fps = self.project.canvas.fps
        for item in self.scene().items(self.rubber):
            if isinstance(item, ClipItem):
                clips.add((item.layer_id, item.clip_id))
            elif isinstance(item, KeyItem):
                keys.add((item.layer_id, round(item.t * fps), item.prop))
        if (clips, keys) != (self.picked_clips, self.picked_keys):
            self.picked_clips, self.picked_keys = clips, keys
            frames = {k[:2] for k in keys}
            primary_ok = self.selected in clips or (
                self.selected_key is not None
                and (self.selected_key[0], round(self.selected_key[1] * fps)) in frames
            )
            if not primary_ok:  # the band's first find stands in until the release names it
                self.selected = min(clips) if clips else None
                self.selected_key, self.selected_key_prop = None, None
                if self.selected is None and keys:
                    layer_id, frame, prop = min(keys, key=lambda k: (k[0], k[1], k[2] or ""))
                    self.selected_key, self.selected_key_prop = (layer_id, frame / fps), prop
            self.sync()
        self.viewport().update()

    def _click_empty(self, press: _EmptyPress) -> None:
        """A click on empty space: a property row chooses that property (P7.3), a row its object
        (P7.1); Shift/Ctrl add."""
        prop_row = self.prop_row_at(press.pos.y())
        if prop_row is not None:
            self.pick_prop(prop_row[0].id, prop_row[1], press.extend)
            return
        layer = self.layer_at(press.pos.y())
        if layer is not None:
            self.pick_layer(layer.id, press.extend)

    def _finish_group_drag(self) -> None:
        """Drop the picks (or the layers) dragged: one undo step; a lifetime the move cut is
        warned about. A click without moving picks the clicked item (or the band's row) alone."""
        self.apply_pending()
        drag, self._group_drag = self._group_drag, None
        moved = self.project is not drag.base
        self.document.commit_preview("Move layers" if drag.layers else "Move selection")
        if not moved:
            if drag.row is not None:
                self.pick_layer(drag.row, drag.extend)
            else:
                self.collapse_picks()
            return
        old = set(shift_timing.timing_warnings(drag.base))
        new = [w for w in shift_timing.timing_warnings(self.project) if w not in old]
        if self.selected_key is not None:  # the moved primary key: the shared selection follows it
            self.keySelected.emit(*self.selected_key)
        if new:
            self.message.emit(f"{'Move layers' if drag.layers else 'Move selection'}: {new[0]}")

    def _finish_rubber(self, before: str | None) -> None:
        """The band is released: the shared selection learns the primary item (none found: the
        item picked before goes, its object stays selected)."""
        self.rubber = None
        if self.selected is not None:
            self._make_primary(clip=self.selected)
        elif self.selected_key is not None:
            layer_id, t = self.selected_key
            self._make_primary(key=(layer_id, round(t * self.project.canvas.fps), self.selected_key_prop))
        else:
            self.sync()
            if before is not None:  # the object of the item picked before the band
                self.layerPicked.emit(before, False)
        self._say_count()

    def select_audio_row(self, audio_id: str) -> None:
        self.selected = self.selected_key = self.selected_cue = self.selected_marker = None
        self.selected_audio = audio_id
        self.audioSelected.emit(audio_id)
        self.sync()

    def reach(self) -> float:
        """How far a drag may place things: the scene's end, or - when the scene grows with its
        content - as far as the timeline shows (the scene then grows when the drag is dropped)."""
        canvas = self.project.canvas
        if not canvas.grow_with_content:
            return canvas.duration
        shown = self.scale.t(self.mapToScene(self.viewport().width(), 0).x())
        return max(canvas.duration, shown)

    def _near_end(self, pos: QPointF) -> bool:
        """The ruler position is on the scene's end line (draggable)."""
        return (
            pos.y() < RULER_HEIGHT
            and abs(pos.x() - self._viewport_x(self.project.canvas.duration)) <= EDGE_PX
        )

    def sizeHint(self) -> QSize:
        return QSize(800, RULER_HEIGHT + 6 * ROW_HEIGHT + 2 * self.frameWidth() + 16)

    def set_playhead(self, t: float) -> None:
        self.playhead = t
        if self.follow_playhead:
            self._scroll_to_playhead()
        self.viewport().update()
        if self.expanded:  # the property rows show values at the playhead
            self.header.update()

    def _scroll_to_playhead(self) -> None:
        """Keep the playhead in view (U3): when it leaves, page the view so it sits a tenth in from
        the edge it left by. A view scrolled away by hand comes back on the next playhead move."""
        width = self.viewport().width()
        if width <= 0:
            return
        x = self._viewport_x(t := self.playhead)
        if 0 <= x <= width:
            return
        margin = width * 0.1
        bar = self.horizontalScrollBar()
        scene_x = self.scale.x(t)
        bar.setValue(round(scene_x - (margin if x > width else width - margin)))

    # -- scene -------------------------------------------------------------------

    def sync(self) -> None:
        """Rebuild the scene from the current snapshot (cheap: B11), in a new ``QGraphicsScene``:
        clearing the same scene got slower with every rebuild, in proportion to every item it had
        ever held (B68, inside PySide), so the old scene is dropped whole instead."""
        project = self.project
        if project is None:
            self.scene().clear()
            return
        width = self.scale.x(max(project.canvas.duration, scene_length.content_end(project)))
        fps = project.canvas.fps
        key_frames = self._follow_primary(fps)
        found_clips: set[tuple[str, str]] = set()  # picks still there (an undo can take them away)
        found_keys: set[tuple[str, int]] = set()
        draggable = self.rows_draggable()
        index = self.layer_index()
        rows = self.rows()
        layout = self.layout()
        height = layout.bottom + (1 + len(project.audio)) * ROW_HEIGHT
        scene = self._fresh_scene(QRectF(0, 0, width + 40, height))
        subtitle_top = layout.bottom
        for cue in project.subtitles:  # the Subtitles row (ADR 0035)
            rect = QRectF(
                self.scale.x(cue.start),
                subtitle_top + CLIP_MARGIN,
                max(2.0, self.scale.x(cue.end) - self.scale.x(cue.start)),
                ROW_HEIGHT - 2 * CLIP_MARGIN,
            )
            scene.addItem(CueItem(cue, rect, cue.id == self.selected_cue))
        for row, layer in enumerate(rows):
            top = layout.tops[row]
            start, end = index.lifetime(layer.id)
            end = min(end, project.canvas.duration)
            if end > start:
                band = QRectF(
                    self.scale.x(start), top + 2, self.scale.x(end) - self.scale.x(start), ROW_HEIGHT - 4
                )
                scene.addItem(BandItem(layer.id, band, layer.id in draggable))
            for clip in layer.clips:
                rect = QRectF(
                    self.scale.x(clip.start),
                    top + CLIP_MARGIN,
                    max(2.0, self.scale.x(clip.end) - self.scale.x(clip.start)),
                    ROW_HEIGHT - 2 * CLIP_MARGIN,
                )
                selected = (layer.id, clip.id) in self.picked_clips
                if selected:
                    found_clips.add((layer.id, clip.id))
                scene.addItem(ClipItem(layer.id, clip, rect, selected))
            for t, props in key_times(layer, fps):
                selected = (layer.id, round(t * fps)) in key_frames
                if selected:
                    found_keys.add((layer.id, round(t * fps)))
                center = QPointF(self.scale.x(t), top + KEY_OFFSET)
                scene.addItem(KeyItem(layer.id, t, props, center, selected))
            for i, prop in enumerate(layout.subs[row]):  # property rows (P7.3)
                self._add_prop_row(layer, prop, top + ROW_HEIGHT + i * SUB_ROW_HEIGHT, fps)
        for i, clip in enumerate(project.audio):
            top = layout.bottom + (1 + i) * ROW_HEIGHT
            rect = QRectF(
                self.scale.x(clip.start),
                top + CLIP_MARGIN,
                max(2.0, self.scale.x(clip.end) - self.scale.x(clip.start)),
                ROW_HEIGHT - 2 * CLIP_MARGIN,
            )
            peaks = self._peaks(clip.path)
            first = round(clip.offset * PEAKS_PER_SECOND)
            shown = peaks[first : first + round(clip.duration * PEAKS_PER_SECOND)]
            scene.addItem(AudioItem(clip, rect, _heard(shown, clip), clip.id == self.selected_audio))
        if len(found_clips) != len(self.picked_clips):
            self.picked_clips = found_clips
        if len(found_keys) != len(key_frames):
            self.picked_keys = {k for k in self.picked_keys if k[:2] in found_keys}
        self.header.update()
        self.viewport().update()

    def _on_peaks_ready(self, path: str) -> None:
        self._peaks_loader.busy.discard(path)
        self.sync()

    def _peaks(self, path: str) -> np.ndarray:
        """A sound's waveform peaks: at once for a short or scanned file; a long one is scanned in
        the background and shows a flat row until then (B70)."""
        ready = audio.peaks_ready(path, PEAKS_PER_SECOND)
        if ready is not None:
            return ready
        length = audio.probe(path)
        if length is None or length <= SYNC_PEAKS_SECONDS:
            return audio.peaks(path, PEAKS_PER_SECOND)
        self._peaks_loader.request(path)
        return np.zeros(0, np.float32)

    def _fresh_scene(self, rect: QRectF) -> QGraphicsScene:
        """An empty scene of ``rect`` in place of the current one, the scroll position kept. A
        hidden timeline clears its scene instead: a scene set before the first layout would leave
        its scroll bars stale for the fit that waits for the real width."""
        old = self.scene()
        if not self.isVisible():
            old.clear()
            old.setSceneRect(rect)
            return old
        scene = QGraphicsScene(self)
        scene.setSceneRect(rect)  # before it is shown: the scroll bars keep their place
        self.setScene(scene)
        old.deleteLater()
        return scene

    def _add_prop_row(self, layer: Layer, prop: str, top: float, fps: int) -> None:
        """A property row's keys (its band is drawn behind the items: ``drawBackground``)."""
        picks = self.picked_keys
        for key in layer.tracks.get(prop, []):
            frame = round(key.t * fps)
            selected = (layer.id, frame, None) in picks or (layer.id, frame, prop) in picks
            center = QPointF(self.scale.x(key.t), top + SUB_ROW_HEIGHT / 2)
            self.scene().addItem(PropKeyItem(layer.id, key.t, prop, center, selected))

    def key_items(self) -> list[KeyItem]:
        return [item for item in self.scene().items() if isinstance(item, KeyItem)]

    def cue_items(self) -> list[CueItem]:
        return [item for item in self.scene().items() if isinstance(item, CueItem)]

    def audio_items(self) -> list[AudioItem]:
        return [item for item in self.scene().items() if isinstance(item, AudioItem)]

    def clip_items(self) -> list[ClipItem]:
        return [item for item in self.scene().items() if isinstance(item, ClipItem)]

    def clip_item(self, layer_id: str, clip_id: str) -> ClipItem:
        for item in self.clip_items():
            if (item.layer_id, item.clip_id) == (layer_id, clip_id):
                return item
        raise KeyError((layer_id, clip_id))

    # -- painting ----------------------------------------------------------------

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        """Scrolling copies the viewport's pixels, the ruler and the playhead with them; they stay
        put, so the viewport is drawn again (the ruler was repeated down the rows)."""
        super().scrollContentsBy(dx, dy)
        self.viewport().update()

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        """The property rows' bands, only those in view: as scene items, a thousand full-width
        rectangles made every rebuild's ``QGraphicsScene.clear`` superlinear (B68)."""
        super().drawBackground(painter, rect)
        if not self.expanded or self.project is None:
            return
        layout, rows = self.layout(), self.rows()
        first = max(0, bisect_right(layout.tops, rect.top()) - 1)
        for row in range(first, len(rows)):
            top = layout.tops[row]
            if top > rect.bottom():
                break
            chosen_row = self.prop_layer == rows[row].id
            for i, prop in enumerate(layout.subs[row]):
                band = SUB_CHOSEN if chosen_row and prop in self.selected_props else SUB_BAND
                y = top + ROW_HEIGHT + i * SUB_ROW_HEIGHT
                painter.fillRect(QRectF(rect.left(), y, rect.width(), SUB_ROW_HEIGHT), band)

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:
        project = self.project
        painter.save()
        painter.resetTransform()  # viewport coordinates: ruler and playhead stay put
        width = self.viewport().width()
        painter.fillRect(0, 0, width, RULER_HEIGHT, RULER_BACKGROUND)
        if project is not None:
            end_x = self._viewport_x(project.canvas.duration)
            if end_x < width:  # past the scene's end: dimmed, with the end line to drag (P7.1)
                painter.fillRect(
                    QRectF(max(end_x, 0), RULER_HEIGHT, width - max(end_x, 0), self.viewport().height()),
                    SHADE_COLOR,
                )
            self._draw_ticks(painter, width, max(project.canvas.duration, self.reach()))
            if 0 <= end_x <= width:
                painter.setPen(QPen(END_COLOR, 2))
                painter.drawLine(QPointF(end_x, 0), QPointF(end_x, self.viewport().height()))
            self._draw_markers(painter, width, project)
            if self.guide is not None:
                gx = self._viewport_x(self.guide)
                painter.setPen(QPen(GUIDE_COLOR, 1, Qt.PenStyle.DashLine))
                painter.drawLine(QPointF(gx, 0), QPointF(gx, self.viewport().height()))
            x = self._viewport_x(self.playhead)
            painter.setPen(QPen(PLAYHEAD_COLOR, 2))
            painter.drawLine(QPointF(x, 0), QPointF(x, self.viewport().height()))
            if self.rubber is not None:  # the rubber band being drawn (U4b)
                painter.setPen(QPen(SELECTED_EDGE, 1, Qt.PenStyle.DashLine))
                painter.setBrush(RUBBER_FILL)
                painter.drawRect(self.mapFromScene(self.rubber).boundingRect())
                painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.restore()

    def _draw_ticks(self, painter: QPainter, width: int, duration: float) -> None:
        step = _tick_step(self.scale.px_per_second)
        painter.setPen(TEXT_COLOR)
        painter.setFont(QFont(painter.font().family(), 8))
        first = max(0, int(self.scale.t(self.mapToScene(0, 0).x()) / step))
        t = first * step
        while t <= duration + 1e-9:
            x = self._viewport_x(t)
            if x > width:
                break
            painter.drawLine(QPointF(x, RULER_HEIGHT - 6), QPointF(x, RULER_HEIGHT))
            painter.drawText(QPointF(x + 3, RULER_HEIGHT - 9), _tick_label(t, step))
            t += step

    def _draw_markers(self, painter: QPainter, width: int, project: Project) -> None:
        """Flags on the ruler with their names, and a faint line through the rows (ADR 0037)."""
        font = QFont(painter.font().family(), 8)
        height = self.viewport().height()
        for marker in project.markers:
            x = self._viewport_x(marker.t)
            if x < -40 or x > width:
                continue
            colour = QColor(marker.colour)
            selected = marker.id == self.selected_marker
            line = QColor(colour)
            line.setAlpha(110)
            painter.setPen(QPen(line, 1))
            painter.drawLine(QPointF(x, RULER_HEIGHT), QPointF(x, height))
            painter.setPen(QPen(SELECTED_EDGE if selected else colour.darker(150), 1.5 if selected else 1))
            painter.setBrush(colour)
            painter.drawPolygon(QPolygonF([QPointF(x, 2), QPointF(x + 9, 6), QPointF(x, 10), QPointF(x, 2)]))
            painter.drawLine(QPointF(x, 2), QPointF(x, RULER_HEIGHT))
            if marker.name:
                font.setBold(selected)
                painter.setFont(font)
                text = painter.fontMetrics().boundingRect(marker.name)
                box = QRectF(x + 11, 1, text.width() + 6, 12)
                painter.fillRect(box, RULER_BACKGROUND)
                painter.setPen(colour.lighter(130) if not selected else SELECTED_EDGE)
                painter.drawText(box.adjusted(3, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter, marker.name)
        painter.setBrush(Qt.BrushStyle.NoBrush)

    def _viewport_x(self, t: float) -> float:
        return self.mapFromScene(QPointF(self.scale.x(t), 0)).x()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.header.setGeometry(0, 0, self.header_width, self.height())
        if getattr(self, "_fit_pending", False):
            self.fit_to_width()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if getattr(self, "_fit_pending", False):
            self.fit_to_width()

    # -- zoom --------------------------------------------------------------------

    def zoom(self, factor: float, viewport_x: float) -> None:
        """Zoom about a viewport x, keeping the time under it in place."""
        t = self.scale.t(self.mapToScene(int(viewport_x), 0).x())
        self.scale = TimeScale(self.scale.zoomed(factor, 0).px_per_second)
        self.sync()
        self.horizontalScrollBar().setValue(round(self.scale.x(t) - viewport_x))
        self.viewport().update()

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.zoom(1.2 if event.angleDelta().y() > 0 else 1 / 1.2, event.position().x())
            event.accept()
            return
        super().wheelEvent(event)

    # -- mouse -------------------------------------------------------------------

    def _hit(self, pos: QPointF, kind: type = ClipItem) -> tuple[ClipItem | AudioItem | None, Edge | None]:
        item = next((i for i in self.items(pos.toPoint()) if isinstance(i, kind)), None)
        if item is None:
            return None, None
        left = self.mapFromScene(item.rect().topLeft()).x()
        right = self.mapFromScene(item.rect().topRight()).x()
        if pos.x() - left <= EDGE_PX:
            return item, "start"
        if right - pos.x() <= EDGE_PX:
            return item, "end"
        return item, None

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self.project is None:
            super().mousePressEvent(event)
            return
        pos = event.position()
        if pos.y() < RULER_HEIGHT:
            marker = self.marker_at(pos.x())
            if marker is not None:  # pick and drag a marker (ADR 0037)
                self.selected = self.selected_key = self.selected_audio = self.selected_cue = None
                self.selected_marker = marker.id
                self.markerSelected.emit(marker.id)
                x = self.mapToScene(pos.toPoint()).x()
                self._marker_drag = _MarkerDrag(marker.id, x, self.project, marker, marker.t)
                self.document.begin_preview()
                self.sync()
                return
            if self._near_end(pos):  # drag the scene's end (P7.1)
                self._end_drag = self.project
                self.document.begin_preview()
                return
            self._scrubbing = True
            self._scrub(pos.x())
            return
        extend = bool(
            event.modifiers() & (Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.ControlModifier)
        )
        many = self.picked_count() > 1
        key = self._key_hit(pos)
        if key is not None and extend:  # add it to the picks, or take it out (U4b)
            self.toggle_key_pick(self._key_pick(key))
            return
        if key is not None and many:
            layer_id, frame, prop = self._key_pick(key)
            picked = {(layer_id, frame, None), (layer_id, frame, prop)} & self.picked_keys
            if picked:  # drag every pick by this key
                self._make_primary(key=(layer_id, frame, prop))
                self._begin_group_drag(pos, [key.t])
                return
        if key is not None:
            self.selected, self.selected_key = None, (key.layer_id, key.t)
            self.selected_key_prop = key.prop
            self.keySelected.emit(key.layer_id, key.t)
            self._last_key_t = key.t
            x = self.mapToScene(pos.toPoint()).x()
            self._key_drag = _KeyDrag(key.layer_id, key.t, x, self.project, key.prop)
            self.document.begin_preview()
            self.sync()
            return
        bar, edge = self._hit(pos, CueItem)
        if bar is not None:  # a subtitle (ADR 0035)
            self.selected = self.selected_key = self.selected_audio = None
            self.selected_cue = bar.cue_id
            self.subtitleSelected.emit(bar.cue_id)
            base = self.project
            cue = next(c for c in base.subtitles if c.id == bar.cue_id)
            self._cue_drag = _CueDrag(bar.cue_id, edge, self.mapToScene(pos.toPoint()).x(), base, cue)
            self.document.begin_preview()
            self.sync()
            return
        sound, edge = self._hit(pos, AudioItem)
        if sound is not None:  # a sound (ADR 0034)
            self.selected, self.selected_key, self.selected_audio = None, None, sound.audio_id
            self.selected_cue = None
            self.audioSelected.emit(sound.audio_id)
            base = self.project
            clip = next(c for c in base.audio if c.id == sound.audio_id)
            self._audio_drag = _AudioDrag(
                sound.audio_id, edge, self.mapToScene(pos.toPoint()).x(), base, clip
            )
            self.document.begin_preview()
            self.sync()
            return
        item, edge = self._hit(pos)
        if item is None:
            band = self._band_hit(pos)
            if band is not None:  # a selected row's band: move those layers whole (U4b)
                start, end = self.layer_index().lifetime(band.layer_id)
                end = min(end, self.project.canvas.duration)
                rows = tuple(i for i in self.picked_rows if i in self.rows_draggable())
                self._begin_group_drag(pos, [start, end], layers=rows, row=band.layer_id, extend=extend)
                return
            # empty space: a click picks the row on release (P7.1, P7.3), a drag a rubber band
            self._empty_press = _EmptyPress(
                pos,
                QPointF(self.mapToScene(pos.toPoint())),
                extend,
                set(self.picked_clips),
                set(self.picked_keys),
                (self.selected, self.selected_key, self.selected_key_prop),
            )
            return
        if extend:  # add the clip to the picks, or take it out (U4b)
            self.toggle_clip_pick(item.layer_id, item.clip_id)
            return
        if many and (item.layer_id, item.clip_id) in self.picked_clips:  # drag every pick by it
            self._make_primary(clip=(item.layer_id, item.clip_id))
            clip = next(c for c in self.project.layer(item.layer_id).clips if c.id == item.clip_id)
            self._begin_group_drag(pos, [clip.start, clip.end])
            return
        self.selected_key = None
        self.selected_audio = self.selected_cue = None
        self.selected = (item.layer_id, item.clip_id)
        self.clipSelected.emit(item.layer_id, item.clip_id)
        base = self.project
        clip = next(c for c in base.layer(item.layer_id).clips if c.id == item.clip_id)
        self._drag = _Drag(item.layer_id, item.clip_id, edge, self.mapToScene(pos.toPoint()).x(), base, clip)
        self.document.begin_preview()
        self.sync()

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        if self._scrubbing:
            self._scrub(pos.x())
            return
        if self._end_drag is not None:
            self._apply_end_drag(pos.x())
            return
        press = self._empty_press
        if press is not None:  # past a few pixels, a press on empty space draws a rubber band
            if not press.banding and (pos - press.pos).manhattanLength() > RUBBER_PX:
                press.banding = True
            if press.banding:
                self._update_rubber(pos)
            return
        if (
            self._drag is None
            and self._group_drag is None
            and self._key_drag is None
            and self._audio_drag is None
            and self._cue_drag is None
            and self._marker_drag is None
        ):
            self._update_cursor(pos)
            return
        snapping = not (event.modifiers() & Qt.KeyboardModifier.AltModifier)
        self._pending = (self.mapToScene(pos.toPoint()).x(), snapping)
        if not self._apply_scheduled:
            self._apply_scheduled = True
            QTimer.singleShot(0, self.apply_pending)

    def mouseReleaseEvent(self, event) -> None:
        if self._scrubbing:
            self._scrubbing = False
            return
        if self._end_drag is not None:
            self._end_drag = None
            self.document.commit_preview("Scene length")
            return
        press, self._empty_press = self._empty_press, None
        if press is not None:
            if press.banding:
                self._finish_rubber(press.layer)
            else:  # a click on empty space: pick that property row or row
                self._click_empty(press)
            return
        self._set_guide(None)
        if self._group_drag is not None:
            self._finish_group_drag()
            return
        if self._marker_drag is not None:
            self.apply_pending()
            self._marker_drag = None
            self.document.commit_preview("Move marker")
            return
        if self._key_drag is not None:
            self.apply_pending()
            drag, self._key_drag = self._key_drag, None
            moved = self.project is not drag.base
            self.document.commit_preview(f"Move {drag.prop} key" if drag.prop else "Move keys")
            if moved:  # keep the moved keys selected
                self.selected_key = (drag.layer_id, self._last_key_t)
                self.selected_key_prop = drag.prop
                self.sync()
                self.keySelected.emit(drag.layer_id, self._last_key_t)
            return
        if self._audio_drag is not None:
            self.apply_pending()
            verb = "Move" if self._audio_drag.mode is None else "Trim"
            self._audio_drag = None
            self.document.commit_preview(f"{verb} sound")
            return
        if self._cue_drag is not None:
            self.apply_pending()
            verb = "Move" if self._cue_drag.mode is None else "Trim"
            self._cue_drag = None
            self.document.commit_preview(f"{verb} subtitle")
            return
        if self._drag is None:
            super().mouseReleaseEvent(event)
            return
        self.apply_pending()
        verb = "Move" if self._drag.mode is None else "Trim"
        self._drag = None
        self.document.commit_preview(f"{verb} clip")

    def keyPressEvent(self, event) -> None:
        drags = (
            self._drag,
            self._key_drag,
            self._audio_drag,
            self._cue_drag,
            self._marker_drag,
            self._group_drag,
        )
        dragging = any(drag is not None for drag in drags)
        if event.key() == Qt.Key.Key_Escape and self._empty_press is not None:  # drop the band
            press, self._empty_press, self.rubber = self._empty_press, None, None
            self.picked_clips, self.picked_keys = press.clips, press.keys
            self.selected, self.selected_key, self.selected_key_prop = press.primary
            self.sync()
            return
        if event.key() == Qt.Key.Key_Escape and self._group_drag is not None:
            group, self._group_drag = self._group_drag, None
            self.picked_clips, self.picked_keys = set(group.clips), set(group.keys)
            if group.primary_key is not None:
                self.selected_key, self.selected_key_prop = group.primary_key[:2], group.primary_key[2]
        if event.key() == Qt.Key.Key_Escape and not dragging and self.picked_count() > 1:
            self.collapse_picks()
            return
        if event.matches(QKeySequence.StandardKey.SelectAll) and not dragging:
            self.select_all_items()
            return
        if event.key() == Qt.Key.Key_Escape and dragging:
            self._drag = None
            self._key_drag = None
            self._audio_drag = None
            self._cue_drag = None
            self._marker_drag = None
            self._pending = None
            self._set_guide(None)
            self.document.cancel_preview()
            return
        deleting = event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace)
        if deleting and not dragging:
            if self.picked_count() > 1:  # every pick, one undo step (U4b)
                self.delete_picks()
                return
            if self.selected_marker:
                self.delete_marker(self.selected_marker)
                return
            if self.selected_cue:
                self.delete_subtitle(self.selected_cue)
                return
            if self.selected_audio:
                self.delete_audio(self.selected_audio)
                return
            if self.selected_key:
                props = [self.selected_key_prop] if self.selected_key_prop else None
                self.delete_keys(*self.selected_key, props)
                return
            if self.selected:
                self.delete_clip(*self.selected)
                return
        super().keyPressEvent(event)

    # -- adding and deleting clips (S2.6) ------------------------------------------

    def contextMenuEvent(self, event) -> None:
        menu = self.context_menu(QPointF(event.pos()))
        if menu is not None and not menu.isEmpty():
            menu.exec(event.globalPos())

    def context_menu(self, pos: QPointF) -> QMenu | None:
        """The right-click menu for a viewport position (built separately so it can be tested)."""
        busy = (self._drag, self._key_drag, self._group_drag, self._empty_press)
        if self.project is None or any(state is not None for state in busy):
            return None
        menu = QMenu(self)
        if pos.y() < RULER_HEIGHT:  # the ruler: markers (ADR 0037)
            t = min(max(self.scale.t(self.mapToScene(pos.toPoint()).x()), 0.0), self.reach())
            marker = self.marker_at(pos.x())
            if marker is None:
                menu.addAction("Add marker here", lambda: self.add_marker_at(t))
                return menu
            marker_id, at = marker.id, marker.t
            menu.addAction("Rename marker...", lambda: self.rename_marker(marker_id))
            menu.addAction("Delete marker", lambda: self.delete_marker(marker_id))
            self._sound_menu(menu, "Add sound here", at)
            return menu
        if self.subtitle_row_at(pos.y()):  # the Subtitles row (ADR 0035)
            bar, _edge = self._hit(pos, CueItem)
            if bar is not None:
                cue_id = bar.cue_id
                menu.addAction("Delete subtitle", lambda: self.delete_subtitle(cue_id))
                return menu
            t = self.scale.t(self.mapToScene(pos.toPoint()).x())
            fps = self.project.canvas.fps
            place = subtitles.place_cue(self.project, max(0.0, round(t * fps) / fps))  # on a frame
            add = menu.addAction("Add subtitle here", lambda: self.add_subtitle(*place))
            add.setEnabled(place is not None)
            return menu
        sound = self.audio_at(pos.y())
        if sound is not None:  # a sound's row (ADR 0034)
            menu.addAction("Delete sound", lambda: self.delete_audio(sound.id))
            return menu
        key = self._key_hit(pos)
        if key is not None and key.prop is not None:
            self._prop_key_menu(menu, key.layer_id, key.prop, key.t)
            return menu
        if key is not None:
            layer_id, t = key.layer_id, key.t
            menu.addAction(f"Delete keys at {t:g} s", lambda: self.delete_keys(layer_id, t))
            return menu
        prop_row = self.prop_row_at(pos.y())
        if prop_row is not None:  # a property row: key that property at the playhead (P7.3)
            layer, prop = prop_row
            verb = "Delete" if self.keyed_at_playhead(layer, prop) else "Add"
            menu.addAction(f"{verb} {prop} key at playhead", lambda: self.toggle_key(layer.id, prop))
            return menu
        item, _edge = self._hit(pos)
        if item is not None:
            layer_id, clip_id = item.layer_id, item.clip_id
            menu.addAction(f"Delete {item.kind} clip", lambda: self.delete_clip(layer_id, clip_id))
            clip = next(c for c in self.project.layer(layer_id).clips if c.id == clip_id)
            self._sound_menu(menu, "Add sound at start", clip.start)  # ADR 0037
            self._sound_menu(menu, "Add sound at end", clip.end)
            return menu
        layer = self.layer_at(pos.y())
        if layer is None:
            return None
        t = self.scale.t(self.mapToScene(pos.toPoint()).x())
        self._add_key_menu(menu, layer)
        if self.preset_menu is not None:  # at the clicked time, like Add clip (ADR 0039)
            fps = self.project.canvas.fps
            at = max(0.0, round(t * fps) / fps)
            self.preset_menu(menu.addMenu("Apply preset"), layer.id, at)
            if self.browse_presets is not None:  # the presets browser, for this row and time (ADR 0044)
                menu.setToolTipsVisible(True)
                browse = menu.addAction("Browse presets...", lambda: self.browse_presets(layer.id, at))
                browse.setToolTip("Pick a preset by its moving preview and apply it to this row here")
        add = menu.addMenu("Add clip")
        placement = place_new_clip(
            layer,
            t,
            duration=self.reach(),
            fps=self.project.canvas.fps,
            obstacles=obstacles(self.project, layer.id),
        )
        if placement is None:
            add.setEnabled(False)
            add.setTitle("Add clip (no room here)")
            return menu
        start, length = placement
        type_name = (layer.spec or self.project.root_of(layer.id).spec).type
        kinds = adapter.allowed_clip_kinds(type_name)
        if (
            not kinds
        ):  # code layers animate in their code (ADR 0019); simulated layers have no clips (ADR 0033)
            add.setEnabled(False)
            add.setTitle(
                "Add clip (animate it in its code)"
                if type_name in CODE_TYPES
                else "Add clip (none: it is drawn between its layers)"
                if type_name in CONNECTOR_TYPES  # ADR 0036
                else "Add clip (none: it is simulated)"
            )
            return menu
        if layer.is_part:  # a part cannot morph; its object can (ADR 0020)
            kinds = [k for k in kinds if CLIP_KIND_INFO[k].category != "morph"]
        if layer.is_child:  # only whole objects travel along paths (ADR 0025)
            kinds = [k for k in kinds if CLIP_KIND_INFO[k].category != "motion"]
        for category, title in (
            ("content", "Appear / disappear"),
            ("emphasis", "Emphasis"),
            ("motion", "Move"),
            ("morph", "Turn into"),
        ):
            section = [k for k in kinds if CLIP_KIND_INFO[k].category == category]
            if not section:
                continue
            menu_for = add.addMenu(title)
            for kind in section:
                if category == "motion":  # along which layer (ADR 0025)
                    sub = menu_for.addMenu(kind)
                    paths = self.project.path_layers(layer.id)
                    sub.setEnabled(bool(paths))
                    for path in paths:
                        sub.addAction(
                            path.label,
                            lambda k=kind, p=path.id: self.add_clip(
                                layer.id, k, start, length, params={"path": p}
                            ),
                        )
                    continue
                if category != "morph":
                    menu_for.addAction(kind, lambda k=kind: self.add_clip(layer.id, k, start, length))
                    continue
                sub = menu_for.addMenu(kind)
                targets = self._morph_targets(layer, kind)
                sub.setEnabled(bool(targets))
                for target in targets:
                    sub.addAction(
                        target.label,
                        lambda k=kind, to=target.id: self.add_clip(layer.id, k, start, length, to_layer=to),
                    )
        return menu

    # -- keyframes (P2b) ---------------------------------------------------------

    def _key_hit(self, pos: QPointF) -> KeyItem | None:
        """The diamond nearest the cursor within KEY_GRAB_PX (they win over clip bars)."""
        scene = self.mapToScene(pos.toPoint())
        near = [
            (abs(item.pos().x() - scene.x()), item)
            for item in self.key_items()
            if abs(item.pos().x() - scene.x()) <= KEY_GRAB_PX
            and abs(item.pos().y() - scene.y()) <= KEY_GRAB_PX
        ]
        return min(near, key=lambda pair: pair[0])[1] if near else None

    def _add_key_menu(self, menu: QMenu, layer: Layer) -> None:
        keyable = keyable_props(layer)  # a graph keys its opacity only (ADR 0024)
        tracked = [prop for prop in keyable if layer.tracks.get(prop)]
        if tracked:
            menu.addAction("Add key at playhead", lambda: self.add_keys(layer.id, tracked))
            return
        sub = menu.addMenu("Add key at playhead")
        for prop in keyable:
            sub.addAction(prop.capitalize(), lambda p=prop: self.add_keys(layer.id, [p]))

    def _prop_key_menu(self, menu: QMenu, layer_id: str, prop: str, t: float) -> None:
        """A property's key: delete it, or pick the ease of the motion from it to its next key."""
        menu.addAction(f"Delete {prop} key at {t:g} s", lambda: self.delete_keys(layer_id, t, [prop]))
        layer, fps = self.project.layer(layer_id), self.project.canvas.fps
        track = layer.tracks.get(prop, [])
        index = next((i for i, k in enumerate(track) if abs(k.t - t) < 0.5 / fps), None)
        if index is None or index == len(track) - 1:
            menu.addAction("No easing: no motion follows the last key").setEnabled(False)
            return
        current = track[index].ease
        menu.addSection(f"{PROP_LABELS[prop]} from {t:g} s: {curve_editor.ease_label(current)}")
        for choice in graph_model.ease_choices():
            action = menu.addAction(curve_editor.ease_label(choice))
            action.setCheckable(True)
            action.setChecked(choice == current)
            action.triggered.connect(lambda _=False, e=choice: self.set_key_ease(layer_id, prop, t, e))
        menu.addSeparator()

        def edit() -> None:
            ease = self.edit_curve(self, current)
            if ease is not None:
                self.set_key_ease(layer_id, prop, t, ease)

        menu.addAction("Edit curve...", edit)

    def set_key_ease(self, layer_id: str, prop: str, t: float, ease: Easing) -> None:
        self._apply(lambda p: edits.set_key_ease(p, layer_id, t, ease, props=[prop]), "Set ease")

    def add_keys(self, layer_id: str, props: list[str]) -> None:
        """Key ``props`` at the playhead frame, holding their current values."""
        fps = self.project.canvas.fps
        t = round(self.playhead * fps) / fps
        before = self.project

        def op(project: Project) -> edits.Edit:
            values = layer_transform(project.layer(layer_id), t)
            for prop in props:
                project = edits.set_key(project, layer_id, prop, t, getattr(values, prop)).project
            return edits.Edit(project, *edits.classify(before, project))

        self._apply(op, "Add key")
        self.selected, self.selected_key, self.selected_key_prop = None, (layer_id, t), None
        self.sync()
        self.keySelected.emit(layer_id, t)

    def delete_keys(self, layer_id: str, t: float, props: list[str] | None = None) -> None:
        """Remove the keys at ``t``: of every property, or of ``props`` only (a property row)."""
        if self.selected_key is not None and self.selected_key[0] == layer_id:
            self.selected_key = self.selected_key_prop = None
        text = f"Delete {props[0]} key" if props and len(props) == 1 else "Delete keys"
        self._apply(lambda p: edits.remove_keys(p, layer_id, t, props=props), text)

    def _morph_targets(self, layer: Layer, kind: str) -> list[Layer]:
        """Objects a layer can turn into with ``kind``: not parts, code or already targeted."""
        taken = self.project.morph_sources()
        tex_only = kind == "TransformMatchingTex"  # ADR 0020
        return [
            other
            for other in self.rows()
            if other.id != layer.id
            and other.id not in taken
            and not other.is_part
            and other.spec.type not in CODE_TYPES | TRACE_TYPES | CONNECTOR_TYPES
            and (not tex_only or other.spec.type in PART_PARENT_TYPES)
        ]

    def add_clip(
        self,
        layer_id: str,
        kind: str,
        start: float,
        length: float,
        to_layer: str | None = None,
        params: dict | None = None,
    ) -> None:
        clip_id = edits.new_clip_id(self.project.layer(layer_id), kind)
        params = {**new_clip_params(kind), **(params or {})}  # new morphs match smartly (ADR 0056)
        self._apply(
            lambda p: edits.add_clip(
                p, layer_id, kind, start, length, to_layer=to_layer, clip_id=clip_id, params=params
            ),
            f"Add {kind} clip",
        )
        if any(c.id == clip_id for c in self.project.layer(layer_id).clips):
            self.selected = (layer_id, clip_id)
            self.sync()
            self.clipSelected.emit(layer_id, clip_id)

    def delete_clip(self, layer_id: str, clip_id: str) -> None:
        if self.selected == (layer_id, clip_id):
            self.selected = None
        self._apply(lambda p: edits.remove_clip(p, layer_id, clip_id), "Delete clip")

    def add_subtitle(self, start: float, end: float) -> None:
        self._apply(lambda p: edits.add_cue(p, start, end, "New subtitle"), "Add subtitle")
        cue = next((c for c in self.project.subtitles if c.start == start), None)
        if cue is not None:
            self.selected_cue = cue.id
            self.sync()
            self.subtitleSelected.emit(cue.id)

    def delete_subtitle(self, cue_id: str) -> None:
        if self.selected_cue == cue_id:
            self.selected_cue = None
        self._apply(lambda p: edits.remove_cue(p, cue_id), "Delete subtitle")

    def delete_audio(self, audio_id: str) -> None:
        if self.selected_audio == audio_id:
            self.selected_audio = None
        self._apply(lambda p: edits.remove_audio(p, audio_id), "Delete sound")

    # -- markers and sounds at a moment (P5c, ADR 0037) ------------------------------

    def add_marker_at(self, t: float) -> str | None:
        """Add a marker on the frame of ``t`` and select it; the marker already there is selected
        instead. Returns its id."""
        if self.project is None:
            return None
        marker = edits.marker_at(self.project, t)
        if marker is None:
            before = {m.id for m in self.project.markers}
            self._apply(lambda p: edits.add_marker(p, t), "Add marker")
            marker = next((m for m in self.project.markers if m.id not in before), None)
        if marker is not None:
            self.selected = self.selected_key = self.selected_audio = self.selected_cue = None
            self.selected_marker = marker.id
            self.sync()
            self.markerSelected.emit(marker.id)
        return marker.id if marker is not None else None

    def delete_marker(self, marker_id: str) -> None:
        if self.selected_marker == marker_id:
            self.selected_marker = None
        self._apply(lambda p: edits.remove_marker(p, marker_id), "Delete marker")

    def rename_marker(self, marker_id: str) -> None:
        marker = next((m for m in self.project.markers if m.id == marker_id), None)
        name = self.ask_marker_name(marker.name if marker is not None else "")
        if name is not None:
            self._apply(lambda p: edits.update_marker(p, marker_id, name=name.strip()), "Rename marker")

    def ask_marker_name(self, current: str) -> str | None:
        """The new name of a marker, or None (cancelled). Tests replace it."""
        text, ok = QInputDialog.getText(self, "Rename Marker", "Name:", text=current)
        return text if ok else None

    def ask_sound_path(self) -> str:
        """A sound file to add (blank: cancelled). Tests replace it."""
        name, _ = QFileDialog.getOpenFileName(
            self, "Add Sound", "", "Sounds (*.wav *.mp3 *.ogg *.flac *.m4a *.aac);;All files (*)"
        )
        return name

    def sound_files(self) -> list[str]:
        """The project's sound files, the last added first, without those that cannot be read."""
        paths = list(dict.fromkeys(clip.path for clip in reversed(self.project.audio)))
        return [path for path in paths if audio.probe(path)]

    def _sound_menu(self, menu: QMenu, title: str, t: float) -> None:
        sub = menu.addMenu(title)
        for path in self.sound_files():
            sub.addAction(Path(path).name, lambda p=path: self.add_sound(p, t))
        if sub.actions():
            sub.addSeparator()
        sub.addAction("Other file...", lambda: self.add_sound(self.ask_sound_path(), t))

    def add_sound(self, path: str, t: float) -> None:
        """Add the whole sound file ``path`` starting at ``t`` and select it (as File > Import Audio)."""
        if not path:
            return
        length = audio.probe(path)
        if length is None or length <= 0:
            self.message.emit(f"Cannot read {Path(path).name} as a sound")
            return
        before = {c.id for c in self.project.audio}
        self._apply(
            lambda p: edits.add_audio(p, path, start=t, duration=length, name=Path(path).stem), "Add sound"
        )
        added = next((c for c in self.project.audio if c.id not in before), None)
        if added is not None:
            self.selected = self.selected_key = self.selected_cue = self.selected_marker = None
            self.selected_audio = added.id
            self.sync()
            self.audioSelected.emit(added.id)

    def _set_guide(self, t: float | None) -> None:
        if t != self.guide:
            self.guide = t
            self.viewport().update()

    def _guide_for(self, candidates: list[float], snapping: bool, *times: float) -> None:
        """Show the guide where a dragged edge rests on a snap point (ADR 0037)."""
        hit = next((t for t in times if snapping and snapped(t, candidates)), None)
        self._set_guide(hit)

    def _apply(self, op, text: str) -> None:
        try:
            self.document.apply(op(self.project), text)
        except (edits.EditError, ValidationError) as exc:
            self.message.emit(f"{text}: {exc}")

    def _apply_end_drag(self, viewport_x: float) -> None:
        """Preview the scene's end at the pointer (on frames, at least one frame)."""
        base = self._end_drag
        fps = base.canvas.fps
        t = self.scale.t(self.mapToScene(int(viewport_x), 0).x())
        t = max(round(t * fps), 1) / fps
        self.document.preview(edits.Edit(scene_length.set_length(base, t), "timing", frozenset()))

    def _update_cursor(self, pos: QPointF) -> None:
        if self.project is not None and self._near_end(pos):
            self.viewport().setCursor(Qt.CursorShape.SizeHorCursor)
            return
        item, edge = self._hit(pos) if pos.y() >= RULER_HEIGHT else (None, None)
        if item is None and pos.y() >= RULER_HEIGHT:
            item, edge = self._hit(pos, AudioItem)
        if item is None and pos.y() >= RULER_HEIGHT:
            item, edge = self._hit(pos, CueItem)
        if item is None and pos.y() >= RULER_HEIGHT and self._band_hit(pos) is not None:
            self.viewport().setCursor(Qt.CursorShape.SizeAllCursor)  # moves the layers (U4b)
        elif item is None:
            self.viewport().unsetCursor()
        elif (
            isinstance(item, ClipItem)
            and self.picked_count() > 1
            and (item.layer_id, item.clip_id) in self.picked_clips
        ):
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)  # moves every pick, no trim
        elif edge is not None:
            self.viewport().setCursor(Qt.CursorShape.SizeHorCursor)
        else:
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)

    def _scrub(self, viewport_x: float) -> None:
        t = self.scale.t(self.mapToScene(int(viewport_x), 0).x())
        t = min(max(t, 0.0), self.project.canvas.duration)
        self.set_playhead(t)
        self.seekRequested.emit(t)

    # -- applying a drag -----------------------------------------------------------

    def apply_pending(self) -> None:
        """Preview the latest drag position (coalesced: earlier ones are dropped)."""
        self._apply_scheduled = False
        if self._group_drag is not None and self._pending is not None:
            self._apply_group_drag()
            return
        if self._marker_drag is not None and self._pending is not None:
            self._apply_marker_drag()
            return
        if self._key_drag is not None and self._pending is not None:
            self._apply_key_drag()
            return
        if self._audio_drag is not None and self._pending is not None:
            self._apply_audio_drag()
            return
        if self._cue_drag is not None and self._pending is not None:
            self._apply_cue_drag()
            return
        if self._drag is None or self._pending is None:
            return
        scene_x, snapping = self._pending
        self._pending = None
        drag, base = self._drag, self._drag.base
        canvas = base.canvas
        layer = base.layer(drag.layer_id)
        delta = self.scale.seconds(scene_x - drag.press_x)
        common = {
            "duration": self.reach(),
            "fps": canvas.fps,
            "scale": self.scale,
            "candidates": snap_candidates(
                base, self.playhead, exclude=[("clip", drag.layer_id, drag.clip_id)]
            ),
            "snapping": snapping,
            "obstacles": obstacles(base, drag.layer_id),
        }
        if drag.mode is None:
            start = drag_move(layer, drag.clip_id, drag.clip.start + delta, **common)
            edit = edits.move_clip(base, drag.layer_id, drag.clip_id, start)
            self._guide_for(common["candidates"], snapping, start, start + drag.clip.duration)
        else:
            edge_t = (drag.clip.start if drag.mode == "start" else drag.clip.end) + delta
            start, end = drag_trim(layer, drag.clip_id, drag.mode, edge_t, **common)
            edit = edits.trim_clip(base, drag.layer_id, drag.clip_id, start=start, end=end)
            self._guide_for(common["candidates"], snapping, start if drag.mode == "start" else end)
        self.document.preview(edit)

    def _apply_group_drag(self) -> None:
        """Move the picks (or whole layers) by the dragged item's snapped delta, in one
        ``shift_timing`` edit: never below 0 s for any of it, not past what the timeline reaches
        (the scene grows on the drop); an edit the schema refuses previews nothing, and says why."""
        scene_x, snapping = self._pending
        self._pending = None
        drag, base = self._group_drag, self._group_drag.base
        fps = base.canvas.fps
        selection = self.timing_selection(drag.clips, drag.keys, drag.layers)
        exclude = [("clip", layer_id, clip_id) for layer_id, clip_id in selection.clips]
        exclude += [("key", layer_id, t) for layer_id, t, _ in selection.keys]
        for layer_id in drag.layers:
            layer = base.layer(layer_id)
            exclude += [("clip", layer_id, c.id) for c in layer.clips]
            exclude += [("key", layer_id, t) for t, _ in key_times(layer, fps)]
        candidates = snap_candidates(base, self.playhead, exclude=exclude)
        raw = self.scale.seconds(scene_x - drag.press_x)
        delta = group_delta(
            drag.anchors, raw, fps=fps, scale=self.scale, candidates=candidates, snapping=snapping
        )
        delta = max(delta, -shift_timing.earliest(base, selection))
        room = self.reach() - shift_timing.latest(base, selection)
        if delta > room:
            delta = max(room, 0.0)
        try:
            edit = shift_timing.shift_timing(base, selection, delta)
        except edits.EditError as exc:
            delta, edit = 0.0, edits.Edit(base, "timing", frozenset())
            text = f"{'Move layers' if drag.layers else 'Move selection'}: {exc}"
            if text != drag.refused:
                drag.refused = text
                self.message.emit(text)
        else:
            drag.refused = None
        # the picked keys follow, on the frame grid (as shift_timing places them)
        self.picked_keys = {(lay, round((f / fps + delta) * fps), p) for lay, f, p in drag.keys}
        if drag.primary_key is not None:
            layer_id, t, prop = drag.primary_key
            self.selected_key, self.selected_key_prop = (layer_id, round((t + delta) * fps) / fps), prop
        self._guide_for(candidates, snapping, *(a + delta for a in drag.anchors))
        self.document.preview(edit)

    def _apply_marker_drag(self) -> None:
        """Move a marker: on frames, snapping (ADR 0037), never onto another marker."""
        scene_x, snapping = self._pending
        self._pending = None
        drag, base = self._marker_drag, self._marker_drag.base
        candidates = snap_candidates(base, self.playhead, exclude=[("marker", drag.marker_id)])
        proposed = drag.marker.t + self.scale.seconds(scene_x - drag.press_x)
        t = drag_marker(
            base,
            drag.marker_id,
            proposed,
            drag.last,
            scale=self.scale,
            candidates=candidates,
            snapping=snapping,
        )
        drag.last = t
        self._guide_for(candidates, snapping, t)
        self.document.preview(edits.update_marker(base, drag.marker_id, t=t))

    def _apply_cue_drag(self) -> None:
        """Move a subtitle, or trim one of its ends: on frames, snapping (ADR 0037), never into
        its neighbours (one lane, ADR 0035)."""
        scene_x, snapping = self._pending
        self._pending = None
        drag, base = self._cue_drag, self._cue_drag.base
        cue, fps = drag.cue, base.canvas.fps
        delta = self.scale.seconds(scene_x - drag.press_x)
        candidates = snap_candidates(base, self.playhead, exclude=[("cue", cue.id)])
        others = [c for c in base.subtitles if c.id != cue.id]
        low = max([c.end for c in others if c.end <= cue.start + 1e-9], default=0.0)
        high = min([c.start for c in others if c.start >= cue.end - 1e-9], default=self.reach())
        frame = 1 / fps
        if drag.mode is None:
            length = cue.end - cue.start
            start = min(
                max(snap(cue.start + delta, candidates, self.scale, fps, snapping), low), high - length
            )
            edit = edits.update_cue(base, cue.id, start=start, end=start + length)
            self._guide_for(candidates, snapping, start, start + length)
        elif drag.mode == "start":
            start = min(
                max(snap(cue.start + delta, candidates, self.scale, fps, snapping), low), cue.end - frame
            )
            edit = edits.update_cue(base, cue.id, start=start)
            self._guide_for(candidates, snapping, start)
        else:
            end = max(
                min(snap(cue.end + delta, candidates, self.scale, fps, snapping), high), cue.start + frame
            )
            edit = edits.update_cue(base, cue.id, end=end)
            self._guide_for(candidates, snapping, end)
        self.document.preview(edit)

    def _apply_audio_drag(self) -> None:
        """Move a sound, or trim one of its ends: on frames, snapping (ADR 0037);
        the left edge cannot go before the file's start nor the right edge past its end."""
        scene_x, snapping = self._pending
        self._pending = None
        drag, base = self._audio_drag, self._audio_drag.base
        clip, fps = drag.clip, base.canvas.fps
        delta = self.scale.seconds(scene_x - drag.press_x)
        candidates = snap_candidates(base, self.playhead, exclude=[("audio", drag.audio_id)])

        def placed(t: float) -> float:
            return snap(t, candidates, self.scale, fps, snapping)

        frame = 1 / fps
        if drag.mode is None:
            start = max(0.0, placed(clip.start + delta))
            edit = edits.update_audio(base, drag.audio_id, start=start)
            self._guide_for(candidates, snapping, start)
        elif drag.mode == "start":
            start = min(max(placed(clip.start + delta), clip.start - clip.offset, 0.0), clip.end - frame)
            edit = edits.trim_audio(base, drag.audio_id, start=start)
            self._guide_for(candidates, snapping, start)
        else:
            length = audio.probe(clip.path)
            longest = clip.start + (length - clip.offset) if length else float("inf")
            end = min(max(placed(clip.end + delta), clip.start + frame), longest)
            edit = edits.trim_audio(base, drag.audio_id, end=end)
            self._guide_for(candidates, snapping, end)
        self.document.preview(edit)

    def _apply_key_drag(self) -> None:
        scene_x, snapping = self._pending
        self._pending = None
        drag, base = self._key_drag, self._key_drag.base
        canvas = base.canvas
        layer = base.layer(drag.layer_id)
        if drag.prop is not None:  # one property's key: only its own neighbours bound it (P7.3)
            layer = layer.model_copy(update={"tracks": {drag.prop: layer.tracks[drag.prop]}})
        candidates = snap_candidates(base, self.playhead, exclude=[("key", drag.layer_id, drag.t)])
        proposed = drag.t + self.scale.seconds(scene_x - drag.press_x)
        t = drag_keys(
            layer,
            drag.t,
            proposed,
            duration=self.reach(),
            fps=canvas.fps,
            scale=self.scale,
            candidates=candidates,
            snapping=snapping,
        )
        self._guide_for(candidates, snapping, t)
        if abs(t - drag.t) < 0.5 / canvas.fps:
            self._last_key_t = drag.t
            self.document.preview(edits.Edit(base, "timing", frozenset()))
            return
        self._last_key_t = round(t * canvas.fps) / canvas.fps
        props = [drag.prop] if drag.prop is not None else None
        self.document.preview(edits.retime_keys(base, drag.layer_id, drag.t, t, props=props))


def _heard(peaks: np.ndarray, clip: AudioClip) -> np.ndarray:
    """A sound's waveform as it is heard: its gain and fades applied (clipped like the mix)."""
    t = (np.arange(len(peaks)) + 0.5) / PEAKS_PER_SECOND
    envelope = np.full(len(peaks), 10 ** (clip.gain / 20))
    if clip.fade_in > 0:
        envelope *= np.minimum(1.0, t / clip.fade_in)
    if clip.fade_out > 0:
        envelope *= np.minimum(1.0, (clip.duration - t) / clip.fade_out)
    return np.clip(peaks * np.maximum(envelope, 0.0), 0.0, 1.0)


def _tick_step(px_per_second: float) -> float:
    """A 'nice' ruler step leaving at least ~60 px between labels (minutes on a long scene)."""
    for step in (0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60, 120, 300):
        if step * px_per_second >= 60:
            return step
    return 600


def _tick_label(t: float, step: float) -> str:
    """Seconds on a short ruler, minutes:seconds once the steps are half a minute or more."""
    if step < 30:
        return f"{t:g}s"
    minutes, seconds = divmod(round(t), 60)
    return f"{minutes}:{seconds:02d}"
