"""The welcome (P6d.1, ADR 0044; Lumen, ADR 0063): what the viewer shows until a project is open.

A hero - a serif title ("Make mathematics move." with the second line in the accent gradient), a line of
text, **New project** and **Open** with their shortcuts - the ways to start (a blank scene, the example, and
any templates the window offers), the recent projects as cards with a thumbnail painted from the name, and a
large drawn curve behind it all: the logo's idea at big size. Pure view: the window connects the signals and
keeps the recent list current.

Everything is painted from the theme's tokens when it is shown, so a theme switch needs nothing from here.
The content sits in a scroll area, so a small window scrolls instead of squeezing the hero.
"""

from __future__ import annotations

import math
import time
import zlib
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetricsF,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QRadialGradient,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ... import __version__
from ..style import icons, theme
from ..style.card import Chip

# examples/ sits beside src/ in a checkout; an installed copy has no example to offer.
EXAMPLE = Path(__file__).resolve().parents[4] / "examples" / "showcase.json"

TITLE_LINES = ("Make mathematics", "move.")
SUBTITLE = (
    "A visual studio for Manim. Compose a scene, shape its motion on a timeline, "
    "write code when you want it, and render a film."
)
COLUMNS = 5  # recent project cards per row
MOTIFS = 6  # the drawings a thumbnail can show
BLANK_MOTIF, EXAMPLE_MOTIF = 4, 1


def _rules(c: theme.Colours) -> str:
    return f"""
QWidget#welcome {{ background: transparent; }}
QWidget#welcomeContent {{ background: transparent; }}
QLabel[role="lead"] {{ color: {c.muted}; font-size: 16px; }}
QLabel[role="eyebrow"] {{ color: {c.faint}; font-size: 11px; font-weight: 650; }}
QPushButton[hero="true"] {{ min-height: 44px; padding: 0 22px; border-radius: 11px; }}
QPushButton[hero="true"] QLabel {{
    background: transparent; font-size: 14px; font-weight: 600; color: {c.text};
}}
QPushButton[hero="true"][role="primary"] QLabel {{ color: {c.on_accent}; }}
QPushButton[hero="true"] QLabel[kbd="true"] {{
    font-family: "JetBrains Mono"; font-size: 10px; font-weight: 500; color: {c.muted};
    background: {c.raised}; border: 1px solid {theme.css(c.line_strong)}; border-radius: 5px;
    padding: 1px 5px;
}}
QPushButton[hero="true"][role="primary"] QLabel[kbd="true"] {{
    color: {c.on_accent}; background: rgba(255, 255, 255, 46); border-color: transparent;
}}
"""


theme.register_rules(_rules)


# -- painting helpers ---------------------------------------------------------------------------


def _alpha(token: str, alpha: float) -> QColor:
    colour = QColor(theme.qcolor(token))
    colour.setAlphaF(max(0.0, min(1.0, alpha)))
    return colour


