"""Small drawings of the library's objects (Lumen, ADR 0087): the glyph on an insert tool, a tile of the Add
object popover, a chip of its recent row.

A shape, a line, a plane or a solid is drawn as its own outline in a unit square (a circle is a circle, an
arrow an arrow), the way a design tool shows its shapes; a type with no outline of its own (text, an image,
code, a plugin's object) shows its kind's icon from ``icons``. Strokes are cosmetic (the same hairline at any
size) and take the theme's colours *when painted*, named by token (``tint``), so a theme switch needs nothing
from them.
"""

from __future__ import annotations

import math
from functools import lru_cache

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QIconEngine, QPainter, QPainterPath, QPen, QPixmap

from . import icons, theme

STROKE = 1.5  # px: the outline's width at any size

# a type with no outline of its own -> the icon of its kind (names in ``icons.NAMES``)
FALLBACK = {
    "Text": "text",
    "DecimalNumber": "number",
    "MathTex": "maths",
    "Tex": "maths",
    "ImageMobject": "image",
    "SVGMobject": "shape",
    "TracedPath": "trace",
    "Axes": "axes",
    "Code": "code",
    "Python": "python",
    "Camera": "camera",
}
FILLED = frozenset({"Dot"})


def _poly(*points: tuple[float, float], closed: bool = True) -> QPainterPath:
    path = QPainterPath(QPointF(*points[0]))
    for x, y in points[1:]:
        path.lineTo(x, y)
    if closed:
        path.closeSubpath()
    return path


def _ngon(n: int, radius: float = 0.44, start: float = -90.0) -> list[tuple[float, float]]:
    return [
        (0.5 + radius * math.cos(math.radians(start + 360.0 * i / n)),
         0.5 + radius * math.sin(math.radians(start + 360.0 * i / n)))
        for i in range(n)
    ]  # fmt: skip


def _star(points: int = 5, outer: float = 0.46, inner: float = 0.19) -> QPainterPath:
    corners = []
    for i in range(points * 2):
        radius = outer if i % 2 == 0 else inner
        angle = math.radians(-90 + 180.0 * i / points)
        corners.append((0.5 + radius * math.cos(angle), 0.5 + radius * math.sin(angle)))
    return _poly(*corners)


def _polygram(n: int = 5, step: int = 2) -> QPainterPath:
    corners = _ngon(n, 0.46)
    path = QPainterPath(QPointF(*corners[0]))
    for i in range(1, n + 1):
        path.lineTo(*corners[(i * step) % n])
    return path


def _lines(*segments: tuple[float, float, float, float]) -> QPainterPath:
    path = QPainterPath()
    for x1, y1, x2, y2 in segments:
        path.moveTo(x1, y1)
        path.lineTo(x2, y2)
    return path


def _head(
    path: QPainterPath, tip: tuple[float, float], source: tuple[float, float], size: float = 0.22
) -> None:
    """An open arrow head at ``tip`` for a stroke that arrives from ``source``."""
    angle = math.atan2(tip[1] - source[1], tip[0] - source[0])
    for turn in (math.radians(150), math.radians(-150)):
        path.moveTo(*tip)
        path.lineTo(tip[0] + size * math.cos(angle + turn), tip[1] + size * math.sin(angle + turn))


def _arrow(both: bool = False, start: tuple[float, float] = (0.1, 0.88)) -> QPainterPath:
    end = (0.9, 0.12)
    path = _lines((*start, *end))
    _head(path, end, start)
    if both:
        _head(path, start, end)
    return path


def _curve(both: bool) -> QPainterPath:
    path = QPainterPath(QPointF(0.1, 0.82))
    path.quadTo(0.3, 0.08, 0.9, 0.34)
    _head(path, (0.9, 0.34), (0.62, 0.2))
    if both:
        _head(path, (0.1, 0.82), (0.2, 0.5))
    return path


def _arc(rect: QRectF, start: float, sweep: float) -> QPainterPath:
    path = QPainterPath()
    path.arcMoveTo(rect, start)
    path.arcTo(rect, start, sweep)
    return path


def _grid(lines: int = 3) -> QPainterPath:
    path = _poly((0.08, 0.08), (0.92, 0.08), (0.92, 0.92), (0.08, 0.92))
    for i in range(1, lines):
        t = 0.08 + 0.84 * i / lines
        path.moveTo(t, 0.08)
        path.lineTo(t, 0.92)
        path.moveTo(0.08, t)
        path.lineTo(0.92, t)
    return path


