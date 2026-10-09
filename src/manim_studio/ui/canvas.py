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
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QTransform
from PySide6.QtWidgets import QWidget

from ..core.evaluator import Evaluator
from ..core.schema import Canvas
from ..render.cairo_export import render_frame
from ..render.qt_paths import vmobject_path

OUTLINE_COLOR = QColor("#38bdf8")


@dataclass
class Outline:
    """The selected layer as drawn at the current time, in Manim units."""

    path: QPainterPath
    bounds: QRectF
    anchor: tuple[float, float]


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
        mob = dict(layers).get(self.selected_layer) if self.selected_layer else None
        if mob is None:
            return None
        path = QPainterPath()
        if isinstance(mob, m.ImageMobject):
            ul, ur, dl, dr = (QPointF(*mob.points[i, :2]) for i in range(4))
            path.moveTo(ul)
            for corner in (ur, dr, dl):
                path.lineTo(corner)
            path.closeSubpath()
        else:
            for sub in mob.family_members_with_points():
                if isinstance(sub, m.VMobject):
                    path.addPath(vmobject_path(sub))
        layer = self._evaluator.project.layer(self.selected_layer)
        anchor = self._evaluator.transform_at(layer, t).position
        return Outline(path, path.boundingRect(), (float(anchor[0]), float(anchor[1])))

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
        painter.drawRect(to_px.mapRect(self.outline.bounds))
        cx, cy = to_px.map(QPointF(*self.outline.anchor)).toTuple()
        painter.setPen(pen)
        painter.drawLine(QPointF(cx - 6, cy), QPointF(cx + 6, cy))
        painter.drawLine(QPointF(cx, cy - 6), QPointF(cx, cy + 6))

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
