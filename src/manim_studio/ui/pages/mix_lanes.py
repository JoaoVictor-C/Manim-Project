"""The mix as lanes (Lumen, ADR 0063): the Audio page's picture of what plays when.

Four lanes under a ruler - **Narration** (the sounds made for subtitles), **Music** (long sounds), **Effects**
(short ones) and **Subtitles** - each with a rounded header (an icon tile, the name, a count), the clips drawn
as rounded bars with their waveform in the lane's colour (an effect shows its name), the playhead with its
time, the markers on the ruler and a white ring on the selected clip. A narrated sound that is out of date
(its subtitle changed since) is outlined in the key colour and says *stale*.

A sound is *music* when it lasts at least ``MUSIC_SECONDS`` or half of the scene, an *effect* otherwise: the
project does not keep a kind for a sound, so the lane is only where the picture puts it.

The view only reads the document (through the two callables it is given) and paints; a click on a clip or on
the ruler is reported by a signal and the page does what the tables already do (select, seek). Waveforms come
from ``audio.peaks_ready``: a file that has not been scanned yet is drawn flat and the view looks again a few
times, so it never decodes on the interface thread. ``set_zoom`` shows a part of the scene (Ctrl+wheel zooms
at the pointer, the wheel pans a zoomed view); ``viewChanged`` tells the page's scroll bar.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QWheelEvent,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from ...core.model.schema import AudioClip, Cue, Project
from ...core.sound import audio
from ...core.voice import narration
from ..style import theme
from ..style.icon_tile import paint_tile

PEAKS_PER_SECOND = 100
RULER_HEIGHT = 24
LANE_GAP = 4
HEADER_WIDE, HEADER_NARROW = 156, 118
STEPS = (0.1, 0.25, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600)
POLL_MS = 450
POLL_TRIES = 24
MUSIC_SECONDS = 8.0  # a sound this long (or half of the scene) is music, a shorter one an effect
MAX_ZOOM = 16.0


@dataclass(frozen=True)
class Lane:
    key: str
    title: str
    icon: str
    token: str  # the theme colour of its clips
    gradient: tuple[str, str]
    weight: float  # its share of the height
    least: int  # px: the least height
    most: int  # px: the most height


LANES = (
    Lane("narration", "Narration", "narration", "sound", ("sound", "morph"), 1.9, 48, 84),
    Lane("music", "Music", "music", "motion", ("motion", "accent_2"), 1.4, 36, 60),
    Lane("effects", "Effects", "effects", "key", ("key", "warning"), 1.0, 30, 44),
    Lane("subtitles", "Subtitles", "subtitles", "cue", ("cue", "muted"), 1.0, 30, 44),
)
EMPTY_TEXT = {
    "narration": "No speech yet - Generate speech",
    "music": "No music - Add sound",
    "effects": "No effects - Add sound",
    "subtitles": "No subtitles - Add at playhead",
}
SOUND_LANES = ("music", "effects")


def tick_step(pixels_per_second: float, spacing: float = 64.0) -> float:
    """The smallest whole step of ``STEPS`` (seconds) whose ticks are at least ``spacing`` px apart."""
    return next((s for s in STEPS if s * pixels_per_second >= spacing), STEPS[-1])


def stamp(t: float) -> str:
    """0:03.10 - the playhead's time."""
    whole = max(0.0, t)
    return f"{int(whole // 60)}:{whole % 60:05.2f}"


def ruler_label(t: float, step: float) -> str:
    if t >= 60 or step >= 60:
        return f"{int(t // 60)}:{int(t % 60):02d}"
    return f"{t:g}s"


def is_music(clip: AudioClip, scene_seconds: float) -> bool:
    """Whether the Music lane holds ``clip`` (else Effects): long in itself or against the scene."""
    return clip.duration >= MUSIC_SECONDS or clip.duration >= 0.5 * scene_seconds


def alpha(token: str, amount: float) -> QColor:
    """The theme colour named ``token`` (read now) with this opacity."""
    colour = QColor(theme.qcolor(getattr(theme.THEME, token)))
    colour.setAlphaF(max(0.0, min(1.0, amount)))
    return colour