def _cross() -> QPainterPath:
    a, b = 0.35, 0.65
    return _poly(
        (a, 0.08), (b, 0.08), (b, a), (0.92, a), (0.92, b), (b, b), (b, 0.92), (a, 0.92), (a, b), (0.08, b),
        (0.08, a), (a, a),
    )  # fmt: skip


def _annular_sector() -> QPainterPath:
    outer, inner = QRectF(0.06, 0.06, 0.88, 0.88), QRectF(0.28, 0.28, 0.44, 0.44)
    sweep = 110.0
    path = QPainterPath()
    path.arcMoveTo(outer, 0)
    path.arcTo(outer, 0, sweep)
    angle = math.radians(sweep)
    path.lineTo(0.5 + 0.22 * math.cos(angle), 0.5 - 0.22 * math.sin(angle))
    path.arcTo(inner, sweep, -sweep)
    path.closeSubpath()
    return path


def _sector() -> QPainterPath:
    path = QPainterPath(QPointF(0.5, 0.5))
    path.lineTo(0.94, 0.5)
    path.arcTo(QRectF(0.06, 0.06, 0.88, 0.88), 0, 120)
    path.closeSubpath()
    return path


def _brace() -> QPainterPath:
    path = QPainterPath(QPointF(0.06, 0.66))
    path.quadTo(0.06, 0.5, 0.22, 0.5)
    path.lineTo(0.38, 0.5)
    path.quadTo(0.5, 0.5, 0.5, 0.32)
    path.quadTo(0.5, 0.5, 0.62, 0.5)
    path.lineTo(0.78, 0.5)
    path.quadTo(0.94, 0.5, 0.94, 0.66)
    return path


def _circles(*circles: tuple[float, float, float]) -> QPainterPath:
    path = QPainterPath()
    for x, y, r in circles:
        path.addEllipse(QPointF(x, y), r, r)
    return path


def _union(*paths: QPainterPath) -> QPainterPath:
    out = QPainterPath()
    for p in paths:
        out.addPath(p)
    return out


def _cube() -> QPainterPath:
    hexagon = _ngon(6)
    path = _poly(*hexagon)
    for i in (1, 3, 5):
        path.moveTo(0.5, 0.5)
        path.lineTo(*hexagon[i])
    return path


def _cylinder() -> QPainterPath:
    path = QPainterPath()
    path.addEllipse(QRectF(0.2, 0.08, 0.6, 0.26))
    path.moveTo(0.2, 0.21)
    path.lineTo(0.2, 0.79)
    path.moveTo(0.8, 0.21)
    path.lineTo(0.8, 0.79)
    path.addPath(_arc(QRectF(0.2, 0.66, 0.6, 0.26), 180, 180))
    return path


def _cone() -> QPainterPath:
    path = _lines((0.5, 0.08, 0.16, 0.76), (0.5, 0.08, 0.84, 0.76))
    path.addPath(_arc(QRectF(0.16, 0.64, 0.68, 0.26), 180, 180))
    return path


def _prism() -> QPainterPath:
    front = [(0.08, 0.86), (0.58, 0.86), (0.33, 0.42)]
    back = [(x + 0.3, y - 0.26) for x, y in front]
    path = _union(_poly(*front), _poly(*back))
    for a, b in zip(front, back, strict=True):
        path.moveTo(*a)
        path.lineTo(*b)
    return path


def _tetrahedron() -> QPainterPath:
    path = _poly((0.5, 0.08), (0.94, 0.82), (0.06, 0.82))
    for x, y in ((0.5, 0.08), (0.06, 0.82), (0.94, 0.82)):
        path.moveTo(x, y)
        path.lineTo(0.52, 0.64)
    return path


def _octahedron() -> QPainterPath:
    path = _poly((0.5, 0.06), (0.94, 0.5), (0.5, 0.94), (0.06, 0.5))
    path.moveTo(0.06, 0.5)
    path.lineTo(0.5, 0.64)
    path.lineTo(0.94, 0.5)
    path.moveTo(0.5, 0.06)
    path.lineTo(0.5, 0.64)
    return path


def _nested(n: int, inner_radius: float) -> QPainterPath:
    outer, inner = _ngon(n), _ngon(n, inner_radius, 90.0)
    path = _union(_poly(*outer), _poly(*inner))
    for a, b in zip(outer, _ngon(n, inner_radius), strict=True):
        path.moveTo(*a)
        path.lineTo(*b)
    return path


def _axes_3d() -> QPainterPath:
    return _lines((0.46, 0.54, 0.92, 0.54), (0.46, 0.54, 0.46, 0.08), (0.46, 0.54, 0.1, 0.92))


