"""How the Lumen timeline paints (P17.4b, ADR 0063): colours read from the theme at paint time, bars
and keys. Shared by the timeline, the graph editor and the curve editor; nothing here keeps a colour, so
a theme switch (``theme.set_theme``) repaints everything in the new set.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen

from ..style import theme

BAR_RADIUS = 8.0  # clip, cue and sound bars
BAR_PAD = 9.0  # a bar label's inset


def colour(token: str, alpha: float | None = None) -> QColor:
    """A theme token as a QColor, read now; ``alpha`` (0..1) replaces its alpha."""
    c = theme.qcolor(getattr(theme.THEME, token))
    if alpha is not None:
        c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


def sub_band() -> QColor:
    """Behind a property row (P7.3): the hairline colour at half its strength."""
    c = colour("line")
    c.setAlphaF(c.alphaF() * 0.5)
    return c


def shade(c: QColor, amount: float) -> QColor:
    """``c`` moved towards white (``amount`` > 0) or black (< 0) by ``abs(amount)``, alpha kept."""
    target = 255 if amount > 0 else 0
    t = min(abs(amount), 1.0)
    out = QColor(
        round(c.red() + (target - c.red()) * t),
        round(c.green() + (target - c.green()) * t),
        round(c.blue() + (target - c.blue()) * t),
    )
    out.setAlpha(c.alpha())
    return out


def font(role: str, kind: str = "ui", weight: QFont.Weight | None = None) -> QFont:
    """``theme.font(role, kind=kind)``, at another weight when one is given."""
    f = theme.font(role, kind=kind)
    if weight is not None:
        f.setWeight(weight)
    return f


def shape_pen(width: float) -> QPen:
    """A pen that only gives an item's shape its width (hit tests); the item paints its own look."""
    pen = QPen(Qt.GlobalColor.transparent)
    pen.setWidthF(width)
    return pen


def paint_bar(
    painter: QPainter,
    rect: QRectF,
    fill: QColor,
    selected: bool,
    label: str = "",
    *,
    tint: bool = False,
    text: QColor | None = None,
) -> None:
    """A Lumen bar: a rounded rectangle with a soft shadow; ``fill`` as a vertical gradient (lighter at
    the top) and a 1 px inner highlight, or with ``tint`` a translucent wash with a ring in that colour;
    selected, a ring (``bar_selected``) and a soft glow around it; ``label`` elided inside."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    r = max(0.0, min(BAR_RADIUS, rect.height() / 2, rect.width() / 2))
    painter.setPen(Qt.PenStyle.NoPen)
    inside = QPainterPath()
    inside.addRoundedRect(rect, r, r)
    if selected:  # rings around the bar (never under it: a tinted bar would show them through)
        for grow, alpha in ((5.0, 0.08), (3.5, 0.14), (2.0, 1.0)):  # the glow widest first, then the ring
            outside = QPainterPath()
            outside.addRoundedRect(rect.adjusted(-grow, -grow, grow, grow), r + grow, r + grow)
            painter.fillPath(outside.subtracted(inside), colour("bar_selected", alpha))
    elif not tint:
        painter.setBrush(colour("shadow", 0.28 if theme.THEME.dark else 0.14))
        painter.drawRoundedRect(rect.translated(0, 1.5), r, r)
    if tint:
        wash = QColor(fill)
        wash.setAlphaF(0.2)
        painter.setBrush(wash)
        edge = QColor(fill)
        edge.setAlphaF(0.6)
        painter.setPen(QPen(edge, 1))
        painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), r, r)
    else:
        gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        gradient.setColorAt(0.0, shade(fill, 0.1))
        gradient.setColorAt(1.0, shade(fill, -0.06))
        painter.setBrush(QBrush(gradient))
        painter.drawRoundedRect(rect, r, r)
        if rect.width() > 4:
            highlight = colour("bar_text", 0.22)
            painter.setPen(QPen(highlight, 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), max(r - 0.5, 0), max(r - 0.5, 0))
    if label and rect.width() > 24:
        painter.setFont(font("caption", weight=QFont.Weight.DemiBold))
        painter.setPen(text if text is not None else colour("bar_text"))
        inner = rect.adjusted(BAR_PAD, 0, -BAR_PAD + 4, 0)
        shown = painter.fontMetrics().elidedText(
            label, Qt.TextElideMode.ElideRight, int(max(inner.width(), 0))
        )
        painter.drawText(inner, Qt.AlignmentFlag.AlignVCenter, shown)
    painter.restore()


def paint_key(painter: QPainter, center: QPointF, half: float, fill: QColor, selected: bool) -> None:
    """A key: a rotated rounded square ``half`` from centre to corner, with a dark edge; selected,
    an accent halo around it."""
    side = half * 1.4142
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.translate(center)
    painter.rotate(45)
    square = QRectF(-side / 2, -side / 2, side, side)
    if selected:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(colour("accent", 0.35))
        painter.drawRoundedRect(square.adjusted(-3, -3, 3, 3), 3.5, 3.5)
        painter.setBrush(colour("accent"))
        painter.drawRoundedRect(square.adjusted(-1.8, -1.8, 1.8, 1.8), 2.8, 2.8)
    painter.setPen(QPen(colour("key_edge"), 1.2))
    painter.setBrush(fill)
    painter.drawRoundedRect(square, side * 0.22, side * 0.22)
    painter.restore()
