"""Fast preview: draw Manim's computed geometry with QPainter.

Mirrors ``manim.camera.Camera`` (Cairo) so preview and export agree:

* each VMobject is a list of cubic Bezier subpaths split where anchors do not meet;
* draw order per VMobject is background stroke, fill, stroke;
* fill uses the non-zero winding rule (Cairo's default; Qt defaults to odd-even,
  which would punch wrong holes in glyphs);
* line width is ``stroke_width * 0.01`` frame units, scaled by the camera matrix;
* several colours on one VMobject become a linear gradient between
  ``get_gradient_start_and_end_points()``.
"""

from __future__ import annotations

from collections.abc import Iterable

import manim as m
import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QTransform,
)

from ..core.model.schema import Canvas

CAIRO_LINE_WIDTH_MULTIPLE = 0.01

_JOIN = {
    m.LineJointType.AUTO: Qt.PenJoinStyle.MiterJoin,
    m.LineJointType.ROUND: Qt.PenJoinStyle.RoundJoin,
    m.LineJointType.BEVEL: Qt.PenJoinStyle.BevelJoin,
    m.LineJointType.MITER: Qt.PenJoinStyle.MiterJoin,
}
_CAP = {
    m.CapStyleType.AUTO: Qt.PenCapStyle.FlatCap,
    m.CapStyleType.ROUND: Qt.PenCapStyle.RoundCap,
    m.CapStyleType.BUTT: Qt.PenCapStyle.FlatCap,
    m.CapStyleType.SQUARE: Qt.PenCapStyle.SquareCap,
}


def camera_transform(canvas: Canvas, width_px: int, height_px: int) -> QTransform:
    """Manim frame units -> widget pixels (y up -> y down), same as Cairo's matrix."""
    sx = width_px / canvas.frame_width
    sy = height_px / canvas.frame_height
    return QTransform(sx, 0, 0, -sy, width_px / 2, height_px / 2)


def vmobject_path(vmob: m.VMobject) -> QPainterPath:
    path = QPainterPath()
    path.setFillRule(Qt.FillRule.WindingFill)
    points = vmob.points
    if len(points) == 0:
        return path
    nppcc = vmob.n_points_per_cubic_curve
    xy = points[:, :2].tolist()
    for start, end in vmob.get_subpath_split_indices_from_points(points, n_dims=2):
        start, end = int(start), int(end)
        if end - start < nppcc:
            continue
        path.moveTo(*xy[start])
        for i in range(start, end - nppcc + 1, nppcc):
            (x1, y1), (x2, y2), (x3, y3) = xy[i + 1], xy[i + 2], xy[i + 3]
            path.cubicTo(x1, y1, x2, y2, x3, y3)
        if vmob.consider_points_equals_2d(points[start], points[end - 1]):
            path.closeSubpath()
    return path


def _brush(vmob: m.VMobject, rgbas: np.ndarray) -> QBrush | None:
    if len(rgbas) == 0 or not rgbas[:, 3].any():
        return None
    if len(rgbas) == 1:
        r, g, b, a = rgbas[0]
        return QBrush(QColor.fromRgbF(r, g, b, a))
    p0, p1 = vmob.get_gradient_start_and_end_points()
    grad = QLinearGradient(QPointF(p0[0], p0[1]), QPointF(p1[0], p1[1]))
    for offset, (r, g, b, a) in zip(np.linspace(0, 1, len(rgbas)), rgbas, strict=True):
        grad.setColorAt(float(offset), QColor.fromRgbF(r, g, b, a))
    return QBrush(grad)


def _pen(vmob: m.VMobject, background: bool) -> QPen | None:
    width = vmob.get_stroke_width(background)
    if width == 0:
        return None
    rgbas = vmob.get_stroke_rgbas(background)
    brush = _brush(vmob, rgbas)
    if brush is None:
        return None
    pen = QPen(brush, width * CAIRO_LINE_WIDTH_MULTIPLE)
    pen.setJoinStyle(_JOIN.get(vmob.joint_type, Qt.PenJoinStyle.MiterJoin))
    pen.setCapStyle(_CAP.get(vmob.cap_style, Qt.PenCapStyle.FlatCap))
    return pen


def paint(
    painter: QPainter, canvas: Canvas, mobjects: Iterable[m.Mobject], width_px: int, height_px: int
) -> None:
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.fillRect(0, 0, width_px, height_px, QColor(canvas.background))
    painter.setTransform(camera_transform(canvas, width_px, height_px))
    for mob in mobjects:
        for sub in mob.family_members_with_points():
            if isinstance(sub, m.VMobject):
                _paint_vmobject(painter, sub)
            # ImageMobject preview: TODO (draw QImage with the corner transform)


def _paint_vmobject(painter: QPainter, vmob: m.VMobject) -> None:
    path = vmobject_path(vmob)
    if path.isEmpty():
        return
    background = _pen(vmob, background=True)
    if background is not None:
        painter.strokePath(path, background)
    fill = _brush(vmob, vmob.get_fill_rgbas())
    if fill is not None:
        painter.fillPath(path, fill)
    stroke = _pen(vmob, background=False)
    if stroke is not None:
        painter.strokePath(path, stroke)


def render_image(canvas: Canvas, mobjects: Iterable[m.Mobject], width_px: int, height_px: int) -> QImage:
    image = QImage(width_px, height_px, QImage.Format.Format_RGBA8888)
    painter = QPainter(image)
    try:
        paint(painter, canvas, mobjects, width_px, height_px)
    finally:
        painter.end()
    return image


def image_to_array(image: QImage) -> np.ndarray:
    ptr = image.constBits()
    arr = np.frombuffer(ptr, dtype=np.uint8, count=image.sizeInBytes())
    return arr.reshape(image.height(), image.bytesPerLine() // 4, 4)[:, : image.width()].copy()