class MixLanes(QWidget):
    seekRequested = Signal(float)
    soundClicked = Signal(str)
    cueClicked = Signal(str)
    viewChanged = Signal()  # the zoom or the first second shown changed

    def __init__(
        self,
        project: Callable[[], Project | None],
        time: Callable[[], float],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._project, self._time = project, time
        self.audio_id: str | None = None
        self.subtitle_id: str | None = None
        self.zoom = 1.0  # 1: the whole scene; 4: a quarter of it
        self.scroll = 0.0  # the second at the left edge of the tracks
        self._hits: list[tuple[QRectF, str, str]] = []  # (rect, "sound" | "cue", id) of the last paint
        self._scrubbing = False
        self._poll = QTimer(self, singleShot=True, interval=POLL_MS)
        self._poll.timeout.connect(self._look_again)
        self._tries = 0
        self.setMinimumSize(280, RULER_HEIGHT + sum(lane.least for lane in LANES) + 3 * LANE_GAP)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(False)
        self.setAccessibleName("Mix")

    def sizeHint(self) -> QSize:
        return QSize(640, RULER_HEIGHT + sum(lane.most for lane in LANES) + 3 * LANE_GAP)

    # -- what is shown ----------------------------------------------------------------------------

    def set_selection(self, audio_id: str | None, subtitle_id: str | None) -> None:
        if (audio_id, subtitle_id) != (self.audio_id, self.subtitle_id):
            self.audio_id, self.subtitle_id = audio_id, subtitle_id
            self.update()

    def refresh(self) -> None:
        self._tries = 0
        self._clamp()
        self.update()

    def duration(self) -> float:
        project = self._project()
        if project is None:
            return 1.0
        ends = [c.end for c in project.audio] + [c.end for c in project.subtitles]
        return max(project.canvas.duration, *(ends or [0.0]), 0.5)

    def span(self) -> float:
        """Seconds across the tracks now."""
        return self.duration() / self.zoom

    def set_zoom(self, zoom: float, anchor: float | None = None) -> None:
        """Show ``1/zoom`` of the scene; the second ``anchor`` (default: the middle) keeps its place."""
        zoom = max(1.0, min(MAX_ZOOM, zoom))
        if abs(zoom - self.zoom) < 1e-9:
            return
        before = self.span()
        point = self.scroll + before / 2 if anchor is None else anchor
        fraction = (point - self.scroll) / before if before else 0.5
        self.zoom = zoom
        self.scroll = point - fraction * self.span()
        self._clamp()
        self.update()
        self.viewChanged.emit()

    def set_scroll(self, seconds: float) -> None:
        before = self.scroll
        self.scroll = seconds
        self._clamp()
        if abs(self.scroll - before) > 1e-9:
            self.update()
            self.viewChanged.emit()

    def _clamp(self) -> None:
        self.scroll = max(0.0, min(self.scroll, max(0.0, self.duration() - self.span())))

    def groups(self, project: Project) -> dict[str, list]:
        """What each lane holds: ``(clip, cue)`` pairs for narration, clips, and cues."""
        by_id = {c.id: c for c in project.audio}
        spoken = {cue.audio_id: cue for cue in project.subtitles if cue.audio_id in by_id}
        others = [c for c in project.audio if c.id not in spoken]
        scene = project.canvas.duration
        return {
            "narration": [(by_id[i], cue) for i, cue in spoken.items()],
            "music": [c for c in others if is_music(c, scene)],
            "effects": [c for c in others if not is_music(c, scene)],
            "subtitles": list(project.subtitles),
        }

    def lane_rects(self) -> list[QRectF]:
        """The lane bands (header and track), top to bottom, for the current height."""
        room = self.height() - RULER_HEIGHT - (len(LANES) - 1) * LANE_GAP
        total = sum(lane.weight for lane in LANES)
        rects, top = [], float(RULER_HEIGHT)
        for lane in LANES:
            height = max(lane.least, min(lane.most, room * lane.weight / total))
            rects.append(QRectF(0, top, self.width(), height))
            top += height + LANE_GAP
        return rects

    def _geometry(self) -> tuple[float, float, float]:
        """``(header, track_left, track_width)`` for the current width."""
        header = HEADER_WIDE if self.width() >= 460 else HEADER_NARROW
        return header, header + 8.0, max(40.0, self.width() - header - 8.0 - 6.0)

    # -- painting ---------------------------------------------------------------------------------

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        project = self._project()
        header, track_left, track_width = self._geometry()
        pps = track_width / self.span()
        self._hits = []
        self._paint_ruler(painter, track_left, track_width, pps, project)
        groups = self.groups(project) if project is not None else {lane.key: [] for lane in LANES}
        for lane, band in zip(LANES, self.lane_rects(), strict=True):
            self._paint_lane(
                painter, lane, band, header, track_left, track_width, pps, groups[lane.key], project
            )
        self._paint_playhead(painter, track_left, track_width, pps)
        painter.end()
        if project is not None and self._tries < POLL_TRIES and self._missing_peaks(project):
            self._poll.start()

    def _x(self, left: float, pps: float, t: float) -> float:
        return left + (t - self.scroll) * pps

    def _paint_ruler(
        self, painter: QPainter, left: float, width: float, pps: float, project: Project | None
    ) -> None:
        c = theme.THEME
        step = tick_step(pps)
        painter.save()
        painter.setClipRect(QRectF(left - 4, 0, width + 8, RULER_HEIGHT))
        painter.setFont(theme.mono_font(7))
        t = int(self.scroll / step) * step
        end = self.scroll + self.span() + step
        while t <= min(self.duration(), end) + 1e-9:
            x = self._x(left, pps, t)
            painter.setPen(QPen(theme.qcolor(c.line_strong), 1))
            painter.drawLine(QPointF(x, RULER_HEIGHT - 6), QPointF(x, RULER_HEIGHT - 1))
            painter.setPen(theme.qcolor(c.faint))
            painter.drawText(
                QRectF(x + 3, 1, 60, RULER_HEIGHT - 8), Qt.AlignmentFlag.AlignLeft, ruler_label(t, step)
            )
            t += step
        for marker in project.markers if project is not None else ():
            x = self._x(left, pps, marker.t)
            colour = QColor(marker.colour) if QColor.isValidColorName(marker.colour) else QColor(c.key)
            painter.setPen(QPen(colour, 1))
            painter.drawLine(QPointF(x, 12), QPointF(x, RULER_HEIGHT - 1))
            painter.setBrush(colour)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPolygon([QPointF(x, 3), QPointF(x + 7, 6.5), QPointF(x, 10)])
        painter.restore()

    def _paint_lane(
        self,
        painter: QPainter,
        lane: Lane,
        band: QRectF,
        header: float,
        left: float,
        width: float,
        pps: float,
        items: list,
        project: Project | None,
    ) -> None:
        c = theme.THEME
        head = QRectF(0, band.top(), header, band.height())
        painter.setPen(QPen(theme.qcolor(c.line), 1))
        painter.setBrush(theme.qcolor(c.raised))
        painter.drawRoundedRect(head.adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)
        compact = band.height() < 54  # a short lane: tile and name sit in the middle, no chips
        side = min(22.0, band.height() - 6)
        top = band.top() + ((band.height() - side) / 2 if compact else 9)
        paint_tile(painter, QRectF(10, top, side, side), lane.icon, gradient=lane.gradient, radius=7)
        painter.setFont(self._bold(theme.font("label")))
        painter.setPen(theme.qcolor(c.text))
        name = QRectF(side + 18, top - 2, header - side - 24, side + 4)
        painter.drawText(name, Qt.AlignmentFlag.AlignVCenter, lane.title)
        if not compact:
            self._paint_chips(painter, lane, band, header, items, project)
        track = QRectF(left, band.top(), width, band.height())
        painter.setPen(QPen(theme.qcolor(c.line), 1))
        painter.setBrush(theme.qcolor(c.track))
        painter.drawRoundedRect(track.adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)
        painter.save()
        clip = QPainterPath()
        clip.addRoundedRect(track, 10, 10)
        painter.setClipPath(clip)
        if not items:
            painter.setFont(theme.font("caption"))
            painter.setPen(theme.qcolor(c.faint))
            painter.drawText(track, Qt.AlignmentFlag.AlignCenter, EMPTY_TEXT[lane.key])
        for item in items:
            if lane.key == "narration":
                self._paint_sound(painter, lane, track, left, pps, item[0], item[1], project)
            elif lane.key in SOUND_LANES:
                self._paint_sound(painter, lane, track, left, pps, item, None, project)
            else:
                self._paint_cue(painter, lane, track, left, pps, item)
        painter.restore()

    @staticmethod
    def _bold(font: QFont) -> QFont:
        font.setWeight(QFont.Weight.DemiBold)
        return font

    def _paint_chips(
        self, painter: QPainter, lane: Lane, band: QRectF, header: float, items: list, project: Project | None
    ) -> None:
        c = theme.THEME
        count = len(items)
        texts = [f"{count} {'clip' if lane.key != 'subtitles' else 'cue'}{'s' if count != 1 else ''}"]
        if lane.key == "narration" and project is not None:
            stale = sum(1 for _clip, cue in items if narration.state(project, cue) == narration.STALE)
            if stale:
                texts.append(f"{stale} stale")
        x, y = 10.0, band.top() + 37
        painter.setFont(theme.font("caption"))
        for text in texts:
            width = painter.fontMetrics().horizontalAdvance(text) + 14
            if x + width > header - 6:
                break
            warn = text.endswith("stale")
            box = QRectF(x, y, width, 18)
            painter.setBrush(theme.qcolor(c.surface_3))
            painter.setPen(QPen(alpha("key", 0.6) if warn else theme.qcolor(c.line_strong), 1))
            painter.drawRoundedRect(box, 9, 9)
            painter.setPen(theme.qcolor(c.warning if warn else c.muted))
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)
            x += width + 4

    def _bar_rect(
        self, track: QRectF, left: float, pps: float, start: float, end: float, pad: float = 5.0
    ) -> QRectF:
        x0, x1 = self._x(left, pps, start), self._x(left, pps, end)
        return QRectF(x0, track.top() + pad, max(4.0, x1 - x0), track.height() - 2 * pad)

    def _paint_sound(
        self,
        painter: QPainter,
        lane: Lane,
        track: QRectF,
        left: float,
        pps: float,
        clip: AudioClip,
        cue: Cue | None,
        project: Project | None,
    ) -> None:
        c = theme.THEME
        stale = cue is not None and project is not None and narration.state(project, cue) == narration.STALE
        token = "key" if stale else lane.token
        rect = self._bar_rect(track, left, pps, clip.start, clip.end)
        selected = clip.id == self.audio_id
        painter.setBrush(alpha(token, 0.2 if lane.key == "effects" else 0.14))
        painter.setPen(QPen(alpha(token, 0.7 if stale else 0.55), 1))
        painter.drawRoundedRect(rect, 8, 8)
        if lane.key == "effects":  # short and small: the name, as the design shows it
            painter.setFont(self._bold(theme.font("caption")))
            painter.setPen(theme.qcolor(c.warning if token == "key" else getattr(c, token)))
            label = clip.name or clip.id
            text = painter.fontMetrics().elidedText(
                label, Qt.TextElideMode.ElideRight, int(rect.width() - 10)
            )
            painter.drawText(rect.adjusted(6, 0, -4, 0), Qt.AlignmentFlag.AlignVCenter, text)
        else:
            self._paint_wave(painter, rect.adjusted(6, 5, -6, -5), clip, token)
        if stale:
            self._paint_tag(painter, rect, "stale")
        if selected:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(theme.qcolor(c.bar_selected), 2))
            painter.drawRoundedRect(rect.adjusted(-1, -1, 1, 1), 9, 9)
        self._hits.append((rect, "sound", clip.id))

    def _paint_tag(self, painter: QPainter, rect: QRectF, text: str) -> None:
        c = theme.THEME
        painter.setFont(theme.font("caption"))
        width = painter.fontMetrics().horizontalAdvance(text) + 12
        if rect.width() < width + 12:
            return
        box = QRectF(rect.right() - width - 4, rect.top() + 4, width, 16)
        painter.setBrush(alpha("warning", 0.18))
        painter.setPen(QPen(alpha("warning", 0.5), 1))
        painter.drawRoundedRect(box, 8, 8)
        painter.setPen(theme.qcolor(c.warning))
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)

    def _peaks(self, clip: AudioClip) -> np.ndarray | None:
        found = audio.peaks_ready(clip.path, PEAKS_PER_SECOND)
        if found is None or not len(found):
            return None
        lo = int(clip.offset * PEAKS_PER_SECOND)
        hi = max(lo + 1, int((clip.offset + clip.duration) * PEAKS_PER_SECOND))
        return np.asarray(found[lo:hi], dtype=np.float32)

    def _paint_wave(self, painter: QPainter, area: QRectF, clip: AudioClip, token: str) -> None:
        if area.width() < 4 or area.height() < 4:
            return
        peaks = self._peaks(clip)
        mid = area.center().y()
        if peaks is None or not len(peaks):
            painter.setPen(QPen(alpha(token, 0.4), 1, Qt.PenStyle.DotLine))
            painter.drawLine(QPointF(area.left(), mid), QPointF(area.right(), mid))
            return
        # only the columns that are on screen (a zoomed view of a long sound stays cheap)
        first = max(0, int((self._visible_left() - area.left()) // 3))
        last = min(int(area.width() // 3), int((self._visible_right() - area.left()) // 3) + 1)
        columns = max(1, int(area.width() // 3))
        edges = np.linspace(0, len(peaks), columns + 1).astype(int)
        gain = 10 ** (clip.gain / 20)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(alpha(token, 0.85))
        for i in range(first, max(first, last)):
            a, b = edges[i], max(edges[i] + 1, edges[i + 1])
            level = min(1.0, float(peaks[a:b].max()) * gain) ** 0.75 if a < len(peaks) else 0.0
            half = max(1.0, level * area.height() / 2)
            painter.drawRoundedRect(QRectF(area.left() + i * 3, mid - half, 2, 2 * half), 1, 1)

    def _visible_left(self) -> float:
        return self._geometry()[1]

    def _visible_right(self) -> float:
        _header, left, width = self._geometry()
        return left + width

    def _paint_cue(
        self, painter: QPainter, lane: Lane, track: QRectF, left: float, pps: float, cue: Cue
    ) -> None:
        c = theme.THEME
        rect = self._bar_rect(track, left, pps, cue.start, cue.end, pad=6.0)
        fill = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        fill.setColorAt(0.0, theme.qcolor(theme.mix(c.cue, c.on_accent, 0.14)))
        fill.setColorAt(1.0, theme.qcolor(theme.mix(c.cue, c.badge, 0.25)))
        painter.setBrush(fill)
        painter.setPen(QPen(alpha("bar_text", 0.2), 1))
        painter.drawRoundedRect(rect, 8, 8)
        painter.setFont(self._bold(theme.font("caption")))
        painter.setPen(theme.qcolor(c.bar_text))
        text = painter.fontMetrics().elidedText(
            cue.text.replace("\n", " "), Qt.TextElideMode.ElideRight, int(rect.width() - 14)
        )
        painter.drawText(
            rect.adjusted(8, 0, -6, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text
        )
        if cue.id == self.subtitle_id:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(theme.qcolor(c.bar_selected), 2))
            painter.drawRoundedRect(rect.adjusted(-1, -1, 1, 1), 9, 9)
        self._hits.append((rect, "cue", cue.id))

    def _paint_playhead(self, painter: QPainter, left: float, width: float, pps: float) -> None:
        c = theme.THEME
        t = max(0.0, min(self.duration(), self._time()))
        x = self._x(left, pps, t)
        if x < left - 1 or x > left + width + 1:
            return  # scrolled out of view
        line = QLinearGradient(QPointF(x, 0), QPointF(x, self.height()))
        line.setColorAt(0.0, theme.qcolor(c.accent_2))
        line.setColorAt(1.0, theme.qcolor(c.accent))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(line)
        painter.drawRect(QRectF(x - 1, 0, 2, self.height()))
        painter.setFont(self._bold(theme.mono_font(7)))
        text = stamp(t)
        box_width = painter.fontMetrics().horizontalAdvance(text) + 12
        box = QRectF(min(max(0.0, x - box_width / 2), self.width() - box_width), 2, box_width, 17)
        painter.setBrush(theme.qcolor(c.accent))
        painter.drawRoundedRect(box, 7, 7)
        painter.setPen(theme.qcolor(c.on_accent))
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)

    # -- waveforms that arrive later ----------------------------------------------------------------

    def _missing_peaks(self, project: Project) -> bool:
        return any(audio.peaks_ready(c.path, PEAKS_PER_SECOND) is None for c in project.audio)

    def _look_again(self) -> None:
        self._tries += 1
        if self.isVisible():
            self.update()

    # -- mouse ------------------------------------------------------------------------------------------

    def _time_at(self, x: float) -> float:
        _header, left, width = self._geometry()
        return max(0.0, min(self.duration(), self.scroll + (x - left) / width * self.span()))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        point = event.position()
        for rect, kind, item_id in reversed(self._hits):
            if rect.contains(point):
                (self.soundClicked if kind == "sound" else self.cueClicked).emit(item_id)
                return
        if point.x() < self._geometry()[1] - 4:
            return  # on a lane's header: nothing to seek to
        self._scrubbing = True
        self.seekRequested.emit(self._time_at(point.x()))

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._scrubbing:
            self.seekRequested.emit(self._time_at(event.position().x()))

    def mouseReleaseEvent(self, _event: QMouseEvent) -> None:
        self._scrubbing = False

    def wheelEvent(self, event: QWheelEvent) -> None:
        delta = event.angleDelta()
        steps = (delta.y() or delta.x()) / 120
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.set_zoom(self.zoom * 1.25**steps, self._time_at(event.position().x()))
            event.accept()
        elif self.zoom > 1.0:
            self.set_scroll(self.scroll - steps * self.span() * 0.15)
            event.accept()
        else:
            event.ignore()