def _number_line() -> QPainterPath:
    path = _lines((0.06, 0.5, 0.94, 0.5))
    for i in range(5):
        x = 0.16 + 0.17 * i
        path.moveTo(x, 0.38)
        path.lineTo(x, 0.62)
    _head(path, (0.94, 0.5), (0.7, 0.5), 0.14)
    return path


def _plane_axes() -> QPainterPath:
    path = _lines((0.06, 0.5, 0.94, 0.5), (0.5, 0.94, 0.5, 0.06))
    path.addEllipse(QPointF(0.72, 0.3), 0.07, 0.07)
    return path


def _polar() -> QPainterPath:
    path = _circles((0.5, 0.5, 0.44), (0.5, 0.5, 0.22))
    for dx, dy in ((0.44, 0.0), (0.0, 0.44), (0.311, 0.311), (0.311, -0.311)):
        path.moveTo(0.5 - dx, 0.5 - dy)
        path.lineTo(0.5 + dx, 0.5 + dy)
    return path


def _axes() -> QPainterPath:
    path = _lines((0.14, 0.08, 0.14, 0.86), (0.14, 0.86, 0.92, 0.86))
    path.moveTo(0.22, 0.7)
    path.cubicTo(0.4, 0.14, 0.62, 0.92, 0.88, 0.28)
    return path


def _dashed() -> QPainterPath:
    start, end = (0.1, 0.88), (0.9, 0.12)
    segments = []
    for a, b in ((0.0, 0.22), (0.39, 0.61), (0.78, 1.0)):
        segments.append(
            (
                start[0] + (end[0] - start[0]) * a,
                start[1] + (end[1] - start[1]) * a,
                start[0] + (end[0] - start[0]) * b,
                start[1] + (end[1] - start[1]) * b,
            )
        )
    return _lines(*segments)


def _builders() -> dict[str, QPainterPath]:
    ellipse = QPainterPath()
    ellipse.addEllipse(QRectF(0.06, 0.24, 0.88, 0.52))
    rectangle = QPainterPath()
    rectangle.addRect(QRectF(0.06, 0.22, 0.88, 0.56))
    square = QPainterPath()
    square.addRect(QRectF(0.16, 0.16, 0.68, 0.68))
    rounded = QPainterPath()
    rounded.addRoundedRect(QRectF(0.06, 0.22, 0.88, 0.56), 0.18, 0.18)
    ring = _circles((0.5, 0.5, 0.44), (0.5, 0.5, 0.22))
    bezier = QPainterPath(QPointF(0.1, 0.84))
    bezier.cubicTo(0.1, 0.1, 0.9, 0.9, 0.9, 0.16)
    zigzag = _poly((0.08, 0.76), (0.3, 0.24), (0.52, 0.72), (0.72, 0.3), (0.92, 0.5), closed=False)
    angle = _lines((0.9, 0.82, 0.12, 0.82), (0.12, 0.82, 0.72, 0.22))
    angle.addPath(_arc(QRectF(-0.18, 0.52, 0.6, 0.6), 0, 45))
    right_angle = _poly((0.12, 0.1), (0.12, 0.88), (0.9, 0.88), closed=False)
    right_angle.moveTo(0.12, 0.64)
    right_angle.lineTo(0.36, 0.64)
    right_angle.lineTo(0.36, 0.88)
    connector = _union(_circles((0.2, 0.74, 0.1), (0.8, 0.26, 0.1)), _lines((0.27, 0.67, 0.73, 0.33)))
    sphere = _union(_circles((0.5, 0.5, 0.44)), _arc(QRectF(0.06, 0.36, 0.88, 0.28), 180, 180))
    torus = QPainterPath()
    torus.addEllipse(QRectF(0.04, 0.26, 0.92, 0.48))
    torus.addEllipse(QRectF(0.3, 0.4, 0.4, 0.2))
    return {
        "Circle": _circles((0.5, 0.5, 0.42)),
        "Ellipse": ellipse,
        "Square": square,
        "Rectangle": rectangle,
        "RoundedRectangle": rounded,
        "Triangle": _poly((0.5, 0.1), (0.92, 0.86), (0.08, 0.86)),
        "RightTriangle": _poly((0.16, 0.12), (0.16, 0.86), (0.9, 0.86)),
        "RegularPolygon": _poly(*_ngon(5)),
        "RegularPolygram": _polygram(5, 2),
        "Pentagon": _poly(*_ngon(5)),
        "Hexagon": _poly(*_ngon(6, 0.46, 0)),
        "Octagon": _poly(*_ngon(8, 0.46, -22.5)),
        "Nonagon": _poly(*_ngon(9)),
        "Decagon": _poly(*_ngon(10, 0.46, -90)),
        "Rhombus": _poly((0.5, 0.06), (0.94, 0.5), (0.5, 0.94), (0.06, 0.5)),
        "Parallelogram": _poly((0.28, 0.22), (0.94, 0.22), (0.72, 0.78), (0.06, 0.78)),
        "Trapezoid": _poly((0.3, 0.22), (0.7, 0.22), (0.94, 0.78), (0.06, 0.78)),
        "Polygon": _poly((0.12, 0.4), (0.42, 0.1), (0.9, 0.28), (0.82, 0.8), (0.3, 0.9)),
        "Star": _star(),
        "Cross": _cross(),
        "Dot": _circles((0.5, 0.5, 0.2)),
        "Sector": _sector(),
        "Annulus": ring,
        "AnnularSector": _annular_sector(),
        "Connector": connector,
        "Line": _lines((0.1, 0.88, 0.9, 0.12)),
        "DashedLine": _dashed(),
        "Arrow": _arrow(),
        "DoubleArrow": _arrow(both=True),
        "Vector": _union(_arrow(start=(0.16, 0.84)), _circles((0.16, 0.84, 0.04))),
        "CurvedArrow": _curve(False),
        "CurvedDoubleArrow": _curve(True),
        "Arc": _arc(QRectF(0.1, 0.3, 0.8, 0.8), 25, 130),
        "ArcBetweenPoints": _union(_arc(QRectF(0.1, 0.3, 0.8, 0.8), 25, 130), _circles((0.19, 0.5, 0.04))),
        "CubicBezier": bezier,
        "Angle": angle,
        "RightAngle": right_angle,
        "BraceBetweenPoints": _brace(),
        "Polyline": zigzag,
        "Cube": _cube(),
        "Sphere": sphere,
        "Cylinder": _cylinder(),
        "Cone": _cone(),
        "Torus": torus,
        "Prism": _prism(),
        "Tetrahedron": _tetrahedron(),
        "Octahedron": _octahedron(),
        "Dodecahedron": _nested(5, 0.2),
        "Icosahedron": _nested(6, 0.22),
        "NumberLine": _number_line(),
        "NumberPlane": _grid(),
        "ComplexPlane": _union(_grid(2), _circles((0.72, 0.3, 0.06))),
        "PolarPlane": _polar(),
        "ThreeDAxes": _axes_3d(),
        "Axes": _axes(),
    }


