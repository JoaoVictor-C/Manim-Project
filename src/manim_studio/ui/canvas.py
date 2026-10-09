"""Canvas widget: shows the exact Manim (Cairo) frame at the playhead, letterboxed."""

from __future__ import annotations

import time

import manim as m
from PySide6.QtCore import QRectF, Signal
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QWidget

from ..core.evaluator import Evaluator
from ..core.schema import Canvas
from ..render.cairo_export import render_frame


class CanvasWidget(QWidget):
    """Letterboxed view of the Manim frame at the current time."""

    resized = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(320, 180)
        self._canvas: Canvas | None = None
        self._evaluator: Evaluator | None = None
        self._camera: m.Camera | None = None
        self._camera_size: tuple[int, int] = (0, 0)
        self._image: QImage | None = None
        self.half_resolution = False
        self.last_render_ms = 0.0

    def set_scene(self, canvas: Canvas, evaluator: Evaluator) -> None:
        self._canvas, self._evaluator = canvas, evaluator
        self._camera = None

    def target_rect(self) -> QRectF:
        assert self._canvas is not None
        aspect = self._canvas.width_px / self._canvas.height_px
        w, h = self.width(), self.height()
        if w / h > aspect:
            w = h * aspect
        else:
            h = w / aspect
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

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
        pixels = render_frame(self._camera, self._evaluator.frame(t))
        self.last_render_ms = (time.perf_counter() - start) * 1000
        height, width = pixels.shape[:2]
        self._image = QImage(pixels.data, width, height, 4 * width, QImage.Format.Format_RGBA8888).copy()
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#1e1e1e"))
        if self._image is not None and self._canvas is not None:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawImage(self.target_rect(), self._image)
        painter.end()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.resized.emit()
