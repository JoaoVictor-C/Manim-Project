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
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from pydantic import ValidationError
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QGraphicsPolygonItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QMenu,
    QStyleOptionGraphicsItem,
    QWidget,
)

from ...core import adapter, audio, edits, subtitles
from ...core.evaluator import layer_transform
from ...core.schema import (
    CLIP_KIND_INFO,
    CODE_TYPES,
    CONNECTOR_TYPES,
    PART_PARENT_TYPES,
    TRACE_TYPES,
    AudioClip,
    Clip,
    Cue,
    Layer,
    Project,
    keyable_props,
)
from ...logging_config import get_logger
from ..document import Document
from .model import (
    Edge,
    TimeScale,
    depth,
    drag_keys,
    drag_move,
    drag_trim,
    key_times,
    obstacles,
    place_new_clip,
    snap,
    snap_candidates,
)
from .model import rows as row_layers

log = get_logger(__name__)

ROW_HEIGHT = 28
RULER_HEIGHT = 26
HEADER_WIDTH = 140
INDENT_PX = 14  # per level of part layers (ADR 0012)
EDGE_PX = 6
CLIP_MARGIN = 4
KEY_HALF = 4.5  # diamond half size, px
KEY_GRAB_PX = 5.0
KEY_OFFSET = ROW_HEIGHT - 6  # diamond centre below the row top
TRANSFORM_PROPS = ("position", "scale", "rotation", "opacity")

CATEGORY_COLORS = {"content": "#3b82f6", "emphasis": "#f59e0b", "motion": "#10b981", "morph": "#a855f7"}
AUDIO_COLOR = QColor("#0f766e")
CUE_COLOR = QColor("#854d0e")
WAVE_COLOR = QColor(204, 251, 241, 190)
PEAKS_PER_SECOND = 100
LIFETIME_COLOR = QColor(255, 255, 255, 28)
PLAYHEAD_COLOR = QColor("#ef4444")
BACKGROUND = QColor("#1f2329")
RULER_BACKGROUND = QColor("#2a2f36")
TEXT_COLOR = QColor("#d6dae0")


class ClipItem(QGraphicsRectItem):
    def __init__(self, layer_id: str, clip: Clip, rect: QRectF, selected: bool) -> None:
        super().__init__(rect)
        self.layer_id, self.clip_id, self.kind = layer_id, clip.id, clip.kind
        self.selected = selected
        self.setBrush(QBrush(QColor(CATEGORY_COLORS[clip.info.category])))
        self.setPen(QPen(QColor("#ffffff") if selected else QColor(0, 0, 0, 90), 2 if selected else 1))
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
            painter.setPen(QColor("#ffffff"))
            painter.drawText(rect.adjusted(6, 0, -4, 0), Qt.AlignmentFlag.AlignVCenter, self.kind)


class AudioItem(QGraphicsRectItem):
    """A sound's bar (ADR 0034): its waveform over the part of the file it plays."""

    def __init__(self, clip: AudioClip, rect: QRectF, peaks, selected: bool) -> None:
        super().__init__(rect)
        self.audio_id, self.name = clip.id, clip.name or clip.id
        self.peaks, self.selected = peaks, selected
        self.setPen(QPen(QColor("#ffffff") if selected else QColor(0, 0, 0, 90), 2 if selected else 1))
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
            painter.setPen(QColor("#ffffff"))
            painter.drawText(rect.adjusted(6, 0, -4, 0), Qt.AlignmentFlag.AlignVCenter, self.name)


class CueItem(QGraphicsRectItem):
    """A subtitle's bar (ADR 0035), showing its text."""

    def __init__(self, cue: Cue, rect: QRectF, selected: bool) -> None:
        super().__init__(rect)
        self.cue_id, self.text = cue.id, " ".join(cue.text.split())
        self.setPen(QPen(QColor("#ffffff") if selected else QColor(0, 0, 0, 90), 2 if selected else 1))
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
            painter.setPen(QColor("#ffffff"))
            label = painter.fontMetrics().elidedText(
                self.text, Qt.TextElideMode.ElideRight, int(rect.width() - 10)
            )
            painter.drawText(rect.adjusted(6, 0, -4, 0), Qt.AlignmentFlag.AlignVCenter, label)


