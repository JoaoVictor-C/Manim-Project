"""Canvas widget: shows the exact Manim (Cairo) frame at the playhead.

Since S3 it also draws the selection outline over the frame and forwards mouse
and keyboard input to a tool (``canvas_tools.MoveTool``). Since P3a (ADR 0023)
it has a view (``viewport.View``): the frame letterboxed (Fit) or any scale and
centre; the camera is re-framed to cover the whole widget, so what lies outside
the video frame shows, dimmed. Widget pixels map to Manim units (y up) through
``px_per_unit``, ``to_units`` and ``units_transform`` only.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, replace

import manim as m
import numpy as np
from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPolygonF, QTransform
from PySide6.QtWidgets import QWidget

from ..core.code_frame import CodeFrame
from ..core.evaluator import Evaluator
from ..core.schema import Canvas
from ..render.cairo_export import render_frame
from ..render.preview import PreviewView, preview_camera
from ..render.qt_paths import vmobject_path
from . import motion_overlay, viewport
from .gizmo import HANDLE_PX, KNOB_OFFSET_PX, MIN_BOX_PX, Box, oriented_box

OUTLINE_COLOR = QColor("#38bdf8")
MOTION_COLOR = QColor("#f59e0b")  # the motion path (ADR 0026)
KEY_PX = 7.0  # a key's square on the motion path
PASTEBOARD_DIM = QColor(24, 24, 27, 170)  # over what lies outside the video frame
FRAME_BORDER = QColor("#52525b")
WHEEL_PAN_PX = 48.0  # one wheel notch


@dataclass
class Outline:
    """The selected layer as drawn at the current time, in Manim units."""

    path: QPainterPath
    bounds: QRectF
    anchor: tuple[float, float]
    box: Box  # oriented: the frame the handles live in (P2a)
    snaps: np.ndarray  # where the pivot cross snaps: the unpadded box's corners, edge midpoints, centre (P2f)


class CanvasWidget(QWidget):
    """Letterboxed view of the Manim frame at the current time."""

    resized = Signal()
    view_changed = Signal()  # zoom or pan: the window renders again and updates the readout

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(320, 180)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._canvas: Canvas | None = None
        self._evaluator: Evaluator | None = None
        self._camera: m.Camera | None = None
        self._camera_view: PreviewView | None = None
        self._image: QImage | None = None
        self.half_resolution = False
        self.last_render_ms = 0.0
        self.selected_layer: str | None = None  # whose outline to draw
        self.outline: Outline | None = None
        self.readout: tuple[QPointF, str] | None = None  # a value shown next to the cursor while dragging
        self.tool = None  # receives mouse/key input (canvas_tools.MoveTool)
        self.view = viewport.View()  # editor state, not saved (ADR 0023)
        self.motion: motion_overlay.MotionPath | None = None  # the selected layer's path (ADR 0026)
        self.playing = False  # the motion path hides while playing
        self.render_ahead = None  # frames rendered ahead (ui.render_ahead.RenderAhead, ADR 0028)
        self.from_cache = False  # the frame shown came from it
        self._pan_from: QPointF | None = None  # middle-drag in progress

    @property
    def evaluator(self) -> Evaluator | None:
        return self._evaluator

    def set_scene(self, canvas: Canvas, evaluator: Evaluator) -> None:
        self._canvas, self._evaluator = canvas, evaluator
        self._camera = None
        self.view = viewport.View()  # a project opens at Fit

    # -- geometry ----------------------------------------------------------------

    def geometry_now(self) -> viewport.ViewGeometry:
        assert self._canvas is not None
        return viewport.geometry(self.view, self._canvas, self.width(), self.height())

    def px_per_unit(self) -> float:
        return self.geometry_now().ppu

    def to_units(self, pos: QPointF) -> np.ndarray:
        """A widget position in Manim units."""
        return viewport.to_world(self.geometry_now(), self.width(), self.height(), pos.x(), pos.y())

    def units_transform(self) -> QTransform:
        """Manim units -> widget pixels."""
        geo = self.geometry_now()
        cx, cy = geo.centre
        return QTransform(
            geo.ppu, 0, 0, -geo.ppu, self.width() / 2 - geo.ppu * cx, self.height() / 2 + geo.ppu * cy
        )

    def frame_rect(self) -> QRectF:
        """Where the video frame lies, in widget pixels (it may extend past the widget)."""
        half_w, half_h = self._canvas.frame_width / 2, self._canvas.frame_height / 2
        return self.units_transform().mapRect(QRectF(-half_w, -half_h, 2 * half_w, 2 * half_h))

    def zoom_label(self) -> str:
        return viewport.label(self.view, self.geometry_now()) if self._canvas is not None else ""

    # -- view (ADR 0023) ---------------------------------------------------------

    def set_view(self, view: viewport.View) -> None:
        if view != self.view:
            self.view = view
            self.view_changed.emit()

    def zoom(self, factor: float, pos: QPointF | None = None) -> None:
        """Zoom about a widget position (default: the centre)."""
        if self._canvas is None or self._dragging():
            return
        pos = pos if pos is not None else QPointF(self.width() / 2, self.height() / 2)
        self.set_view(
            viewport.zoom_about(
                self.view, self._canvas, self.width(), self.height(), factor, pos.x(), pos.y()
            )
        )

    def pan(self, dx: float, dy: float) -> None:
        if self._canvas is None or self._dragging():
            return
        self.set_view(viewport.pan(self.view, self._canvas, self.width(), self.height(), dx, dy))

    def fit(self) -> None:
        self.set_view(viewport.View())

    def actual_size(self) -> None:
        if self._canvas is not None:
            self.set_view(viewport.at_scale(self.view, self._canvas, self.width(), self.height(), 1.0))

    def _dragging(self) -> bool:
        """A tool gesture is in progress: the view waits (the dragged object would jump)."""
        return self.tool is not None and getattr(self.tool, "_drag", None) is not None

    # -- rendering ---------------------------------------------------------------

    def render_at(self, t: float) -> None:
        if self._canvas is None or self._evaluator is None:
            return
        view = self.preview_view()
        if self._camera is None or replace(view, centre=(0, 0)) != replace(self._camera_view, centre=(0, 0)):
            self._camera = preview_camera(view)
        elif view.centre != self._camera_view.centre:  # a pan: same camera, moved
            self._camera.frame_center = np.array([view.centre[0], view.centre[1], 0.0])
        self._camera_view = view
        start = time.perf_counter()
        cached = None
        if self.render_ahead is not None:
            self.render_ahead.set_view(view)
            cached = self.render_ahead.image(t)
        self.from_cache = cached is not None
        if cached is not None:  # rendered ahead (ADR 0028): only the selected object is evaluated
            self._image = cached
            self.outline = self._outline(self._selected_object(t), t)
        else:
            layers = self._evaluator.frame_layers(t)
            pixels = render_frame(self._camera, [mob for _, mob in layers])
            self.outline = self._outline(layers, t)  # built now: the mobjects are shared buffers
            height, width = pixels.shape[:2]
            self._image = QImage(pixels.data, width, height, 4 * width, QImage.Format.Format_RGBA8888).copy()
        self.motion = self._motion(t)
        self.last_render_ms = (time.perf_counter() - start) * 1000
        self.update()

    def _selected_object(self, t: float) -> list[tuple[str, m.Mobject]]:
        project = self._evaluator.project
        if not self.selected_layer or not any(layer.id == self.selected_layer for layer in project.layers):
            return []
        return self._evaluator.object_frame(self.selected_layer, t)

    def preview_view(self) -> PreviewView:
        """How the frame is framed now (ADR 0028): the camera covers the whole widget."""
        geo = self.geometry_now()
        scale = self.devicePixelRatioF() * (0.5 if self.half_resolution else 1.0)
        return PreviewView(
            pixel_width=max(2, int(self.width() * scale)),
            pixel_height=max(2, int(self.height() * scale)),
            frame_width=self.width() / geo.ppu,
            frame_height=self.height() / geo.ppu,
            centre=(float(geo.centre[0]), float(geo.centre[1])),
            background=self._canvas.background,
        )

    def _motion(self, t: float) -> motion_overlay.MotionPath | None:
        if self.playing or not self.selected_layer or self._evaluator is None:
            return None
        project = self._evaluator.project
        if not any(layer.id == self.selected_layer for layer in project.layers):
            return None
        layer = project.layer(self.selected_layer)
        return motion_overlay.build(layer, *self._evaluator.position_frame(layer, t))

    def _outline(self, layers: list[tuple[str, m.Mobject]], t: float) -> Outline | None:
        if not self.selected_layer:
            return None
        project = self._evaluator.project
        if not any(layer.id == self.selected_layer for layer in project.layers):
            return None
        # An object with parts is drawn as several mobjects: outline all of them (ADR 0012).
        members = {self.selected_layer} | {d.id for d in project.descendants(self.selected_layer)}
        drawn = [mob for layer_id, mob in layers if layer_id in members]
        if not drawn:
            return None
        mob = drawn[0] if len(drawn) == 1 else m.Group(*drawn)
        path = QPainterPath()
        if isinstance(mob, (m.ImageMobject, CodeFrame)):  # a rectangle: UL, UR, DL, DR
            points = mob.points[:4, :2].copy()
            ul, ur, dl, dr = (QPointF(*points[i]) for i in range(4))
            path.moveTo(ul)
            for corner in (ur, dr, dl):
                path.lineTo(corner)
            path.closeSubpath()
        else:
            family = [sub for sub in mob.family_members_with_points() if isinstance(sub, m.VMobject)]
            for sub in family:
                path.addPath(vmobject_path(sub))
            points = np.concatenate([sub.points[:, :2] for sub in family]) if family else np.zeros((1, 2))
        layer = project.layer(self.selected_layer)
        pivot, rotation, _ = self._evaluator.layer_frame(layer, t)
        anchor = (float(pivot[0]), float(pivot[1]))
        box = oriented_box(points, anchor, rotation, MIN_BOX_PX / self.px_per_unit())
        snaps = oriented_box(
            points, anchor, rotation
        ).snap_points()  # a line snaps to its ends, not beside them
        return Outline(path, path.boundingRect(), anchor, box, snaps)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#1e1e1e"))
        if self._image is not None and self._canvas is not None:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawImage(QRectF(self.rect()), self._image)
            self._paint_pasteboard(painter)
            if self.motion is not None:
                self._paint_motion(painter)
            if self.outline is not None:
                self._paint_outline(painter)
        painter.end()

    def _paint_pasteboard(self, painter: QPainter) -> None:
        """Dim what lies outside the video frame (four bands) and draw the frame's border."""
        frame, widget = self.frame_rect(), QRectF(self.rect())
        top, bottom = max(frame.top(), widget.top()), min(frame.bottom(), widget.bottom())
        for band in (
            QRectF(widget.left(), widget.top(), widget.width(), top - widget.top()),
            QRectF(widget.left(), bottom, widget.width(), widget.bottom() - bottom),
            QRectF(widget.left(), top, frame.left() - widget.left(), bottom - top),
            QRectF(frame.right(), top, widget.right() - frame.right(), bottom - top),
        ):
            if band.width() > 0 and band.height() > 0:
                painter.fillRect(band, PASTEBOARD_DIM)
        pen = QPen(FRAME_BORDER, 1)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(frame)

    def _paint_motion(self, painter: QPainter) -> None:
        """The motion path: dashed through the keys, a square per key, its tangent handles."""
        to_px = self.units_transform()
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        dashed = QPen(MOTION_COLOR, 1, Qt.PenStyle.DashLine)
        dashed.setCosmetic(True)
        painter.setPen(dashed)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPolyline(QPolygonF([to_px.map(QPointF(*p)) for p in self.motion.polyline]))
        solid = QPen(MOTION_COLOR, 1)
        solid.setCosmetic(True)
        painter.setPen(solid)
        half = KEY_PX / 2
        for key in self.motion.keys:
            centre = to_px.map(QPointF(*key.point))
            for handle in (key.in_handle, key.out_handle):
                if handle is not None:
                    end = to_px.map(QPointF(*handle))
                    painter.drawLine(centre, end)
                    painter.setBrush(MOTION_COLOR)
                    painter.drawEllipse(end, 3.0, 3.0)
            painter.setBrush(QColor("#0f172a"))
            painter.drawRect(QRectF(centre.x() - half, centre.y() - half, KEY_PX, KEY_PX))
        painter.restore()

    def _paint_outline(self, painter: QPainter) -> None:
        to_px = self.units_transform()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setClipRect(QRectF(self.rect()))
        pen = QPen(OUTLINE_COLOR, 1.5)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(to_px.map(self.outline.path))
        dashed = QPen(OUTLINE_COLOR, 1, Qt.PenStyle.DashLine)
        dashed.setCosmetic(True)
        painter.setPen(dashed)
        box = self.outline.box
        corners = [to_px.map(QPointF(*c)) for c in box.corners]
        painter.drawPolygon(QPolygonF(corners))
        cx, cy = to_px.map(QPointF(*self.outline.anchor)).toTuple()
        painter.setPen(pen)
        painter.drawLine(QPointF(cx - 6, cy), QPointF(cx + 6, cy))
        painter.drawLine(QPointF(cx, cy - 6), QPointF(cx, cy + 6))
        painter.drawEllipse(QPointF(cx, cy), 3.0, 3.0)  # the pivot: drag it to move the anchor (P2f)
        # handles: corner squares scale, the knob rotates (P2a)
        painter.setBrush(QColor("#0f172a"))
        half = HANDLE_PX / 2
        for corner in corners:
            painter.drawRect(QRectF(corner.x() - half, corner.y() - half, HANDLE_PX, HANDLE_PX))
        knob = to_px.map(QPointF(*box.knob(KNOB_OFFSET_PX / self.px_per_unit())))
        top_middle = (corners[2] + corners[3]) / 2
        painter.drawLine(top_middle, knob)
        painter.drawEllipse(knob, half, half)
        if self.readout is not None:
            pos, text = self.readout
            painter.setPen(QColor("#e2e8f0"))
            painter.drawText(pos + QPointF(14, -10), text)

    # -- input: forwarded to the tool ---------------------------------------------

    def event(self, event) -> bool:
        override = event.type() == QEvent.Type.ShortcutOverride
        if override and self.tool is not None and self.tool.wants_key(event):
            event.accept()  # arrow keys nudge the selection instead of stepping frames
            return True
        return super().event(event)

    def wheelEvent(self, event) -> None:
        """Ctrl+wheel zooms about the cursor; wheel pans (Shift: sideways) - ADR 0023."""
        if self._canvas is None:
            super().wheelEvent(event)
            return
        delta = event.angleDelta()
        notches = (delta.y() or delta.x()) / 120
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.zoom(viewport.ZOOM_STEP**notches, event.position())
        elif event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.pan(notches * WHEEL_PAN_PX, 0.0)
        else:
            self.pan(delta.x() / 120 * WHEEL_PAN_PX, delta.y() / 120 * WHEEL_PAN_PX)
        event.accept()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.MiddleButton and self._canvas is not None:
            if not self._dragging():
                self._pan_from = QPointF(event.position())  # middle-drag pans
            return
        if self.tool is None or self._canvas is None or event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        self.setFocus()
        self.tool.press(event.position(), event.modifiers())

    def mouseDoubleClickEvent(self, event) -> None:
        if self.tool is None or self._canvas is None or event.button() != Qt.MouseButton.LeftButton:
            super().mouseDoubleClickEvent(event)
            return
        self.tool.double_click(event.position(), event.modifiers())

    def mouseMoveEvent(self, event) -> None:
        if self._pan_from is not None:
            delta = event.position() - self._pan_from
            self._pan_from = QPointF(event.position())
            self.pan(delta.x(), delta.y())
            return
        if self.tool is not None and self._canvas is not None:
            self.tool.move(event.position(), event.modifiers())

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_from = None
            return
        if self.tool is not None and self._canvas is not None:
            self.tool.release()

    def keyPressEvent(self, event) -> None:
        if self.tool is not None and self._canvas is not None and self.tool.key(event):
            return
        super().keyPressEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.resized.emit()