def paint_thumbnail(painter: QPainter, rect: QRectF, seed: str | int, radius: float = 10.0) -> None:
    """A small scene-like picture: a dark tinted ground and one drawing chosen by ``seed`` (a name or an
    index), so each project looks like itself without a rendered image."""
    c = theme.THEME
    index = seed if isinstance(seed, int) else zlib.crc32(seed.encode("utf-8"))
    motif = index % MOTIFS
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    clip = QPainterPath()
    clip.addRoundedRect(rect, radius, radius)
    painter.setClipPath(clip)
    ground = QRadialGradient(
        QPointF(rect.center().x(), rect.top() + rect.height() * 0.4), rect.width() * 0.75
    )
    ground.setColorAt(0.0, theme.qcolor(theme.mix(c.badge, c.accent, 0.3)))
    ground.setColorAt(1.0, theme.qcolor(c.badge))
    painter.fillRect(rect, ground)
    cx, cy = rect.center().x(), rect.center().y()
    w, h = min(rect.width() * 0.62, rect.height() * 2.0), rect.height() * 0.62
    left, top = cx - w / 2, cy - h / 2

    def point(x: float, y: float) -> QPointF:  # 0..1 inside the drawing's box
        return QPointF(left + x * w, top + y * h)

    stroke = max(1.6, rect.height() / 44)
    if motif == 0:  # a sine
        path = QPainterPath(point(0, 0.5))
        path.cubicTo(point(0.12, 0.5), point(0.16, 0.0), point(0.33, 0.0))
        path.cubicTo(point(0.5, 0.0), point(0.5, 1.0), point(0.67, 1.0))
        path.cubicTo(point(0.84, 1.0), point(0.88, 0.5), point(1, 0.5))
        painter.setPen(QPen(theme.qcolor(c.morph), stroke, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
    elif motif == 1:  # axes and a curve
        painter.setPen(QPen(_alpha(c.accent_2, 0.45), 1))
        painter.drawLine(point(0, 0.5), point(1, 0.5))
        painter.drawLine(point(0.5, 0), point(0.5, 1))
        path = QPainterPath(point(0, 0.9))
        path.cubicTo(point(0.22, 0.9), point(0.28, 0.1), point(0.5, 0.1))
        path.cubicTo(point(0.72, 0.1), point(0.78, 0.9), point(1, 0.9))
        painter.setPen(QPen(theme.qcolor(c.morph), stroke, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
    elif motif == 2:  # a triangle
        path = QPainterPath(point(0.16, 0.92))
        path.lineTo(point(0.16, 0.08))
        path.lineTo(point(0.84, 0.92))
        path.closeSubpath()
        painter.setPen(QPen(theme.qcolor(c.success), stroke, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
    elif motif == 3:  # a circle and a dot on it
        r = min(w, h) * 0.5
        painter.setPen(QPen(_alpha(c.accent, 0.7), stroke))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(cx, cy), r, r)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme.qcolor(c.key))
        painter.drawEllipse(QPointF(cx + r, cy), r * 0.14, r * 0.14)
    elif motif == 4:  # a serif "Aa", the title
        font = theme.font("title", kind="serif")
        font.setItalic(True)
        font.setPixelSize(max(10, round(rect.height() * 0.38)))
        painter.setFont(font)
        painter.setPen(theme.qcolor(c.badge_text))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "Aa")
    else:  # a spiral of dots
        painter.setPen(Qt.PenStyle.NoPen)
        r0 = min(w, h) * 0.5
        for step in range(14):
            angle = step * 0.75
            radius_step = r0 * (0.12 + 0.88 * step / 13)
            painter.setBrush(_alpha(c.sound if step % 3 else c.key, 0.9))
            dot = max(1.4, rect.height() * 0.028 + step * 0.12)
            painter.drawEllipse(
                QPointF(cx + radius_step * 0.9 * math.cos(angle), cy + radius_step * 0.9 * math.sin(angle)),
                dot,
                dot,
            )
    painter.restore()


def edited_text(path: Path, now: float | None = None) -> str:
    """ "Edited today", "yesterday", "3 days ago"... from the file's modification time ("" if it is gone)."""
    try:
        modified = path.stat().st_mtime
    except OSError:
        return ""
    days = int((time.time() if now is None else now) // 86400 - modified // 86400)
    if days <= 0:
        return "Edited today"
    if days == 1:
        return "Edited yesterday"
    if days < 7:
        return f"Edited {days} days ago"
    if days < 14:
        return "Edited last week"
    if days < 60:
        return f"Edited {days // 7} weeks ago"
    return "Edited " + time.strftime("%d %b %Y", time.localtime(modified))


# -- widgets --------------------------------------------------------------------------------------


class HeroTitle(QWidget):
    """The two-line serif title; the second line is filled with the accent gradient, painted by hand."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pixels = 76
        self.setAccessibleName(" ".join(TITLE_LINES))
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self._resize_for(self._pixels)

    def _font(self, italic: bool = False) -> QFont:
        font = theme.font("display", kind="serif")
        font.setPixelSize(self._pixels)
        font.setItalic(italic)
        font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 98)
        return font

    def fit(self, width: int) -> int:
        """Choose the largest size (up to 76 px) at which the first line fits ``width``; returns it."""
        probe = self._font()
        probe.setPixelSize(100)
        per_pixel = QFontMetricsF(probe).horizontalAdvance(TITLE_LINES[0]) / 100
        self._pixels = max(34, min(76, int(width / max(per_pixel, 0.01) * 0.98)))
        self._resize_for(self._pixels)
        self.update()
        return self._pixels

    def _resize_for(self, pixels: int) -> None:
        self.setFixedHeight(round(pixels * 2.0))

    def sizeHint(self) -> QSize:
        metrics = QFontMetricsF(self._font())
        return QSize(round(metrics.horizontalAdvance(TITLE_LINES[0])) + 4, round(self._pixels * 2.0))

    def paintEvent(self, _event: QPaintEvent) -> None:
        c = theme.THEME
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = self._font()
        metrics = QFontMetricsF(font)
        line = self._pixels * 1.02
        painter.setFont(font)
        painter.setPen(theme.qcolor(c.text))
        painter.drawText(QPointF(0, metrics.ascent() + 2), TITLE_LINES[0])
        italic = self._font(True)
        second = QFontMetricsF(italic)
        path = QPainterPath()
        path.addText(QPointF(0, line + metrics.ascent() + 2), italic, TITLE_LINES[1])
        gradient = QLinearGradient(0, 0, second.horizontalAdvance(TITLE_LINES[1]), 0)
        gradient.setColorAt(0.0, theme.qcolor(c.accent))
        gradient.setColorAt(1.0, theme.qcolor(c.accent_2))
        painter.fillPath(path, QBrush(gradient))
        painter.end()


class HeroButton(QPushButton):
    """A large button with an icon, a label and its shortcut as a small keycap. The labels are children, so
    the stylesheet colours them (``role`` primary: white on the accent)."""

    def __init__(self, icon: str, text: str, hint: str = "", role: str | None = None) -> None:
        super().__init__()
        self.setProperty("hero", True)
        if role:
            self.setProperty("role", role)
        self.setAccessibleName(text)
        self._icon_name = icon
        self._on_accent = role == "primary"
        row = QHBoxLayout(self)
        row.setContentsMargins(22, 0, 22, 0)
        row.setSpacing(10)
        self.glyph = QLabel()
        self.glyph.setFixedSize(18, 18)
        self.label = QLabel(text)
        row.addWidget(self.glyph, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.label, 0, Qt.AlignmentFlag.AlignVCenter)
        self.hint = QLabel(hint)
        self.hint.setProperty("kbd", True)
        self.hint.setVisible(bool(hint))
        row.addWidget(self.hint, 0, Qt.AlignmentFlag.AlignVCenter)
        for child in (self.glyph, self.label, self.hint):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._refresh_icon()
        theme.signals.themeChanged.connect(self._refresh_icon)

    def _refresh_icon(self, *_args) -> None:
        tint = "on_accent" if self._on_accent else "text"
        self.glyph.setPixmap(icons.icon(self._icon_name, tint).pixmap(18, 18))

    def sizeHint(self) -> QSize:
        hint = self.layout().sizeHint()
        return QSize(hint.width(), max(hint.height(), 44))

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()


class _Card(QPushButton):
    """A card button painted by hand: a thumbnail over a name and a line of detail."""

    PADDING = 10
    RADIUS = 16.0

    def __init__(self, name: str, detail: str, seed: str | int, thumb_height: int) -> None:
        super().__init__(name)
        self.detail, self.seed, self.thumb_height = detail, seed, thumb_height
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFlat(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(self.PADDING * 2 + thumb_height + 46)

    def sizeHint(self) -> QSize:
        return QSize(130, self.height())

    def minimumSizeHint(self) -> QSize:
        return QSize(96, self.height())

    def paintEvent(self, _event: QPaintEvent) -> None:
        c = theme.THEME
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        hovered = self.underMouse() or self.hasFocus()
        painter.setBrush(theme.qcolor(c.panel))
        edge = c.accent_line if self.hasFocus() else (c.line_strong if hovered else c.line)
        painter.setPen(QPen(theme.qcolor(edge), 1))
        painter.drawRoundedRect(rect, self.RADIUS, self.RADIUS)
        pad = self.PADDING
        thumb = QRectF(rect.left() + pad, rect.top() + pad, rect.width() - 2 * pad, self.thumb_height)
        paint_thumbnail(painter, thumb, self.seed, 10.0)
        name_font = theme.font("label")
        name_font.setWeight(QFont.Weight.DemiBold)
        name_font.setPixelSize(13)
        painter.setFont(name_font)
        painter.setPen(theme.qcolor(c.text))
        text_width = round(rect.width() - 2 * pad - 4)
        text_left = round(rect.left() + pad + 2)
        base = round(thumb.bottom() + 8)
        painter.drawText(
            QRectF(text_left, base, text_width, 18),
            Qt.AlignmentFlag.AlignVCenter,
            painter.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, text_width),
        )
        small = theme.font("caption")
        painter.setFont(small)
        painter.setPen(theme.qcolor(c.faint))
        painter.drawText(
            QRectF(text_left, base + 18, text_width, 16),
            Qt.AlignmentFlag.AlignVCenter,
            painter.fontMetrics().elidedText(self.detail, Qt.TextElideMode.ElideRight, text_width),
        )
        painter.end()


class StarterCard(_Card):
    """A way to start: a blank scene, the example, a template."""

    PADDING = 12
    RADIUS = 14.0

    def __init__(self, name: str, detail: str, seed: str | int) -> None:
        super().__init__(name, detail, seed, thumb_height=62)


class RecentCard(_Card):
    """A recent project: its name is the button's text, its path the tooltip."""

    def __init__(self, path: Path) -> None:
        super().__init__(
            path.name, "  ·  ".join(filter(None, (edited_text(path), path.parent.name))), path.stem, 96
        )
        self.path = path
        self.setToolTip(str(path))


class BrowseCard(QPushButton):
    """The dashed card at the end of the recent row: Open..."""

    def __init__(self) -> None:
        super().__init__("Browse...")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFlat(True)
        self.setToolTip("Open a project file (Ctrl+O)")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(RecentCard.PADDING * 2 + 96 + 46)

    def sizeHint(self) -> QSize:
        return QSize(130, self.height())

    def minimumSizeHint(self) -> QSize:
        return QSize(96, self.height())

    def paintEvent(self, _event: QPaintEvent) -> None:
        c = theme.THEME
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        hovered = self.underMouse() or self.hasFocus()
        painter.setBrush(theme.qcolor(c.field))
        pen = QPen(theme.qcolor(c.accent_line if hovered else c.line_strong), 1, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawRoundedRect(rect, 16, 16)
        glyph = icons.icon("open", "muted").pixmap(24, 24)
        painter.drawPixmap(round(rect.center().x() - 12), round(rect.center().y() - 22), glyph)
        painter.setFont(theme.font("label"))
        painter.setPen(theme.qcolor(c.muted))
        painter.drawText(
            QRectF(rect.left(), rect.center().y() + 8, rect.width(), 20),
            Qt.AlignmentFlag.AlignCenter,
            "Browse...",
        )
        painter.end()


class WelcomePanel(QWidget):
    newRequested = Signal()
    openRequested = Signal()
    exampleRequested = Signal()
    recentRequested = Signal(Path)
    templateRequested = Signal(str)  # a template offered with ``set_templates`` was chosen (its key)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("welcome")
        self.recent_links: list[QPushButton] = []
        self.template_cards: list[StarterCard] = []
        self._column_width = 560
        self._margin = 80
        self._starter_columns = 4
        self._recent_columns = COLUMNS

        self.new_button = self._hero("add", "New project", "Ctrl N", "primary", self.newRequested)
        self.new_button.setToolTip("An empty scene (Ctrl+N)")
        self.open_button = self._hero("open", "Open", "Ctrl O", None, self.openRequested)
        self.open_button.setToolTip("Open a project file (Ctrl+O)")
        self.example_button = QPushButton(icons.icon("example"), "Open Example")
        self.example_button.setProperty("role", "ghost")
        self.example_button.setToolTip("The showcase scene, as a copy you can change freely")
        self.example_button.clicked.connect(lambda: self.exampleRequested.emit())
        self.example_button.setVisible(EXAMPLE.is_file())

        self.version_chip = Chip(f"Version {_short_version()}", "accent")
        self.version_chip.setVisible(not __version__.startswith("0+"))
        self.title = HeroTitle()
        self.subtitle = QLabel(SUBTITLE)
        self.subtitle.setProperty("role", "lead")
        self.subtitle.setWordWrap(True)
        self.subtitle.setMaximumWidth(480)

        self.buttons = QGridLayout()  # New and Open; Example beside them, or below when the column is narrow
        self.buttons.setHorizontalSpacing(12)
        self.buttons.setVerticalSpacing(8)
        self.buttons.addWidget(self.new_button, 0, 0)
        self.buttons.addWidget(self.open_button, 0, 1)
        self.buttons.addWidget(self.example_button, 0, 2)
        self.buttons.setColumnStretch(3, 1)

        self.starters_heading = self._eyebrow("START HERE")
        self.starters = QGridLayout()
        self.starters.setSpacing(10)
        self._blank = StarterCard("Blank scene", "An empty project", BLANK_MOTIF)
        self._blank.setToolTip("An empty scene (Ctrl+N)")
        self._blank.clicked.connect(lambda: self.newRequested.emit())
        self._example = StarterCard("Showcase", "The example scene", EXAMPLE_MOTIF)
        self._example.setToolTip("The showcase scene, as a copy you can change freely")
        self._example.clicked.connect(lambda: self.exampleRequested.emit())
        self._example.setVisible(EXAMPLE.is_file())
        self._place_starters()

        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(0)
        left.addWidget(self.version_chip, 0, Qt.AlignmentFlag.AlignLeft)
        left.addSpacing(18)
        left.addWidget(self.title)
        left.addSpacing(16)
        left.addWidget(self.subtitle)
        left.addSpacing(28)
        left.addLayout(self.buttons)
        left.addSpacing(36)
        left.addWidget(self.starters_heading)
        left.addSpacing(12)
        left.addLayout(self.starters)
        self.left_column = QWidget()
        self.left_column.setLayout(left)
        self.left_column.setFixedWidth(self._column_width)

        hero = QHBoxLayout()
        hero.setContentsMargins(0, 0, 0, 0)
        hero.addWidget(self.left_column, 0, Qt.AlignmentFlag.AlignTop)
        hero.addStretch(1)

        self.recent_heading = self._eyebrow("RECENT")
        self.recent_grid = QGridLayout()
        self.recent_grid.setSpacing(14)
        self.browse_card = BrowseCard()
        self.browse_card.clicked.connect(lambda: self.openRequested.emit())

        self.content = QWidget()
        self.content.setObjectName("welcomeContent")
        column = QVBoxLayout(self.content)
        column.setContentsMargins(self._margin, 36, self._margin, 26)
        column.setSpacing(0)
        column.addLayout(hero)
        column.addSpacing(24)
        column.addStretch(1)
        column.addWidget(self.recent_heading)
        column.addSpacing(12)
        column.addLayout(self.recent_grid)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setWidget(self.content)
        self.scroll.viewport().setAutoFillBackground(False)
        self.content.setAutoFillBackground(False)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.scroll)
        self.set_recent([])

    # -- building ---------------------------------------------------------------------------------

    def _hero(self, icon: str, text: str, hint: str, role: str | None, signal) -> HeroButton:
        button = HeroButton(icon, text, hint, role)
        button.clicked.connect(lambda: signal.emit())
        return button

    def _eyebrow(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setProperty("role", "eyebrow")
        font = theme.font("section")
        font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 112)
        label.setFont(font)
        return label

    def _place_starters(self, columns: int = 4) -> None:
        cards = [self._blank, self._example, *self.template_cards]
        while self.starters.count():
            self.starters.takeAt(0)
        for index, card in enumerate(cards):
            self.starters.addWidget(card, index // columns, index % columns)
        for column in range(4):
            self.starters.setColumnStretch(column, 1 if column < columns else 0)
        self._starter_columns = columns

    def _regrid(self, width: int) -> None:
        """As many cards per row as the width allows (the starters up to 4, the recent ones up to 5)."""
        starters = max(2, min(4, self._column_width // 128))
        recent = max(2, min(COLUMNS, (width - 2 * self._margin + 14) // 124))
        if starters != self._starter_columns:
            self._place_starters(starters)
        if recent != self._recent_columns:
            self._place_recent(recent)

    def set_templates(self, templates: list[tuple[str, str, str]]) -> None:
        """Offer templates as starting points: ``(key, name, description)``; choosing one emits
        ``templateRequested(key)``. The blank scene and the example stay first."""
        for card in self.template_cards:
            card.setParent(None)
            card.deleteLater()
        self.template_cards = []
        for key, name, description in templates:
            card = StarterCard(name, description, name)
            card.setToolTip(description)
            card.clicked.connect(lambda _=False, k=key: self.templateRequested.emit(k))
            self.template_cards.append(card)
        self._place_starters(self._starter_columns)

    def set_recent(self, paths: list[Path]) -> None:
        """Show these files as cards, newest first (none: the section is hidden)."""
        for link in self.recent_links:
            self.recent_grid.removeWidget(link)
            link.setParent(None)  # gone at once; deleted when control returns to the event loop
            link.deleteLater()
        self.recent_grid.removeWidget(self.browse_card)
        self.recent_links = []
        for path in paths:
            self.recent_links.append(RecentCard(path))
            self.recent_links[-1].clicked.connect(lambda _=False, p=path: self.recentRequested.emit(p))
        self._place_recent(self._recent_columns)
        self.recent_heading.setVisible(bool(paths))
        self.browse_card.setVisible(bool(paths))

    def _place_recent(self, columns: int) -> None:
        cards: list[QPushButton] = [*self.recent_links, self.browse_card]
        for card in cards:
            self.recent_grid.removeWidget(card)
        for index, card in enumerate(cards):
            self.recent_grid.addWidget(card, index // columns, index % columns)
        for column in range(COLUMNS):
            self.recent_grid.setColumnStretch(column, 1 if column < columns else 0)
        self._recent_columns = columns

    # -- layout and painting ----------------------------------------------------------------------

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        width = self.width()
        self._margin = max(28, min(80, round(width * 0.055)))
        self.content.layout().setContentsMargins(
            self._margin, 36 if self.height() > 560 else 20, self._margin, 26
        )
        self._column_width = max(280, min(560, max(round(width * 0.42), 520), width - 2 * self._margin))
        wrapped = self._column_width < 560
        self.buttons.removeWidget(self.example_button)
        self.buttons.addWidget(
            self.example_button, 1 if wrapped else 0, 0 if wrapped else 2, Qt.AlignmentFlag.AlignLeft
        )
        for button in (self.new_button, self.open_button):
            button.hint.setVisible(self._column_width >= 440)
        self._regrid(width)
        self.left_column.setFixedWidth(self._column_width)
        self.title.fit(self._column_width)

    def _illustration_rect(self) -> QRectF | None:
        left = self._margin + self._column_width + 40
        room = self.width() - left - 40
        if room < 220:
            return None
        height = min(self.height() * 0.62, room * 0.82)
        return QRectF(left, 16, room, height)

    def paintEvent(self, _event: QPaintEvent) -> None:
        c = theme.THEME
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), theme.qcolor(c.window))
        strength = 1.0 if c.dark else 0.55
        top = QRadialGradient(
            QPointF(self.width() * 0.78, self.height() * 0.08), max(self.width(), 400) * 0.62
        )
        top.setColorAt(0.0, _alpha(c.accent, 0.22 * strength))
        top.setColorAt(1.0, _alpha(c.accent, 0.0))
        painter.fillRect(self.rect(), top)
        bottom = QRadialGradient(
            QPointF(self.width() * 0.05, self.height() * 1.05), max(self.width(), 400) * 0.5
        )
        bottom.setColorAt(0.0, _alpha(c.accent_2, 0.12 * strength))
        bottom.setColorAt(1.0, _alpha(c.accent_2, 0.0))
        painter.fillRect(self.rect(), bottom)
        area = self._illustration_rect()
        if area is not None:
            paint_curves(painter, area)
        painter.end()


def paint_curves(painter: QPainter, area: QRectF) -> None:
    """The large drawing at the right of the welcome: two gradient curves over faint circles and axes, a dot
    where one of them turns, and the identity next to it."""
    c = theme.THEME
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    scale = min(area.width() / 640, area.height() / 520)
    painter.translate(
        area.left() + (area.width() - 640 * scale) / 2, area.top() + (area.height() - 520 * scale) / 2
    )
    painter.scale(scale, scale)
    painter.setPen(QPen(_alpha(c.text, 0.07), 1))
    painter.drawLine(QPointF(0, 260), QPointF(640, 260))
    painter.drawLine(QPointF(320, 0), QPointF(320, 520))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(_alpha(c.text, 0.08), 1))
    painter.drawEllipse(QPointF(320, 260), 170, 170)
    painter.setPen(QPen(_alpha(c.text, 0.06), 1))
    painter.drawEllipse(QPointF(320, 260), 120, 120)

    first = QPainterPath(QPointF(10, 260))
    first.cubicTo(QPointF(90, 260), QPointF(110, 60), QPointF(200, 60))
    first.cubicTo(QPointF(290, 60), QPointF(300, 460), QPointF(400, 460))
    first.cubicTo(QPointF(500, 460), QPointF(530, 60), QPointF(630, 60))
    grad_a = QLinearGradient(10, 0, 630, 0)
    grad_a.setColorAt(0.0, theme.qcolor(c.accent))
    grad_a.setColorAt(1.0, theme.qcolor(c.accent_2))
    painter.setPen(QPen(QBrush(grad_a), 3.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.drawPath(first)

    second = QPainterPath(QPointF(10, 330))
    second.cubicTo(QPointF(110, 330), QPointF(140, 130), QPointF(240, 130))
    second.cubicTo(QPointF(340, 130), QPointF(330, 400), QPointF(430, 400))
    second.cubicTo(QPointF(530, 400), QPointF(540, 190), QPointF(630, 190))
    grad_b = QLinearGradient(10, 0, 630, 0)
    grad_b.setColorAt(0.0, theme.qcolor(c.morph))
    grad_b.setColorAt(1.0, theme.qcolor(c.sound))
    painter.setOpacity(0.8)
    painter.setPen(QPen(QBrush(grad_b), 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.drawPath(second)
    painter.setOpacity(1.0)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(theme.qcolor(c.text))
    painter.drawEllipse(QPointF(400, 460), 7, 7)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(_alpha(c.text, 0.3), 1))
    painter.drawEllipse(QPointF(400, 460), 16, 16)

    font = theme.font("title", kind="serif")
    font.setItalic(True)
    font.setPixelSize(26)
    painter.setFont(font)
    painter.setPen(theme.qcolor(c.text))
    painter.drawText(QPointF(420, 448), "e")
    small = QFont(font)
    small.setPixelSize(15)
    painter.setFont(small)
    painter.drawText(QPointF(433, 436), "iπ")
    painter.setFont(font)
    painter.drawText(QPointF(452, 448), "+ 1 = 0")
    painter.restore()


def _short_version() -> str:
    parts = __version__.split(".")
    return ".".join(parts[:2])
