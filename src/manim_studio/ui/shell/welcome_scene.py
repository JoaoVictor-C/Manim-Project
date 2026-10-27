"""The picture on the welcome page (Lumen, ADR 0063): mathematics being drawn.

A machine of turning circles (a Fourier series: each circle rides on the edge of the one before) whose last
point draws a glowing curve. Every few seconds the circles change size and the curve melts into another
(a three-pointed deltoid, an astroid, a four-lobed flower, a rosette) and the whole figure turns slowly, so it
is never the same twice. Around it a field of particles flows on invisible currents, leaving soft trails, and
three large colours breathe behind it. The cursor stirs the particles, and the layers shift a few pixels
against each other as it moves (parallax).

Everything is painted by hand from the theme's tokens. ``MathScene`` keeps the state (a clock, the particles,
the picture of their trails) and ``paint`` draws a frame; the welcome page calls ``step`` from a timer while
it is on screen. With motion off nothing steps: ``paint`` draws one finished, still frame.
"""

from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QLineF, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QImage,
    QPainter,
    QPen,
    QPolygonF,
    QRadialGradient,
)

from ..style import theme

# The circles, by how many turns each makes while the pen goes round once (negative: the other way), and the
# sizes of each in the figures the machine passes through.
FREQS = (1, -2, -3, 4, 5)
FIGURES = (
    (1.0, 0.50, 0.00, 0.00, 0.00),  # a deltoid
    (1.0, 0.00, 0.34, 0.00, 0.00),  # an astroid
    (1.0, 0.00, 0.00, 0.00, 0.42),  # a four-lobed flower
    (1.0, 0.36, 0.00, 0.24, 0.12),  # a rosette
)
HOLD, BLEND = 8.5, 3.5  # seconds a figure stays, seconds it takes to become the next
PEN_SPEED = 0.62  # radians per second of the pen's turn
TRAIL_TURNS = 0.9  # how much of a full turn the glowing trail covers
TRAIL_POINTS = 160
TURN_SPEED = 0.032  # the whole figure turns, radians per second
PARTICLES = 200
FLOW_SPEED = 36.0  # px per second
GLOW_SCALE = 4.0  # the backdrop glows are painted at 1/4 size
STILL_TIME = 2.6  # the moment drawn when nothing moves
EDGE = 0.985  # the particles live inside this fraction of the ellipse that fills the area


