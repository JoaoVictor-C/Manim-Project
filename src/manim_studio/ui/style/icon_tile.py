"""A rounded square with an icon in it (Lumen, ADR 0063): the chip in a dialog's header, the tile of a
destination, the badge of a mix lane.

Painted by hand from the theme's tokens when it is shown, so a theme switch needs nothing from the owner:
a ``tone`` gives a soft tinted square with the icon in the tone's colour; a ``gradient`` of two token names
gives a solid diagonal fill with a white icon.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPaintEvent
from PySide6.QtWidgets import QSizePolicy, QWidget

from . import icons, theme

# tone -> the token the icon is drawn in (and the square is tinted with)
TONES = {
    "accent": "accent_text",
    "neutral": "muted",
    "ok": "success",
    "warn": "warning",
    "bad": "danger",
}
SOFT_ALPHA = 38  # 15 %: the tinted square behind a tone's icon


class IconTile(QWidget):
    """``IconTile("warning", tone="warn")``, or ``IconTile("film", gradient=("danger", "warning"))``."""

    def __init__(
        self,
        icon: str,
        *,
        tone: str = "accent",
        gradient: tuple[str, str] | None = None,
        size: int = 34,
        radius: int = 11,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._icon, self._tone, self._gradient = icon, tone, gradient
        self._radius = radius
        self.setFixedSize(size, size)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def sizeHint(self) -> QSize:
        return self.size()

    def set_icon(self, icon: str) -> None:
        self._icon = icon
        self.update()

    def icon_name(self) -> str:
        return self._icon

    def set_tone(self, tone: str) -> None:
        self._tone, self._gradient = tone, None
        self.update()

    def set_gradient(self, gradient: tuple[str, str] | None) -> None:
        self._gradient = gradient
        self.update()

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        paint_tile(painter, QRectF(self.rect()), self._icon, self._tone, self._gradient, self._radius)
        painter.end()


def paint_tile(
    painter: QPainter,
    rect: QRectF,
    icon: str,
    tone: str = "accent",
    gradient: tuple[str, str] | None = None,
    radius: float = 11,
) -> None:
    """Paint the tile into ``rect`` (for views that draw by hand, like the mix lanes)."""
    colours = theme.THEME
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    if gradient is not None:
        fill = QLinearGradient(rect.topLeft(), rect.bottomRight())
        fill.setColorAt(0.0, theme.qcolor(getattr(colours, gradient[0])))
        fill.setColorAt(1.0, theme.qcolor(getattr(colours, gradient[1])))
        painter.setBrush(fill)
        tint = "on_accent"
    else:
        token = TONES.get(tone, "muted")
        soft = QColor(theme.qcolor(getattr(colours, token)))
        soft.setAlpha(SOFT_ALPHA)
        painter.setBrush(soft)
        tint = token
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(rect, radius, radius)
    glyph = round(rect.width() * 0.56)
    target = QRectF(0, 0, glyph, glyph)
    target.moveCenter(rect.center())
    icons.icon(icon, tint).paint(painter, target.toRect())
    painter.restore()
