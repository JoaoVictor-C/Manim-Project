"""The graph editor (P6b.2, decision session 35): the selected layer's keyed values over time.

A thin Qt layer over ``graph_model`` (curves, ranges, sampling, the drag rule) and the
``Document`` (snapshots and undo):

* one curve per value - x, y, scale, rotation, opacity - in its own colour, each normalised
  to the plot over its own range; the focused curve (the last one clicked) has a value
  axis on the left; an untracked value is a dashed line at its base value;
* a click on a key selects it (the shared selection's key time, so Properties shows it);
  dragging moves that curve's key in time (frame grid, the timeline's snap points; Alt:
  frames only) and in value (Shift: along one axis only); release records one undo step,
  Escape cancels; the ranges stay as they were while dragging;
* Delete removes the highlighted keys: the clicked curve's key, or after a click on the
  timeline every key at that time; double-click on a curve adds a key there;
* right-click a segment to pick its ease or open the curve editor;
* F frames the keys, the wheel zooms time about the cursor, Ctrl+wheel the values,
  dragging with the middle button pans; the strip at the top scrubs the playhead.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic import ValidationError
from PySide6.QtCore import QLineF, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QMenu, QWidget

from ..core import edits
from ..core.schema import Easing, Layer, Project
from . import curve_editor, graph_model, theme
from .document import Document
from .graph_model import BY_NAME, Curve, Point, ValueView
from .selection import Selection
from .timeline.model import TimeScale

RULER = 20.0  # px: the time strip at the top (click to scrub)
AXIS = 56.0  # px: the value labels on the left
MARGIN = 10.0  # px: right and bottom
KEY_PX = 4.5  # half the size of a key's diamond
KEY_GRAB_PX = 7.0
CURVE_GRAB_PX = 5.0
SAMPLE_PX = 2.0  # a curve sample every 2 pixels
WHEEL_ZOOM = 1.2


@dataclass
class _Drag:
    curve: Curve
    t: float  # the key's time at the press
    press: QPointF
    base: Project  # the snapshot the drag started from
    value: float  # the key's value at the press
    new_t: float = 0.0
    lock: str | None = None  # "time" or "value" while Shift is held


@dataclass
class _Pan:
    press: QPointF
    scale: TimeScale
    values: ValueView


@dataclass
class _Cache:
    key: tuple = ()
    lines: dict[str, list[QLineF]] = field(default_factory=dict)  # stroked one by one (B56)
    polylines: dict[str, list[tuple[float, float]]] = field(default_factory=dict)
    sources: dict[str, tuple] = field(default_factory=dict)  # (track, base) each curve was drawn from


class GraphEditor(QWidget):
    seekRequested = Signal(float)
    message = Signal(str)  # refused edits, for the status bar

    def __init__(
        self, document: Document, selection: Selection, playhead: Callable[[], float], parent=None
    ) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setMinimumHeight(160)
        self.document = document
        self.selection = selection
        self.playhead = playhead
        self.edit_curve = curve_editor.edit_curve  # replaced in tests
        self.visible: set[str] = {curve.name for curve in graph_model.CURVES}
        self.focus: str | None = None  # the curve with the value axis (the last one clicked)
        self.focus_prop: str | None = None  # the track of the key clicked here (None: the column)
        self._own_key: tuple[str, float] | None = None  # the key time this editor selected
        self.scale = TimeScale(px_per_second=100.0)
        self.values = ValueView()
        self.ranges: dict[str, tuple[float, float]] = {}
        self._drag: _Drag | None = None
        self._pan: _Pan | None = None
        self._scrubbing = False
        self._pending: tuple[QPointF, bool, bool] | None = None  # (pos, snapping, shift)
        self._apply_scheduled = False
        self._cache = _Cache()
        document.changed.connect(lambda *_: self._on_document())
        document.reset.connect(lambda *_: self._on_reset())
        selection.changed.connect(self._on_selection)
        self._sync_ranges()  # made after a layer may already be selected

    # -- state ---------------------------------------------------------------------------

    @property
    def layer(self) -> Layer | None:
        layer_id = self.selection.layer_id
        if layer_id is None:
            return None
        return next((layer for layer in self.document.project.layers if layer.id == layer_id), None)

    def curves(self) -> list[Curve]:
        """The curves shown: those the layer may key and the legend leaves on."""
        layer = self.layer
        if layer is None:
            return []
        return [curve for curve in graph_model.curves_for(layer) if curve.name in self.visible]

    def set_curve_visible(self, name: str, visible: bool) -> None:
        (self.visible.add if visible else self.visible.discard)(name)
        if not visible and self.focus == name:
            self.focus = None
        self.update()

    def focus_curve(self) -> Curve | None:
        """The curve the value axis belongs to: the last clicked, else the first keyed shown."""
        curves = self.curves()
        if self.focus is not None and any(c.name == self.focus for c in curves):
            return BY_NAME[self.focus]
        layer = self.layer
        keyed = [c for c in curves if layer is not None and layer.tracks.get(c.prop)]
        return (keyed or curves or [None])[0]

    def plot_rect(self) -> QRectF:
        return QRectF(
            AXIS, RULER, max(self.width() - AXIS - MARGIN, 10.0), max(self.height() - RULER - MARGIN, 10.0)
        )

    def _sync_ranges(self) -> None:
        layer = self.layer
        self.ranges = {c.name: graph_model.value_range(layer, c) for c in graph_model.CURVES} if layer else {}

    def _on_document(self) -> None:
        if self._drag is None:  # while dragging, the ranges stay put
            self._sync_ranges()
        self.update()

    def _on_reset(self) -> None:
        self._drag = self._pan = None
        self._pending = None
        self.focus = self.focus_prop = None
        self._own_key = None
        self._sync_ranges()
        self.frame_all()

    def _on_selection(self) -> None:
        if self._drag is not None:  # the drag's own key time moving: ranges and focus stay
            self.update()
            return
        current = (self.selection.layer_id, self.selection.key_time)
        if self._own_key is None or current != self._own_key:
            self.focus_prop = None  # chosen elsewhere: the whole column is highlighted
            self._own_key = None
        self._sync_ranges()
        self.update()

    # -- geometry ------------------------------------------------------------------------

    def x_of(self, t: float) -> float:
        return self.plot_rect().left() + self.scale.x(t)

    def t_of(self, x: float) -> float:
        return self.scale.t(x - self.plot_rect().left())

    def y_of(self, curve: Curve, value: float) -> float:
        return self.values.y(graph_model.normalise(value, self.ranges[curve.name]))

    def value_of(self, curve: Curve, y: float) -> float:
        return graph_model.denormalise(self.values.n(y), self.ranges[curve.name])

    def point_pos(self, name: str, t: float) -> QPointF:
        """Where a key of curve ``name`` at ``t`` is drawn."""
        curve, layer = BY_NAME[name], self.layer
        key = graph_model.key_at(layer, curve, t, self.document.project.canvas.fps)
        return QPointF(self.x_of(key.t), self.y_of(curve, graph_model.component(key.value, curve)))

    def curve_pos(self, name: str, t: float) -> QPointF:
        """Where curve ``name`` passes at ``t``."""
        curve = BY_NAME[name]
        value = graph_model.component(graph_model.value_at(self.layer, curve, t), curve)
        return QPointF(self.x_of(t), self.y_of(curve, value))

    def points(self) -> list[Point]:
        layer = self.layer
        if layer is None or not self.ranges:
            return []
        left, scale = self.plot_rect().left(), self.scale
        return [
            Point(curve.name, t, left + scale.x(t), self.y_of(curve, value))
            for curve in self.curves()
            for t, value in graph_model.keys(layer, curve)
        ]

    def highlighted(self) -> set[tuple[str, float]]:
        """The keys drawn selected: ``(curve name, time)``."""
        layer, t = self.layer, self.selection.key_time
        if layer is None or t is None:
            return set()
        fps = self.document.project.canvas.fps
        return {
            (curve.name, key.t)
            for curve in graph_model.curves_for(layer)
            if self.focus_prop in (None, curve.prop)
            for key in layer.tracks.get(curve.prop, [])
            if abs(key.t - t) < 0.5 / fps
        }

    def frame_all(self) -> None:
        """F: the keys of the curves shown (or the scene) across the width; values 0..1."""
        duration = self.document.project.canvas.duration
        t0, t1 = graph_model.frame_times(self.layer, self.curves(), duration)
        width = self.plot_rect().width()
        self.scale = TimeScale(px_per_second=max(width / max(t1 - t0, 1e-3), 1e-3), offset=t0)
        rect = self.plot_rect()
        self.values = ValueView(rect.top(), rect.height())
        self.update()

    def resizeEvent(self, event) -> None:
        old = event.oldSize()
        rect = self.plot_rect()
        if old.width() > 0 and old.width() - AXIS - MARGIN > 0:  # keep the time span in view
            span = (old.width() - AXIS - MARGIN) / self.scale.px_per_second
            self.scale = TimeScale(max(rect.width() / span, 1e-3), self.scale.offset)
        else:
            self.frame_all()
        self.values = self.values.resized(rect.top(), rect.height())
        super().resizeEvent(event)

    def sizeHint(self) -> QSize:
        return QSize(800, 260)

    # -- drawing -------------------------------------------------------------------------

    def _curve_cache(self) -> _Cache:
        layer = self.layer
        rect = self.plot_rect()
        names = tuple(c.name for c in self.curves())
        key = (
            layer.id,
            names,
            self.scale,
            self.values,
            (rect.left(), rect.width(), rect.height()),
            tuple(sorted(self.ranges.items())),
        )
        old = self._cache
        if key == old.key and old.sources == {
            c.name: (layer.tracks.get(c.prop), getattr(layer.base, c.prop)) for c in self.curves()
        }:
            return old
        cache = _Cache(key)
        t0, t1 = self.t_of(rect.left()), self.t_of(rect.right())
        step = self.scale.seconds(SAMPLE_PX)
        for curve in self.curves():
            source = (layer.tracks.get(curve.prop), getattr(layer.base, curve.prop))
            cache.sources[curve.name] = source
            if key == old.key and old.sources.get(curve.name) == source:  # e.g. the curves not dragged
                cache.lines[curve.name] = old.lines[curve.name]
                cache.polylines[curve.name] = old.polylines[curve.name]
                continue
            samples = graph_model.curve_points(layer, curve, t0, t1, step)
            line = [(rect.left() + self.scale.x(t), self.y_of(curve, v)) for t, v in samples]
            if not layer.tracks.get(curve.prop):  # a flat base line, drawn dashed in one stroke
                cache.lines[curve.name] = [QLineF(*line[0], *line[-1])]
            else:  # separate segments: Qt strokes a wide antialiased polyline 20x slower (B56)
                cache.lines[curve.name] = [QLineF(*a, *b) for a, b in itertools.pairwise(line)]
            cache.polylines[curve.name] = line
        self._cache = cache
        return cache

    def paintEvent(self, event) -> None:
        colours = theme.THEME
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), theme.qcolor(colours.track))
        rect = self.plot_rect()
        painter.fillRect(QRectF(0, 0, self.width(), RULER), theme.qcolor(colours.ruler))
        muted = theme.qcolor(colours.muted)
        layer = self.layer
        if layer is None:
            painter.setPen(muted)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "Select an object to see its keyframes")
            self._draw_playhead(painter, rect)
            painter.end()
            return
        self._draw_grid(painter, rect)
        painter.save()
        painter.setClipRect(rect)
        cache = self._curve_cache()
        focus = self.focus_curve()
        order = sorted(self.curves(), key=lambda c: focus is not None and c.name == focus.name)
        for curve in order:  # the focused curve on top
            pen = QPen(theme.qcolor(getattr(colours, curve.token)), 2.5 if curve is focus else 1.5)
            if not layer.tracks.get(curve.prop):
                pen.setStyle(Qt.PenStyle.DashLine)
                pen.setWidthF(1.0)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawLines(cache.lines[curve.name])
        selected = self.highlighted()
        painter.setPen(QPen(theme.qcolor(colours.key_edge), 1))
        for point in self.points():
            hot = (point.curve, point.t) in selected
            token = colours.key_selected if hot else getattr(colours, BY_NAME[point.curve].token)
            painter.setBrush(theme.qcolor(token))
            size = KEY_PX + (1.5 if hot else 0.0)
            painter.drawPolygon(
                QPolygonF(
                    [
                        QPointF(point.x, point.y - size),
                        QPointF(point.x + size, point.y),
                        QPointF(point.x, point.y + size),
                        QPointF(point.x - size, point.y),
                    ]
                )
            )
        painter.restore()
        if not any(layer.tracks.get(c.prop) for c in self.curves()):
            painter.setPen(muted)
            painter.drawText(
                rect.adjusted(0, 8, 0, 0),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                "Double-click a line to add a key",
            )
        self._draw_playhead(painter, rect)
        painter.end()

    def _draw_grid(self, painter: QPainter, rect: QRectF) -> None:
        colours = theme.THEME
        grid, muted = QPen(theme.qcolor(colours.grid), 1), theme.qcolor(colours.muted)
        t0, t1 = self.t_of(rect.left()), self.t_of(rect.right())
        step = graph_model.nice_step(1 / self.scale.px_per_second)
        for t in graph_model.ticks(t0, t1, step):
            x = self.x_of(t)
            painter.setPen(grid)
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            painter.setPen(muted)
            painter.drawText(QPointF(x + 3, RULER - 6), f"{t:g} s")
        curve = self.focus_curve()
        if curve is None or curve.name not in self.ranges:
            return
        lo, hi = self.value_of(curve, rect.bottom()), self.value_of(curve, rect.top())
        step = graph_model.nice_step((hi - lo) / rect.height(), 36.0)
        painter.setPen(theme.qcolor(getattr(colours, curve.token)))
        painter.drawText(QRectF(2, 2, AXIS + 80, RULER - 4), Qt.AlignmentFlag.AlignVCenter, curve.label)
        for value in graph_model.ticks(lo, hi, step):
            y = self.y_of(curve, value)
            painter.setPen(grid)
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            painter.setPen(muted)
            painter.drawText(
                QRectF(0, y - 8, AXIS - 6, 16),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                f"{round(value, 6):g}",
            )

    def _draw_playhead(self, painter: QPainter, rect: QRectF) -> None:
        x = self.x_of(self.playhead())
        if rect.left() <= x <= rect.right():
            painter.setPen(QPen(theme.qcolor(theme.THEME.playhead), 1.5))
            painter.drawLine(QPointF(x, 0), QPointF(x, rect.bottom()))

    # -- hits ----------------------------------------------------------------------------

    def point_at(self, pos: QPointF) -> Point | None:
        return graph_model.nearest_point(self.points(), pos.x(), pos.y(), KEY_GRAB_PX)

    def curve_at(self, pos: QPointF) -> Curve | None:
        """The shown curve within a few pixels of ``pos``: a keyed curve before a dashed base
        line, then the focused curve, then the nearest."""
        layer = self.layer
        if layer is None:
            return None
        cache = self._curve_cache()
        focus = self.focus_curve()
        near = [
            (not layer.tracks.get(c.prop), c is not focus, distance, c)
            for c in self.curves()
            if (distance := graph_model.distance_to_polyline(cache.polylines[c.name], pos.x(), pos.y()))
            <= CURVE_GRAB_PX
        ]
        return min(near, key=lambda item: item[:3])[3] if near else None

    # -- mouse ---------------------------------------------------------------------------

    def mousePressEvent(self, event) -> None:
        pos = event.position()
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan = _Pan(pos, self.scale, self.values)
            return
        if event.button() != Qt.MouseButton.LeftButton or self.layer is None:
            super().mousePressEvent(event)
            return
        if pos.y() < RULER:
            self._scrubbing = True
            self._scrub(pos.x())
            return
        point = self.point_at(pos)
        layer = self.layer
        if point is None:
            if self.selection.key_time is not None:
                self.selection.set(layer.id)
            return
        curve = BY_NAME[point.curve]
        self.focus, self.focus_prop = curve.name, curve.prop
        key = graph_model.key_at(layer, curve, point.t, self.document.project.canvas.fps)
        self._select_key(layer.id, key.t)
        self._drag = _Drag(
            curve, key.t, pos, self.document.project, graph_model.component(key.value, curve), key.t
        )
        self.document.begin_preview()
        self.update()

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        if self._pan is not None:
            delta = pos - self._pan.press
            pan = self._pan
            self.scale = TimeScale(pan.scale.px_per_second, pan.scale.offset - pan.scale.seconds(delta.x()))
            self.values = pan.values.panned(delta.y())
            self.update()
            return
        if self._scrubbing:
            self._scrub(pos.x())
            return
        if self._drag is None:
            self._update_cursor(pos)
            return
        modifiers = event.modifiers()
        snapping = not (modifiers & Qt.KeyboardModifier.AltModifier)
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        self._pending = (QPointF(pos), snapping, shift)
        if not self._apply_scheduled:
            self._apply_scheduled = True
            QTimer.singleShot(0, self.apply_pending)

    def mouseReleaseEvent(self, event) -> None:
        if self._pan is not None and event.button() == Qt.MouseButton.MiddleButton:
            self._pan = None
            return
        if self._scrubbing:
            self._scrubbing = False
            return
        if self._drag is None:
            super().mouseReleaseEvent(event)
            return
        self.apply_pending()
        drag, self._drag = self._drag, None
        moved = self.document.project is not drag.base
        self.document.commit_preview(f"Move {drag.curve.label.lower()} key")
        self._sync_ranges()
        if moved:
            self._select_key(self.selection.layer_id, drag.new_t)
        self.update()

    def mouseDoubleClickEvent(self, event) -> None:
        pos = event.position()
        if event.button() != Qt.MouseButton.LeftButton or self.layer is None or pos.y() < RULER:
            return
        curve = self.curve_at(pos)
        if curve is not None:
            self.add_key_at(curve.name, self.t_of(pos.x()))

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key == Qt.Key.Key_Escape and self._drag is not None:
            self._drag = None
            self._pending = None
            self.document.cancel_preview()
            self._sync_ranges()
            self.update()
            return
        deleting = key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self._drag is None
        if deleting and self.delete_selected():
            return
        if key == Qt.Key.Key_F and self._drag is None:
            self.frame_all()
            return
        super().keyPressEvent(event)

    def wheelEvent(self, event) -> None:
        factor = WHEEL_ZOOM if event.angleDelta().y() > 0 else 1 / WHEEL_ZOOM
        pos = event.position()
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.values = self.values.zoomed(factor, pos.y())
        else:
            self.scale = self.scale.zoomed(factor, pos.x() - self.plot_rect().left())
        event.accept()
        self.update()

    def contextMenuEvent(self, event) -> None:
        menu = self.context_menu(QPointF(event.pos()))
        if menu is not None and not menu.isEmpty():
            menu.exec(event.globalPos())

    def _update_cursor(self, pos: QPointF) -> None:
        if self.layer is not None and pos.y() >= RULER and self.point_at(pos) is not None:
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        else:
            self.unsetCursor()

    def _scrub(self, x: float) -> None:
        t = min(max(self.t_of(x), 0.0), self.document.project.canvas.duration)
        self.seekRequested.emit(t)

    def _select_key(self, layer_id: str, t: float) -> None:
        self._own_key = (layer_id, t)
        self.selection.set_key(layer_id, t)

    # -- applying a drag -----------------------------------------------------------------

    def apply_pending(self) -> None:
        """Preview the latest drag position (coalesced: earlier ones are dropped)."""
        self._apply_scheduled = False
        if self._drag is None or self._pending is None:
            return
        pos, snapping, shift = self._pending
        self._pending = None
        drag = self._drag
        delta = pos - drag.press
        if shift and drag.lock is None and max(abs(delta.x()), abs(delta.y())) > 2:
            drag.lock = "time" if abs(delta.x()) >= abs(delta.y()) else "value"
        if not shift:
            drag.lock = None
        proposed_t = drag.t if drag.lock == "value" else drag.t + self.scale.seconds(delta.x())
        if drag.lock == "time":
            proposed_value = drag.value
        else:
            press_n = graph_model.normalise(drag.value, self.ranges[drag.curve.name])
            n = press_n + (self.values.n(pos.y()) - self.values.n(drag.press.y()))
            proposed_value = graph_model.denormalise(n, self.ranges[drag.curve.name])
        try:
            edit, drag.new_t = graph_model.drag_key(
                drag.base,
                self.selection.layer_id,
                drag.curve,
                drag.t,
                proposed_t,
                proposed_value,
                scale=self.scale,
                playhead=self.playhead(),
                snapping=snapping,
            )
        except (edits.EditError, ValidationError) as exc:
            self.message.emit(f"Move key: {exc}")
            return
        self.document.preview(edit)

    # -- edits ---------------------------------------------------------------------------

    def _apply(self, op: Callable[[Project], edits.Edit], text: str) -> bool:
        try:
            self.document.apply(op(self.document.project), text)
        except (edits.EditError, ValidationError) as exc:
            self.message.emit(f"{text}: {exc}")
            return False
        return True

    def add_key_at(self, name: str, t: float) -> None:
        """A key on curve ``name`` at the frame of ``t``, holding the value played there."""
        layer, curve = self.layer, BY_NAME[name]
        fps = self.document.project.canvas.fps
        t = min(max(round(t * fps) / fps, 0.0), self.document.project.canvas.duration)
        if self._apply(lambda p: graph_model.add_key(p, layer.id, curve, t), "Add key"):
            self.focus, self.focus_prop = curve.name, curve.prop
            self._select_key(layer.id, t)

    def delete_selected(self) -> bool:
        """Delete the highlighted keys; False when none is."""
        layer, t = self.layer, self.selection.key_time
        if layer is None or t is None or not self.highlighted():
            return False
        props = [self.focus_prop] if self.focus_prop else None
        self._own_key = None
        return self._apply(lambda p: graph_model.delete_keys(p, layer.id, t, props), "Delete keys")

    def set_ease(self, name: str, t: float, ease: Easing) -> None:
        layer, curve = self.layer, BY_NAME[name]
        self._apply(lambda p: graph_model.set_segment_ease(p, layer.id, curve, t, ease), "Set ease")

    def context_menu(self, pos: QPointF) -> QMenu | None:
        """Right-click: delete a key; on a segment, its ease (or the curve editor)."""
        layer = self.layer
        if layer is None or self._drag is not None:
            return None
        menu = QMenu(self)
        point = self.point_at(pos)
        if point is not None:
            curve = BY_NAME[point.curve]
            menu.addAction(
                f"Delete {curve.label.lower()} key at {point.t:g} s",
                lambda: self._apply(
                    lambda p: graph_model.delete_keys(p, layer.id, point.t, [curve.prop]), "Delete keys"
                ),
            )
            return menu
        curve = self.curve_at(pos)
        start = graph_model.segment_start(layer, curve, self.t_of(pos.x())) if curve else None
        if curve is None or start is None:
            return menu
        key = graph_model.key_at(layer, curve, start, self.document.project.canvas.fps)
        menu.addSection(f"{curve.label} from {start:g} s: {curve_editor.ease_label(key.ease)}")
        for choice in graph_model.ease_choices():
            action = menu.addAction(curve_editor.ease_label(choice))
            action.setCheckable(True)
            action.setChecked(choice == key.ease)
            action.triggered.connect(lambda _=False, e=choice: self.set_ease(curve.name, start, e))
        menu.addSeparator()

        def edit() -> None:
            ease = self.edit_curve(self, key.ease)
            if ease is not None:
                self.set_ease(curve.name, start, ease)

        menu.addAction("Edit curve...", edit)
        return menu