def _ease(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return 1.0 - (1.0 - x) ** 3


def _smooth(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return x * x * (3.0 - 2.0 * x)


def figure_radii(t: float) -> np.ndarray:
    """The sizes of the circles at time ``t``: a figure held, then blended into the next one."""
    cycle = HOLD + BLEND
    index = int(t // cycle) % len(FIGURES)
    into = (t % cycle) - HOLD
    mix = _smooth(into / BLEND) if into > 0 else 0.0
    return np.array(FIGURES[index]) * (1.0 - mix) + np.array(FIGURES[(index + 1) % len(FIGURES)]) * mix


def machine(radii: np.ndarray, theta: float, turn: float) -> list[complex]:
    """The centres of the circles for the pen at ``theta`` (0 first, the pen last), turned by ``turn``."""
    points = [0j]
    for radius, freq in zip(radii, FREQS, strict=True):
        points.append(points[-1] + radius * complex(math.cos(freq * theta), math.sin(freq * theta)))
    spin = complex(math.cos(turn), math.sin(turn))
    return [p * spin for p in points]


def trail(
    radii: np.ndarray, theta: float, turn: float, turns: float, count: int = TRAIL_POINTS
) -> np.ndarray:
    """The pen's last ``turns`` of a full turn as ``count`` points (complex), oldest first."""
    angles = theta - np.linspace(turns * 2 * math.pi, 0.0, count)
    total = np.zeros(count, dtype=complex)
    for radius, freq in zip(radii, FREQS, strict=True):
        if radius > 1e-6:
            total += radius * np.exp(1j * freq * angles)
    return total * complex(math.cos(turn), math.sin(turn))


class MathScene:
    """The state of the picture and how to paint a frame of it."""

    def __init__(self, seed: int = 7) -> None:
        self.rng = np.random.default_rng(seed)
        self.t = STILL_TIME
        self.size = (0.0, 0.0)
        self.ratio = 1.0
        self.buffer: QImage | None = None
        self.parallax = np.zeros(2)
        n = PARTICLES
        self.x = self.px = np.zeros(n)
        self.y = self.py = np.zeros(n)
        self.age = np.zeros(n)
        self.life = np.ones(n)
        self.hue = np.zeros(n, dtype=int)

    # -- the particles --------------------------------------------------------------------------------

    def resize(self, width: float, height: float, ratio: float = 1.0) -> None:
        """Make the picture of the trails for an area of this size (a new, warmed-up one when it changed)."""
        if (width, height, ratio) == (*self.size, self.ratio) or width < 40 or height < 40:
            return
        self.size, self.ratio = (width, height), ratio
        self.buffer = QImage(
            max(1, round(width * ratio)),
            max(1, round(height * ratio)),
            QImage.Format.Format_ARGB32_Premultiplied,
        )
        self.buffer.setDevicePixelRatio(ratio)
        self.buffer.fill(0)
        self._spawn(np.ones(PARTICLES, dtype=bool))
        self.age = self.rng.random(PARTICLES) * self.life  # not all born at once
        for _ in range(80):  # trails already there when the first frame shows
            self._advance(1 / 30, None, draw=True)

    def _spawn(self, which: np.ndarray) -> None:
        count = int(which.sum())
        if not count:
            return
        width, height = self.size
        angle = self.rng.random(count) * 2 * math.pi
        radius = np.sqrt(self.rng.random(count)) * EDGE
        self.x[which] = self.px[which] = width / 2 + np.cos(angle) * radius * width / 2
        self.y[which] = self.py[which] = height / 2 + np.sin(angle) * radius * height / 2
        self.age[which] = 0.0
        self.life[which] = 4.0 + self.rng.random(count) * 6.0
        self.hue[which] = self.rng.integers(0, 4, count)

    def step(self, dt: float, cursor: QPointF | None) -> None:
        """Move the clock, the particles and the parallax on by ``dt`` seconds; ``cursor`` is in the area."""
        dt = min(max(dt, 0.0), 0.06)
        self.t += dt
        width, height = self.size
        if width:
            target = np.zeros(2)
            if cursor is not None:
                target = np.array([cursor.x() / width - 0.5, cursor.y() / height - 0.5]) * 2.0
            self.parallax += (target - self.parallax) * min(1.0, dt * 3.0)
            self._advance(dt, cursor, draw=True)

    def _advance(self, dt: float, cursor: QPointF | None, *, draw: bool) -> None:
        if self.buffer is None:
            return
        width, height = self.size
        t, x, y = self.t, self.x, self.y
        angle = 2.1 * np.sin(x * 0.012 + t * 0.17) + 2.1 * np.cos(y * 0.014 - t * 0.12)
        angle += np.sin((x + y) * 0.007 + t * 0.21)
        vx, vy = np.cos(angle), np.sin(angle)
        dx, dy = x - width / 2, y - height / 2
        radius = np.hypot(dx, dy) + 1.0
        vx += -dy / radius * 0.9  # a slow swirl round the middle, the way the circles turn
        vy += dx / radius * 0.9
        if cursor is not None:  # the cursor stirs: a whirl and a little push away
            cx, cy = x - cursor.x(), y - cursor.y()
            near = np.hypot(cx, cy) + 20.0
            weight = np.exp(-(cx * cx + cy * cy) / (2 * 95.0**2))
            vx += (-cy / near * 2.6 + cx / near * 1.0) * weight
            vy += (cx / near * 2.6 + cy / near * 1.0) * weight
        self.px, self.py = x.copy(), y.copy()
        self.x = x + vx * FLOW_SPEED * dt
        self.y = y + vy * FLOW_SPEED * dt
        self.age = self.age + dt
        out = (
            ((self.x - width / 2) / (width / 2)) ** 2 + ((self.y - height / 2) / (height / 2)) ** 2
        ) > EDGE**2
        gone = out | (self.age > self.life)
        if draw:
            self._draw_trails(gone)
        self._spawn(gone)

    def _draw_trails(self, gone: np.ndarray) -> None:
        buffer = self.buffer
        assert buffer is not None
        painter = QPainter(buffer)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationOut)
        fade = QColor(Qt.GlobalColor.black)  # only its alpha counts: it erases
        fade.setAlpha(24)
        painter.fillRect(QRectF(0, 0, *self.size), fade)  # old trails fade a little each frame
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        c = theme.THEME
        palette = [
            theme.qcolor(c.accent),
            theme.qcolor(c.accent_2),
            theme.qcolor(c.morph),
            theme.qcolor(c.sound),
        ]
        width, height = self.size
        rim = np.hypot((self.x - width / 2) / (width / 2), (self.y - height / 2) / (height / 2))
        life = np.sin(np.pi * np.clip(self.age / self.life, 0.0, 1.0)) * np.clip((1.0 - rim) / 0.3, 0.0, 1.0)
        tier = np.minimum((life * 3.0).astype(int), 2)  # three strengths: born, grown, dying
        live = ~gone
        for hue in range(4):
            for level in range(3):
                pick = live & (self.hue == hue) & (tier == level)
                if not pick.any():
                    continue
                colour = QColor(palette[hue])
                colour.setAlphaF((0.3, 0.58, 0.85)[level])
                painter.setPen(QPen(colour, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                painter.drawLines(
                    [
                        QLineF(float(a), float(b), float(d), float(e))
                        for a, b, d, e in zip(
                            self.px[pick], self.py[pick], self.x[pick], self.y[pick], strict=True
                        )
                    ]
                )
        painter.end()

    # -- painting -------------------------------------------------------------------------------------

    def paint(
        self, painter: QPainter, area: QRectF, progress: float = 1.0, cursor: QPointF | None = None
    ) -> None:
        """One frame in ``area``. ``progress`` (0..1) is the entrance: the particles come first, then the
        circles one by one and the pen, the trail growing from nothing, the identity last. ``cursor`` is in
        the area's own coordinates (or None)."""
        if area.width() < 40 or area.height() < 40:
            return
        c = theme.THEME
        self.resize(area.width(), area.height(), painter.device().devicePixelRatioF())
        width, height = area.width(), area.height()
        t = self.t
        shift = self.parallax
        painter.save()
        painter.translate(area.topLeft())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        strength = 1.0 if c.dark else 0.55
        breath = 0.86 + 0.14 * math.sin(t * 1.05)

        # the colours behind: three large glows drifting on slow orbits, painted small and scaled up (they
        # are smooth, and a frame has to be cheap)
        phase = t * 0.33
        glows = (  # kept inside the area: their edges fade out before they reach its border
            (c.accent, math.cos(phase) * 0.09, math.sin(phase * 0.8) * 0.07, 0.46, 0.26),
            (c.accent_2, -math.cos(phase * 0.7 + 1.0) * 0.11, math.sin(phase * 0.9 + 2.0) * 0.08, 0.4, 0.19),
            (c.morph, math.sin(phase * 0.6 + 4.0) * 0.1, -math.cos(phase * 0.75) * 0.09, 0.34, 0.12),
        )
        reach = min(width, height)
        margin = 60.0
        small = QImage(
            max(1, round((width + 2 * margin) / GLOW_SCALE)),
            max(1, round((height + 2 * margin) / GLOW_SCALE)),
            QImage.Format.Format_ARGB32_Premultiplied,
        )
        small.fill(0)
        glow_painter = QPainter(small)
        glow_painter.scale(1 / GLOW_SCALE, 1 / GLOW_SCALE)
        glow_painter.translate(margin, margin)
        glow_painter.setPen(Qt.PenStyle.NoPen)
        for token, ox, oy, size, alpha in glows:
            centre = QPointF(width / 2 + ox * width + shift[0] * 6, height / 2 + oy * height + shift[1] * 6)
            gradient = QRadialGradient(centre, size * reach)
            colour = QColor(theme.qcolor(token))
            colour.setAlphaF(min(1.0, alpha * strength * breath * _ease(progress / 0.4)))
            gradient.setColorAt(0.0, colour)
            colour.setAlphaF(0.0)
            gradient.setColorAt(1.0, colour)
            glow_painter.setBrush(gradient)
            glow_painter.drawRect(QRectF(-margin, -margin, width + 2 * margin, height + 2 * margin))
        glow_painter.end()
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(QRectF(-margin, -margin, width + 2 * margin, height + 2 * margin), small)

        # the trails of the particles
        if self.buffer is not None:
            painter.setOpacity(_ease((progress - 0.05) / 0.45))
            painter.drawImage(QPointF(shift[0] * 10, shift[1] * 10), self.buffer)
            painter.setOpacity(1.0)

        # the figure: rings, then the circles and the pen
        centre = QPointF(width / 2 + shift[0] * 16, height / 2 + shift[1] * 16)
        radii = figure_radii(t)
        extent = 0.43 * min(width, height) / max(float(radii.sum()), 0.5)
        self._paint_rings(painter, centre, 0.43 * min(width, height), progress, c)
        theta = t * PEN_SPEED
        turn = t * TURN_SPEED
        self._paint_trail(painter, centre, extent, radii, theta, turn, progress, c)
        self._paint_machine(painter, centre, extent, radii, theta, turn, progress, c)
        self._paint_identity(painter, QRectF(0, 0, width, height), progress, c)
        painter.restore()

    @staticmethod
    def _paint_rings(
        painter: QPainter, centre: QPointF, reach: float, progress: float, c: theme.Colours
    ) -> None:
        grow = _ease(progress / 0.35)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for fraction, alpha in ((1.0, 0.09), (0.66, 0.065), (0.33, 0.05)):
            colour = QColor(theme.qcolor(c.text))
            colour.setAlphaF(alpha * grow)
            painter.setPen(QPen(colour, 1))
            radius = reach * fraction * (0.7 + 0.3 * grow)
            painter.drawEllipse(centre, radius, radius)
        colour = QColor(theme.qcolor(c.text))
        colour.setAlphaF(0.06 * grow)
        painter.setPen(QPen(colour, 1))
        painter.drawLine(
            QPointF(centre.x() - reach * 1.08, centre.y()), QPointF(centre.x() + reach * 1.08, centre.y())
        )
        painter.drawLine(
            QPointF(centre.x(), centre.y() - reach * 1.08), QPointF(centre.x(), centre.y() + reach * 1.08)
        )

    @staticmethod
    def _at(centre: QPointF, extent: float, z: complex) -> QPointF:
        return QPointF(centre.x() + z.real * extent, centre.y() + z.imag * extent)

    def _paint_trail(
        self,
        painter: QPainter,
        centre: QPointF,
        extent: float,
        radii: np.ndarray,
        theta: float,
        turn: float,
        progress: float,
        c: theme.Colours,
    ) -> None:
        reveal = _ease((progress - 0.12) / 0.7)
        if reveal <= 0.0:
            return
        points = trail(
            radii, theta, turn, TRAIL_TURNS * reveal, max(8, round(TRAIL_POINTS * max(reveal, 0.1)))
        )
        polygon = [self._at(centre, extent, complex(p)) for p in points]
        palette = [
            theme.qcolor(c.accent),
            theme.qcolor(c.accent_2),
            theme.qcolor(c.morph),
            theme.qcolor(c.sound),
        ]
        count = len(polygon)
        step = 5
        for glow in (True, False):  # a wide faint pass under a thin bright one
            for start in range(0, count - 1, step):
                along = (start + step / 2) / count  # 0 the tail ... 1 the pen
                position = ((along * 1.3 + self.t * 0.07) % 1.0) * 4.0
                low = int(position) % 4
                mix = position - int(position)
                a, b = palette[low], palette[(low + 1) % 4]
                colour = QColor(
                    round(a.red() + (b.red() - a.red()) * mix),
                    round(a.green() + (b.green() - a.green()) * mix),
                    round(a.blue() + (b.blue() - a.blue()) * mix),
                )
                colour.setAlphaF(min(1.0, (along**1.5) * (0.2 if glow else 1.0)))
                width = (1.3 + 2.8 * along) * (3.4 if glow else 1.0)
                painter.setPen(
                    QPen(
                        colour,
                        width,
                        Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.FlatCap,
                        Qt.PenJoinStyle.RoundJoin,
                    )
                )
                painter.drawPolyline(QPolygonF(polygon[start : start + step + 1]))

    def _paint_machine(
        self,
        painter: QPainter,
        centre: QPointF,
        extent: float,
        radii: np.ndarray,
        theta: float,
        turn: float,
        progress: float,
        c: theme.Colours,
    ) -> None:
        joints = machine(radii, theta, turn)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for index, radius in enumerate(radii):
            show = _ease((progress - 0.08 - index * 0.09) / 0.22)
            if radius < 0.01 or show <= 0.0:
                continue
            origin = self._at(centre, extent, joints[index])
            tip = self._at(centre, extent, joints[index + 1])
            ring = QColor(theme.qcolor(c.text))
            ring.setAlphaF(0.13 * show)
            painter.setPen(QPen(ring, 1))
            painter.drawEllipse(origin, radius * extent * show, radius * extent * show)
            arm = QColor(theme.qcolor(c.text))
            arm.setAlphaF(0.34 * show)
            painter.setPen(QPen(arm, 1.1))
            painter.drawLine(
                origin,
                QPointF(
                    origin.x() + (tip.x() - origin.x()) * show, origin.y() + (tip.y() - origin.y()) * show
                ),
            )
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(arm)
            painter.drawEllipse(tip, 2.2 * show, 2.2 * show)
            painter.setBrush(Qt.BrushStyle.NoBrush)
        pen = self._at(centre, extent, joints[-1])
        glow = QRadialGradient(pen, 34)
        colour = QColor(theme.qcolor(c.accent_2))
        colour.setAlphaF(0.6 * _ease((progress - 0.1) / 0.3))
        glow.setColorAt(0.0, colour)
        colour.setAlphaF(0.0)
        glow.setColorAt(1.0, colour)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(pen, 34, 34)
        core = QColor(theme.qcolor(c.text))
        core.setAlphaF(_ease((progress - 0.1) / 0.3))
        painter.setBrush(core)
        painter.drawEllipse(pen, 4.4, 4.4)

    def _paint_identity(self, painter: QPainter, area: QRectF, progress: float, c: theme.Colours) -> None:
        """The line under the figure: e^(i pi) + 1 = 0, glowing very slightly."""
        fade = _ease((progress - 0.82) / 0.18)
        if fade <= 0.0:
            return
        scale = min(area.width() / 640, area.height() / 520)
        font = theme.font("title", kind="serif")
        font.setItalic(True)
        font.setPixelSize(max(12, round(23 * scale + 4)))
        small = QFont(font)
        small.setPixelSize(max(8, round(font.pixelSize() * 0.6)))
        big, tiny = QFontMetricsF(font), QFontMetricsF(small)
        parts = (("e", font), ("iπ", small), (" + 1 = 0", font))
        total = sum((tiny if f is small else big).horizontalAdvance(text) for text, f in parts)
        x = area.center().x() - total / 2
        y = area.bottom() - 10
        colour = QColor(theme.qcolor(c.text))
        colour.setAlphaF(fade * (0.78 + 0.22 * math.sin(self.t * 1.2)))
        painter.setPen(colour)
        for text, f in parts:
            painter.setFont(f)
            lift = big.height() * 0.32 if f is small else 0.0
            painter.drawText(QPointF(x, y - lift), text)
            x += (tiny if f is small else big).horizontalAdvance(text)