class KeyItem(QGraphicsPolygonItem):
    """Every key of one layer at one time (P2b)."""

    def __init__(
        self, layer_id: str, t: float, props: tuple[str, ...], center: QPointF, selected: bool
    ) -> None:
        h = KEY_HALF
        diamond = QPolygonF([QPointF(0, -h), QPointF(h, 0), QPointF(0, h), QPointF(-h, 0)])
        super().__init__(diamond)
        self.setPos(center)
        self.layer_id, self.t, self.props, self.selected = layer_id, t, props, selected
        self.setBrush(QBrush(QColor("#fde047") if selected else QColor("#e5e7eb")))
        self.setPen(QPen(QColor("#ffffff") if selected else QColor(0, 0, 0, 160), 1.5 if selected else 1))
        self.setToolTip(f"{t:g} s: {', '.join(props)}")
        self.setZValue(3)


@dataclass
class _KeyDrag:
    layer_id: str
    t: float
    press_x: float
    base: Project


class LayerHeader(QWidget):
    """Layer names, drawn in the view's left margin and scrolled with the rows."""

    def __init__(self, view: TimelineView) -> None:
        super().__init__(view)
        self._view = view

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), RULER_BACKGROUND)
        project = self._view.project
        if project is None:
            return
        painter.setPen(TEXT_COLOR)
        scroll = self._view.verticalScrollBar().value()
        rows = self._view.rows()
        for row, layer in enumerate(rows):
            y = RULER_HEIGHT + row * ROW_HEIGHT - scroll
            if y + ROW_HEIGHT < RULER_HEIGHT:
                continue
            text = layer.name or layer.id
            indent = INDENT_PX * depth(project, layer)
            if indent:
                text = "\u21b3 " + text
            rect = QRectF(8 + indent, y, HEADER_WIDTH - 12 - indent, ROW_HEIGHT)
            painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter, text)
        y = RULER_HEIGHT + len(rows) * ROW_HEIGHT - scroll  # the subtitles (ADR 0035)
        if y + ROW_HEIGHT >= RULER_HEIGHT:
            painter.drawText(
                QRectF(8, y, HEADER_WIDTH - 12, ROW_HEIGHT), Qt.AlignmentFlag.AlignVCenter, "Subtitles"
            )
        for i, clip in enumerate(project.audio):  # sounds under the subtitles (ADR 0034)
            y = RULER_HEIGHT + (len(rows) + 1 + i) * ROW_HEIGHT - scroll
            if y + ROW_HEIGHT >= RULER_HEIGHT:
                rect = QRectF(8, y, HEADER_WIDTH - 12, ROW_HEIGHT)
                painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter, "\u266a " + (clip.name or clip.id))
        painter.fillRect(0, 0, HEADER_WIDTH, RULER_HEIGHT, RULER_BACKGROUND)


@dataclass
class _CueDrag:
    cue_id: str
    mode: Edge | None  # None = move
    press_x: float
    base: Project
    cue: Cue


