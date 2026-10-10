"""Canvas widget: shows the exact Manim (Cairo) frame at the playhead, letterboxed.

Since S3 it also draws the selection outline over the frame and forwards mouse
and keyboard input to a tool (``canvas_tools.MoveTool``). Coordinates: widget
pixels map to Manim units through ``target_rect`` (the frame is centred on the
origin, y up).
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import manim as m
import numpy as np
from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPolygonF, QTransform
from PySide6.QtWidgets import QWidget

from ..core.code_frame import CodeFrame
from ..core.evaluator import Evaluator
from ..core.schema import Canvas
from ..render.cairo_export import render_frame
from ..render.qt_paths import vmobject_path
from .gizmo import HANDLE_PX, KNOB_OFFSET_PX, MIN_BOX_PX, Box, oriented_box

OUTLINE_COLOR = QColor("#38bdf8")


@dataclass
class Outline:
    """The selected layer as drawn at the current time, in Manim units."""

    path: QPainterPath
    bounds: QRectF
    anchor: tuple[float, float]
    box: Box  # oriented: the frame the handles live in (P2a)


class CanvasWidget(QWidget):
    """Letterboxed view of the Manim frame at the current time."""

    resized = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(320, 180)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._canvas: Canvas | None = None
        self._evaluator: Evaluator | None = None
        self._camera: m.Camera | None = None
        self._camera_size: tuple[int, int] = (0, 0)
        self._image: QImage | None = None
        self.half_resolution = False
        self.last_render_ms = 0.0
        self.selected_layer: str | None = None  # whose outline to draw
        self.outline: Outline | None = None
        self.readout: tuple[QPointF, str] | None = None  # a value shown next to the cursor while dragging
        self.tool = None  # receives mouse/key input (canvas_tools.MoveTool)

    @property
    def evaluator(self) -> Evaluator | None:
        return self._evaluator

    def set_scene(self, canvas: Canvas, evaluator: Evaluator) -> None:
        self._canvas, self._evaluator = canvas, evaluator
        self._camera = None

    # -- geometry ----------------------------------------------------------------

    def target_rect(self) -> QRectF:
        assert self._canvas is not None
        aspect = self._canvas.width_px / self._canvas.height_px
        w, h = self.width(), self.height()
        if w / h > aspect:
            w = h * aspect
        else:
            h = w / aspect
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def px_per_unit(self) -> float:
        return self.target_rect().width() / self._canvas.frame_width

    def to_units(self, pos: QPointF) -> np.ndarray:
        """A widget position in Manim units."""
        center, ppu = self.target_rect().center(), self.px_per_unit()
        return np.array([(pos.x() - center.x()) / ppu, -(pos.y() - center.y()) / ppu])

    def units_transform(self) -> QTransform:
        """Manim units -> widget pixels."""
        center, ppu = self.target_rect().center(), self.px_per_unit()
        return QTransform(ppu, 0, 0, -ppu, center.x(), center.y())

    # -- rendering ---------------------------------------------------------------

    def render_at(self, t: float) -> None:
        if self._canvas is None or self._evaluator is None:
            return
        rect = self.target_rect()
        scale = self.devicePixelRatioF() * (0.5 if self.half_resolution else 1.0)
        size = (max(2, int(rect.width() * scale)), max(2, int(rect.height() * scale)))
        if self._camera is None or size != self._camera_size:
            self._camera = m.Camera(
                pixel_width=size[0],
                pixel_height=size[1],
                frame_width=self._canvas.frame_width,
                frame_height=self._canvas.frame_height,
                background_color=m.ManimColor(self._canvas.background),
                background_opacity=1.0,
            )
            self._camera_size = size
        start = time.perf_counter()
        layers = self._evaluator.frame_layers(t)
        pixels = render_frame(self._camera, [mob for _, mob in layers])
        self.outline = self._outline(layers, t)  # built now: the mobjects are shared buffers
        self.last_render_ms = (time.perf_counter() - start) * 1000
        height, width = pixels.shape[:2]
        self._image = QImage(pixels.data, width, height, 4 * width, QImage.Format.Format_RGBA8888).copy()
        self.update()

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
        return Outline(path, path.boundingRect(), anchor, box)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#1e1e1e"))
        if self._image is not None and self._canvas is not None:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawImage(self.target_rect(), self._image)
            if self.outline is not None:
                self._paint_outline(painter)
        painter.end()

    def _paint_outline(self, painter: QPainter) -> None:
        to_px = self.units_transform()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setClipRect(self.target_rect())
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

    def mousePressEvent(self, event) -> None:
        if self.tool is None or self._canvas is None or event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        self.setFocus()
        self.tool.press(event.position(), event.modifiers())

    def mouseDoubleClickEvent(self, event) -> None:
        if self.tool is None or self._canvas is None or event.button() != Qt.MouseButton.LeftButton:
            super().mouseDoubleClickEvent(event)
            return
        self.tool.double_click(event.position())

    def mouseMoveEvent(self, event) -> None:
        if self.tool is not None and self._canvas is not None:
            self.tool.move(event.position(), event.modifiers())

    def mouseReleaseEvent(self, event) -> None:
        if self.tool is not None and self._canvas is not None:
            self.tool.release()

    def keyPressEvent(self, event) -> None:
        if self.tool is not None and self._canvas is not None and self.tool.key(event):
            return
        super().keyPressEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.resized.emit()