@lru_cache(maxsize=1)
def _paths() -> dict[str, QPainterPath]:
    return _builders()


def has_outline(type_name: str) -> bool:
    return type_name in _paths()


def paint(
    painter: QPainter, rect: QRectF, type_name: str, tint: str = "text", *, disabled: bool = False
) -> None:
    """Draw ``type_name`` centred in ``rect`` (as large as fits) in the theme colour named ``tint``."""
    path = _paths().get(type_name)
    if path is None:
        name = FALLBACK.get(type_name, "shape")
        icons.icon(name, tint).paint(
            painter, rect.toRect(), mode=QIcon.Mode.Disabled if disabled else QIcon.Mode.Normal
        )
        return
    colours = theme.THEME
    ink = theme.qcolor(colours.disabled if disabled else getattr(colours, tint))
    side = min(rect.width(), rect.height())
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.translate(rect.center().x() - side / 2, rect.center().y() - side / 2)
    painter.scale(side, side)
    pen = QPen(ink, STROKE)
    pen.setCosmetic(True)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(ink if type_name in FILLED else Qt.BrushStyle.NoBrush)
    painter.drawPath(path)
    painter.restore()


class _GlyphEngine(QIconEngine):
    """A ``QIcon`` that draws the glyph when it is painted, in the theme then in use."""

    def __init__(self, type_name: str, tint: str) -> None:
        super().__init__()
        self.type_name, self.tint = type_name, tint

    def clone(self) -> QIconEngine:
        return _GlyphEngine(self.type_name, self.tint)

    def actualSize(self, size: QSize, mode: QIcon.Mode, state: QIcon.State) -> QSize:
        return size

    def pixmap(self, size: QSize, mode: QIcon.Mode, state: QIcon.State) -> QPixmap:
        pixmap = QPixmap(size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        self.paint(painter, QRect(0, 0, size.width(), size.height()), mode, state)
        painter.end()
        return pixmap

    def paint(self, painter: QPainter, rect: QRect, mode: QIcon.Mode, state: QIcon.State) -> None:
        paint(painter, QRectF(rect), self.type_name, self.tint, disabled=mode == QIcon.Mode.Disabled)


def icon(type_name: str, tint: str = "text") -> QIcon:
    """The glyph of ``type_name`` as a ``QIcon`` (for menus)."""
    return QIcon(_GlyphEngine(type_name, tint))