@dataclass
class _AudioDrag:
    audio_id: str
    mode: Edge | None  # None = move
    press_x: float
    base: Project
    clip: AudioClip


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
    message = Signal(str)  # refused edits, for the status bar

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.setBackgroundBrush(BACKGROUND)
        self.setViewportMargins(HEADER_WIDTH, 0, 0, 0)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumHeight(RULER_HEIGHT + 2 * ROW_HEIGHT)
        self.header = LayerHeader(self)
        self.verticalScrollBar().valueChanged.connect(self.header.update)

        self.document: Document | None = None
        self.scale = TimeScale(px_per_second=120.0)
        self.playhead = 0.0
        self.selected: tuple[str, str] | None = None
        self.selected_key: tuple[str, float] | None = None
        self.selected_audio: str | None = None
        self.selected_cue: str | None = None
        self._drag: _Drag | None = None
        self._audio_drag: _AudioDrag | None = None
        self._cue_drag: _CueDrag | None = None
        self._key_drag: _KeyDrag | None = None
        self._last_key_t = 0.0
        self._scrubbing = False
        self._pending: tuple[float, bool] | None = None  # (scene x, snapping)
        self._apply_scheduled = False

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
        self._audio_drag = None
        self._cue_drag = None
        self._drag = None
        self._key_drag = None
        self.sync()

    def set_selected(self, layer_id: str | None, clip_id: str | None, key_time: float | None = None) -> None:
        """Highlight a clip or a key time chosen elsewhere (the shared selection), or none."""
        selected = (layer_id, clip_id) if layer_id and clip_id else None
        selected_key = (layer_id, key_time) if layer_id and key_time is not None else None
        if (selected, selected_key) != (self.selected, self.selected_key):
            self.selected, self.selected_key = selected, selected_key
            self.sync()

    def set_selected_subtitle(self, cue_id: str | None) -> None:
        if cue_id != self.selected_cue:
            self.selected_cue = cue_id
            self.sync()

    def subtitle_row_at(self, viewport_y: float) -> bool:
        """Whether this height is the Subtitles row."""
        if self.project is None or viewport_y < RULER_HEIGHT:
            return False
        return int((self.mapToScene(0, int(viewport_y)).y() - RULER_HEIGHT) // ROW_HEIGHT) == len(self.rows())

    def set_selected_audio(self, audio_id: str | None) -> None:
        if audio_id != self.selected_audio:
            self.selected_audio = audio_id
            self.sync()

    def audio_at(self, viewport_y: float) -> AudioClip | None:
        """The sound whose row is at this height (rows under the layers)."""
        if self.project is None or viewport_y < RULER_HEIGHT:
            return None
        row = (
            int((self.mapToScene(0, int(viewport_y)).y() - RULER_HEIGHT) // ROW_HEIGHT) - len(self.rows()) - 1
        )
        return self.project.audio[row] if 0 <= row < len(self.project.audio) else None

    def rows(self) -> list[Layer]:
        """Layers in row order: the front-most object first, each followed by its parts."""
        return row_layers(self.project) if self.project is not None else []

    def row_of(self, layer_id: str) -> int:
        return [layer.id for layer in self.rows()].index(layer_id)

    def layer_at(self, viewport_y: float) -> Layer | None:
        row = int((self.mapToScene(0, int(viewport_y)).y() - RULER_HEIGHT) // ROW_HEIGHT)
        rows = self.rows()
        return rows[row] if viewport_y >= RULER_HEIGHT and 0 <= row < len(rows) else None

    def sizeHint(self) -> QSize:
        return QSize(800, RULER_HEIGHT + 6 * ROW_HEIGHT + 2 * self.frameWidth() + 16)

    def set_playhead(self, t: float) -> None:
        self.playhead = t
        self.viewport().update()

    # -- scene -------------------------------------------------------------------

    def sync(self) -> None:
        """Rebuild the scene from the current snapshot (cheap: B11)."""
        scene = self.scene()
        scene.clear()
        project = self.project
        if project is None:
            return
        width = self.scale.x(project.canvas.duration)
        height = RULER_HEIGHT + (len(project.layers) + 1 + len(project.audio)) * ROW_HEIGHT
        scene.setSceneRect(0, 0, width + 40, height)
        subtitle_top = RULER_HEIGHT + len(self.rows()) * ROW_HEIGHT
        for cue in project.subtitles:  # the Subtitles row (ADR 0035)
            rect = QRectF(
                self.scale.x(cue.start),
                subtitle_top + CLIP_MARGIN,
                max(2.0, self.scale.x(cue.end) - self.scale.x(cue.start)),
                ROW_HEIGHT - 2 * CLIP_MARGIN,
            )
            scene.addItem(CueItem(cue, rect, cue.id == self.selected_cue))
        first_audio_row = len(self.rows()) + 1
        for row, layer in enumerate(self.rows()):
            top = RULER_HEIGHT + row * ROW_HEIGHT
            start, end = project.lifetime(layer.id)
            end = min(end, project.canvas.duration)
            if end > start:
                band = scene.addRect(
                    QRectF(
                        self.scale.x(start), top + 2, self.scale.x(end) - self.scale.x(start), ROW_HEIGHT - 4
                    ),
                    QPen(Qt.PenStyle.NoPen),
                    QBrush(LIFETIME_COLOR),
                )
                band.setZValue(1)
            for clip in layer.clips:
                rect = QRectF(
                    self.scale.x(clip.start),
                    top + CLIP_MARGIN,
                    max(2.0, self.scale.x(clip.end) - self.scale.x(clip.start)),
                    ROW_HEIGHT - 2 * CLIP_MARGIN,
                )
                scene.addItem(ClipItem(layer.id, clip, rect, self.selected == (layer.id, clip.id)))
            for t, props in key_times(layer, project.canvas.fps):
                selected = self.selected_key is not None and self.selected_key[0] == layer.id
                selected = selected and abs(self.selected_key[1] - t) < 0.5 / project.canvas.fps
                center = QPointF(self.scale.x(t), top + KEY_OFFSET)
                scene.addItem(KeyItem(layer.id, t, props, center, selected))
        for i, clip in enumerate(project.audio):
            top = RULER_HEIGHT + (first_audio_row + i) * ROW_HEIGHT
            rect = QRectF(
                self.scale.x(clip.start),
                top + CLIP_MARGIN,
                max(2.0, self.scale.x(clip.end) - self.scale.x(clip.start)),
                ROW_HEIGHT - 2 * CLIP_MARGIN,
            )
            peaks = audio.peaks(clip.path, PEAKS_PER_SECOND)
            first = round(clip.offset * PEAKS_PER_SECOND)
            shown = peaks[first : first + round(clip.duration * PEAKS_PER_SECOND)]
            scene.addItem(AudioItem(clip, rect, _heard(shown, clip), clip.id == self.selected_audio))
        self.header.update()
        self.viewport().update()

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

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:
        project = self.project
        painter.save()
        painter.resetTransform()  # viewport coordinates: ruler and playhead stay put
        width = self.viewport().width()
        painter.fillRect(0, 0, width, RULER_HEIGHT, RULER_BACKGROUND)
        if project is not None:
            self._draw_ticks(painter, width, project.canvas.duration)
            x = self._viewport_x(self.playhead)
            painter.setPen(QPen(PLAYHEAD_COLOR, 2))
            painter.drawLine(QPointF(x, 0), QPointF(x, self.viewport().height()))
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
            painter.drawText(QPointF(x + 3, RULER_HEIGHT - 9), f"{t:g}s")
            t += step

    def _viewport_x(self, t: float) -> float:
        return self.mapFromScene(QPointF(self.scale.x(t), 0)).x()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.header.setGeometry(0, 0, HEADER_WIDTH, self.height())

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
            self._scrubbing = True
            self._scrub(pos.x())
            return
        key = self._key_hit(pos)
        if key is not None:
            self.selected, self.selected_key = None, (key.layer_id, key.t)
            self.keySelected.emit(key.layer_id, key.t)
            self._last_key_t = key.t
            self._key_drag = _KeyDrag(key.layer_id, key.t, self.mapToScene(pos.toPoint()).x(), self.project)
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
        if (
            self._drag is None
            and self._key_drag is None
            and self._audio_drag is None
            and self._cue_drag is None
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
        if self._key_drag is not None:
            self.apply_pending()
            drag, self._key_drag = self._key_drag, None
            moved = self.project is not drag.base
            self.document.commit_preview("Move keys")
            if moved:  # keep the moved keys selected
                self.selected_key = (drag.layer_id, self._last_key_t)
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
        drags = (self._drag, self._key_drag, self._audio_drag, self._cue_drag)
        dragging = any(drag is not None for drag in drags)
        if event.key() == Qt.Key.Key_Escape and dragging:
            self._drag = None
            self._key_drag = None
            self._audio_drag = None
            self._cue_drag = None
            self._pending = None
            self.document.cancel_preview()
            return
        deleting = event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace)
        if deleting and not dragging:
            if self.selected_cue:
                self.delete_subtitle(self.selected_cue)
                return
            if self.selected_audio:
                self.delete_audio(self.selected_audio)
                return
            if self.selected_key:
                self.delete_keys(*self.selected_key)
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
        if self.project is None or self._drag is not None or self._key_drag is not None:
            return None
        menu = QMenu(self)
        if self.subtitle_row_at(pos.y()):  # the Subtitles row (ADR 0035)
            bar, _edge = self._hit(pos, CueItem)
            if bar is not None:
                cue_id = bar.cue_id
                menu.addAction("Delete subtitle", lambda: self.delete_subtitle(cue_id))
                return menu
            t = self.scale.t(self.mapToScene(pos.toPoint()).x())
            place = subtitles.place_cue(self.project, max(0.0, t))
            add = menu.addAction("Add subtitle here", lambda: self.add_subtitle(*place))
            add.setEnabled(place is not None)
            return menu
        sound = self.audio_at(pos.y())
        if sound is not None:  # a sound's row (ADR 0034)
            menu.addAction("Delete sound", lambda: self.delete_audio(sound.id))
            return menu
        key = self._key_hit(pos)
        if key is not None:
            layer_id, t = key.layer_id, key.t
            menu.addAction(f"Delete keys at {t:g} s", lambda: self.delete_keys(layer_id, t))
            return menu
        item, _edge = self._hit(pos)
        if item is not None:
            layer_id, clip_id = item.layer_id, item.clip_id
            menu.addAction(f"Delete {item.kind} clip", lambda: self.delete_clip(layer_id, clip_id))
            return menu
        layer = self.layer_at(pos.y())
        if layer is None:
            return None
        t = self.scale.t(self.mapToScene(pos.toPoint()).x())
        self._add_key_menu(menu, layer)
        add = menu.addMenu("Add clip")
        placement = place_new_clip(
            layer,
            t,
            duration=self.project.canvas.duration,
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
                            path.name or path.id,
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
                        target.name or target.id,
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
        self.selected, self.selected_key = None, (layer_id, t)
        self.sync()
        self.keySelected.emit(layer_id, t)

    def delete_keys(self, layer_id: str, t: float) -> None:
        if self.selected_key is not None and self.selected_key[0] == layer_id:
            self.selected_key = None
        self._apply(lambda p: edits.remove_keys(p, layer_id, t), "Delete keys")

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

    def _apply(self, op, text: str) -> None:
        try:
            self.document.apply(op(self.project), text)
        except (edits.EditError, ValidationError) as exc:
            self.message.emit(f"{text}: {exc}")

    def _update_cursor(self, pos: QPointF) -> None:
        item, edge = self._hit(pos) if pos.y() >= RULER_HEIGHT else (None, None)
        if item is None and pos.y() >= RULER_HEIGHT:
            item, edge = self._hit(pos, AudioItem)
        if item is None and pos.y() >= RULER_HEIGHT:
            item, edge = self._hit(pos, CueItem)
        if item is None:
            self.viewport().unsetCursor()
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
            "duration": canvas.duration,
            "fps": canvas.fps,
            "scale": self.scale,
            "candidates": snap_candidates(base, self.playhead, exclude=(drag.layer_id, drag.clip_id)),
            "snapping": snapping,
            "obstacles": obstacles(base, drag.layer_id),
        }
        if drag.mode is None:
            start = drag_move(layer, drag.clip_id, drag.clip.start + delta, **common)
            edit = edits.move_clip(base, drag.layer_id, drag.clip_id, start)
        else:
            edge_t = (drag.clip.start if drag.mode == "start" else drag.clip.end) + delta
            start, end = drag_trim(layer, drag.clip_id, drag.mode, edge_t, **common)
            edit = edits.trim_clip(base, drag.layer_id, drag.clip_id, start=start, end=end)
        self.document.preview(edit)

    def _apply_cue_drag(self) -> None:
        """Move a subtitle, or trim one of its ends: on frames, snapping to clip edges and the
        playhead, never into its neighbours (one lane, ADR 0035)."""
        scene_x, snapping = self._pending
        self._pending = None
        drag, base = self._cue_drag, self._cue_drag.base
        cue, fps = drag.cue, base.canvas.fps
        delta = self.scale.seconds(scene_x - drag.press_x)
        candidates = snap_candidates(base, self.playhead)
        others = [c for c in base.subtitles if c.id != cue.id]
        low = max([c.end for c in others if c.end <= cue.start + 1e-9], default=0.0)
        high = min([c.start for c in others if c.start >= cue.end - 1e-9], default=base.canvas.duration)
        frame = 1 / fps
        if drag.mode is None:
            length = cue.end - cue.start
            start = min(
                max(snap(cue.start + delta, candidates, self.scale, fps, snapping), low), high - length
            )
            edit = edits.update_cue(base, cue.id, start=start, end=start + length)
        elif drag.mode == "start":
            start = min(
                max(snap(cue.start + delta, candidates, self.scale, fps, snapping), low), cue.end - frame
            )
            edit = edits.update_cue(base, cue.id, start=start)
        else:
            end = max(
                min(snap(cue.end + delta, candidates, self.scale, fps, snapping), high), cue.start + frame
            )
            edit = edits.update_cue(base, cue.id, end=end)
        self.document.preview(edit)

    def _apply_audio_drag(self) -> None:
        """Move a sound, or trim one of its ends: on frames, snapping to clip edges and the playhead;
        the left edge cannot go before the file's start nor the right edge past its end."""
        scene_x, snapping = self._pending
        self._pending = None
        drag, base = self._audio_drag, self._audio_drag.base
        clip, fps = drag.clip, base.canvas.fps
        delta = self.scale.seconds(scene_x - drag.press_x)
        candidates = snap_candidates(base, self.playhead)

        def placed(t: float) -> float:
            return snap(t, candidates, self.scale, fps, snapping)

        frame = 1 / fps
        if drag.mode is None:
            start = max(0.0, placed(clip.start + delta))
            edit = edits.update_audio(base, drag.audio_id, start=start)
        elif drag.mode == "start":
            start = min(max(placed(clip.start + delta), clip.start - clip.offset, 0.0), clip.end - frame)
            edit = edits.trim_audio(base, drag.audio_id, start=start)
        else:
            length = audio.probe(clip.path)
            longest = clip.start + (length - clip.offset) if length else float("inf")
            end = min(max(placed(clip.end + delta), clip.start + frame), longest)
            edit = edits.trim_audio(base, drag.audio_id, end=end)
        self.document.preview(edit)

    def _apply_key_drag(self) -> None:
        scene_x, snapping = self._pending
        self._pending = None
        drag, base = self._key_drag, self._key_drag.base
        canvas = base.canvas
        layer = base.layer(drag.layer_id)
        others = [t for t, _ in key_times(layer, canvas.fps) if abs(t - drag.t) >= 0.5 / canvas.fps]
        candidates = [*snap_candidates(base, self.playhead), *others]
        proposed = drag.t + self.scale.seconds(scene_x - drag.press_x)
        t = drag_keys(
            layer,
            drag.t,
            proposed,
            duration=canvas.duration,
            fps=canvas.fps,
            scale=self.scale,
            candidates=candidates,
            snapping=snapping,
        )
        if abs(t - drag.t) < 0.5 / canvas.fps:
            self._last_key_t = drag.t
            self.document.preview(edits.Edit(base, "timing", frozenset()))
            return
        self._last_key_t = round(t * canvas.fps) / canvas.fps
        self.document.preview(edits.retime_keys(base, drag.layer_id, drag.t, t))


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
    """A 'nice' ruler step leaving at least ~60 px between labels."""
    for step in (0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60):
        if step * px_per_second >= 60:
            return step
    return 120
