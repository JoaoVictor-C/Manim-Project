"""The small painted pieces of the Code page in Lumen (P17.4d, ADR 0063).

Everything here paints from ``theme.THEME`` at the moment it paints, so a theme switch needs nothing from
it: the explorer's kind chips and state chips (``paint_kind``, ``paint_chip``), the file tabs over the
editor (``CodeTabs``: rounded top tabs, a dot for unapplied text, the close button on hover), a chip with a
switch in it (``ToggleChip``, Live), the Run button with its shortcut (``RunButton``) and the thin accent line
under the toolbar while a run works (``ProgressLine``, animated through ``motion``). ``svg_url`` draws the few
stylesheet images the page needs in a theme's colours. ``rules`` is the page's part of the stylesheet.
"""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

from PySide6.QtCore import Property, QEvent, QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPaintEvent, QPen
from PySide6.QtWidgets import QAbstractButton, QPushButton, QTabBar, QWidget

from ..style import motion, theme
from ..style.render_activity import FRAMES

RUN_HINT = "Ctrl ↵"
CHIP_HEIGHT = 22
KIND_SIZE = 22


# -- stylesheet images -----------------------------------------------------------------------------

_SHAPES = {
    "close": '<path d="M4.5 4.5l7 7M11.5 4.5l-7 7" fill="none" stroke="{c}" stroke-width="1.6" '
    'stroke-linecap="round"/>',
    "caret": '<path d="M4.5 6.5l3.5 3.5 3.5-3.5" fill="none" stroke="{c}" stroke-width="1.7" '
    'stroke-linecap="round" stroke-linejoin="round"/>',
}


def svg_url(shape: str, token: str) -> str:
    """A stylesheet ``url(...)`` of a small glyph (``close``, ``caret``) drawn in the colour ``token``."""
    colour = token[:7]
    text = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">'
        + _SHAPES[shape].format(c=colour)
        + "</svg>"
    )
    key = hashlib.sha1(text.encode()).hexdigest()[:10]
    folder = Path(tempfile.gettempdir()) / "manim-studio-code-ui"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{shape}-{key}.svg"
    if not target.is_file():
        target.write_text(text, encoding="utf-8")
    return "url(" + str(target).replace(chr(92), "/") + ")"


# -- chips and kinds ---------------------------------------------------------------------------------

TONES = {"neutral": "muted", "accent": "accent_text", "ok": "success", "warn": "warning", "bad": "error_text"}


def chip_font() -> QFont:
    f = theme.font("caption")
    f.setPixelSize(10)
    return f


def paint_chip(painter: QPainter, rect: QRectF, text: str, tone: str = "neutral") -> None:
    """A pill like ``Chip``: the raised colour, a hairline, the text in the tone's colour."""
    colours = theme.THEME
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    if tone == "accent":
        fill, edge = colours.accent_soft, colours.accent_line
    else:
        fill, edge = colours.raised, colours.line_strong
    painter.setPen(QPen(theme.qcolor(edge), 1))
    painter.setBrush(theme.qcolor(fill))
    radius = rect.height() / 2
    painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
    painter.setPen(theme.qcolor(getattr(colours, TONES.get(tone, "muted"))))
    painter.setFont(chip_font())
    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
    painter.restore()


def kind_colours(kind: str) -> tuple[str, str] | None:
    """The two ends of a kind's gradient (None: a preset, drawn plain)."""
    c = theme.THEME
    return {
        "scene": (c.key, c.warning),  # amber to orange
        "object": (c.content, c.accent),  # blue to violet
        "helper": (c.success, c.accent_2),  # green to teal
    }.get(kind)


KIND_ICONS = {
    "scene": "kind-scene",
    "object": "kind-object",
    "helper": "kind-helper",
    "preset": "kind-preset",
}


def paint_kind(painter: QPainter, rect: QRectF, kind: str) -> None:
    """The rounded icon chip of a row: a gradient per kind, a plain chip for a preset."""
    from ..style import icons

    colours = theme.THEME
    ends = kind_colours(kind)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    if ends is None:
        painter.setBrush(theme.qcolor(colours.surface_3))
        tint = "muted"
    else:
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0.0, theme.qcolor(ends[0]))
        gradient.setColorAt(1.0, theme.qcolor(ends[1]))
        painter.setBrush(gradient)
        tint = "on_accent"
    painter.drawRoundedRect(rect, theme.RADIUS_SMALL, theme.RADIUS_SMALL)
    glyph = icons.icon(KIND_ICONS.get(kind, "kind-preset"), tint=tint)
    side = 14
    target = QRect(round(rect.center().x() - side / 2), round(rect.center().y() - side / 2), side, side)
    glyph.paint(painter, target)
    painter.restore()


# -- the tabs over the editor ----------------------------------------------------------------------------


class CodeTabs(QTabBar):
    """File tabs with rounded tops: the current one sits on the editor's colour under an accent line.

    The text of a tab keeps the marks the page puts in it (``"  ●"`` for unapplied text, a spinner while it
    runs), so the page and its tests read it as before; the painting turns the dot into a warning-coloured
    dot and the spinner into an accent glyph, and shows the close button only on the current and the
    hovered tab."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setDrawBase(False)
        self._hover = -1
        self.currentChanged.connect(lambda _i: self._sync_close())

    @staticmethod
    def parts(text: str) -> tuple[str, bool, str]:
        """(name, dirty, spinner glyph) of a tab's text."""
        words = text.split("  ")
        name = words[0]
        dirty = "●" in words[1:]
        spin = next((w for w in words[1:] if w and w[0] in FRAMES), "")
        return name, dirty, spin

    def tabSizeHint(self, index: int) -> QSize:
        size = super().tabSizeHint(index)
        return QSize(size.width(), 34)

    def minimumTabSizeHint(self, index: int) -> QSize:
        size = super().minimumTabSizeHint(index)
        return QSize(size.width(), 34)

    def paintEvent(self, event: QPaintEvent) -> None:
        colours = theme.THEME
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for index in range(self.count()):
            rect = QRectF(self.tabRect(index)).adjusted(1, 0, -1, 0)
            current = index == self.currentIndex()
            if current or index == self._hover:
                path = QPainterPath()
                r = theme.RADIUS_ROW
                path.moveTo(rect.bottomLeft())
                path.lineTo(rect.left(), rect.top() + r)
                path.quadTo(rect.topLeft(), QPointF(rect.left() + r, rect.top()))
                path.lineTo(rect.right() - r, rect.top())
                path.quadTo(rect.topRight(), QPointF(rect.right(), rect.top() + r))
                path.lineTo(rect.bottomRight())
                path.closeSubpath()
                painter.fillPath(path, theme.qcolor(colours.field if current else colours.hover))
                if current:
                    painter.save()
                    painter.setClipPath(path)
                    painter.fillRect(
                        QRectF(rect.left(), rect.top(), rect.width(), 2), theme.qcolor(colours.accent)
                    )
                    painter.restore()
            name, dirty, spin = self.parts(self.tabText(index))
            x = rect.left() + 12
            icon = self.tabIcon(index)
            if not icon.isNull():
                icon.paint(painter, QRect(round(x), round(rect.center().y() - 7), 14, 14))
                x += 14 + 8
            font = theme.font("label")
            painter.setFont(font)
            painter.setPen(theme.qcolor(colours.text if current else colours.muted))
            metrics = painter.fontMetrics()
            right = rect.right() - 10 - (18 if self.tabButton(index, QTabBar.ButtonPosition.RightSide) else 0)
            room = int(right - x - (12 if dirty else 0) - (14 if spin else 0))
            shown = metrics.elidedText(name, Qt.TextElideMode.ElideRight, max(room, 8))
            painter.drawText(QRectF(x, rect.top(), room, rect.height()), Qt.AlignmentFlag.AlignVCenter, shown)
            x += metrics.horizontalAdvance(shown) + 8
            if dirty:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(theme.qcolor(colours.warning))
                painter.drawEllipse(QPointF(x + 3.5, rect.center().y()), 3.5, 3.5)
                x += 12
            if spin:
                painter.setPen(theme.qcolor(colours.accent_text))
                painter.drawText(
                    QRectF(x, rect.top(), 14, rect.height()), Qt.AlignmentFlag.AlignVCenter, spin
                )
        painter.end()

    # -- the close button on hover -------------------------------------------------------------

    def _sync_close(self) -> None:
        for index in range(self.count()):
            button = self.tabButton(index, QTabBar.ButtonPosition.RightSide)
            if button is not None:
                button.setVisible(index in (self.currentIndex(), self._hover))

    def tabLayoutChange(self) -> None:
        super().tabLayoutChange()
        self._sync_close()

    def mouseMoveEvent(self, event) -> None:
        hover = self.tabAt(event.position().toPoint())
        if hover != self._hover:
            self._hover = hover
            self._sync_close()
            self.update()
        super().mouseMoveEvent(event)

    def event(self, event) -> bool:
        if event.type() == QEvent.Type.Leave and self._hover != -1:
            self._hover = -1
            self._sync_close()
            self.update()
        return super().event(event)


# -- a chip with a switch ----------------------------------------------------------------------------


class ToggleChip(QAbstractButton):
    """A checkable chip with a small switch before its text (the toolbar's Live)."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setText(text)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self._hover = False

    def sizeHint(self) -> QSize:
        width = self.fontMetrics().horizontalAdvance(self.text())
        return QSize(8 + 22 + 6 + width + 10, CHIP_HEIGHT)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def enterEvent(self, event) -> None:
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:
        colours = theme.THEME
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        on = self.isChecked()
        painter.setPen(QPen(theme.qcolor(colours.accent_line if on else colours.line_strong), 1))
        painter.setBrush(theme.qcolor(colours.accent_soft if on else colours.raised))
        painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        track = QRectF(8, (self.height() - 13) / 2, 22, 13)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme.qcolor(colours.accent if on else colours.surface_3))
        painter.drawRoundedRect(track, 6.5, 6.5)
        knob = 9
        kx = track.right() - knob - 2 if on else track.left() + 2
        painter.setBrush(theme.qcolor(colours.on_accent if on else colours.muted))
        painter.drawEllipse(QRectF(kx, track.top() + 2, knob, knob))
        painter.setPen(theme.qcolor(colours.text if on or self._hover else colours.muted))
        painter.setFont(self.font())
        painter.drawText(
            QRectF(track.right() + 6, 0, self.width() - track.right() - 6, self.height()),
            Qt.AlignmentFlag.AlignVCenter,
            self.text(),
        )
        if self.hasFocus():
            painter.setPen(QPen(theme.qcolor(colours.accent), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        painter.end()


# -- Run, with its shortcut -----------------------------------------------------------------------------


class RunButton(QPushButton):
    """The primary Run button; while it says just "Run" it shows its shortcut in a small key cap."""

    def __init__(self, *args) -> None:
        super().__init__(*args)
        self.setObjectName("codeRun")
        self.setProperty("role", "primary")
        self.setProperty("size", "sm")
        self.setProperty("hint", True)

    def setText(self, text: str) -> None:
        hint = text == "Run"
        if hint != self.property("hint"):
            self.setProperty("hint", hint)
            self.style().unpolish(self)
            self.style().polish(self)
        super().setText(text)

    def _hint_font(self) -> QFont:
        f = theme.font("caption", kind="mono")
        f.setPixelSize(10)
        return f

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        if not self.property("hint") or not self.isEnabled():
            return
        colours = theme.THEME
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(self._hint_font())
        width = painter.fontMetrics().horizontalAdvance(RUN_HINT) + 10
        cap = QRectF(self.width() - width - 8, (self.height() - 16) / 2, width, 16)
        fill = QColor(theme.qcolor(colours.on_accent))
        fill.setAlpha(46)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        painter.drawRoundedRect(cap, 5, 5)
        painter.setPen(theme.qcolor(colours.on_accent))
        painter.drawText(cap, Qt.AlignmentFlag.AlignCenter, RUN_HINT)
        painter.end()


# -- the line that says a run is working ---------------------------------------------------------------


class ProgressLine(QWidget):
    """A 3 px accent gradient under the toolbar while the code runs; it flows when motion is on."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(3)
        self._phase = 0.0
        self._animation = None

    def _get_phase(self) -> float:
        return self._phase

    def _set_phase(self, value: float) -> None:
        self._phase = float(value)
        self.update()

    phase = Property(float, _get_phase, _set_phase)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        animation = motion.animate(self, "phase", 1.0, 1200, start=0.0)
        if animation is not None:
            animation.setLoopCount(-1)
            self._animation = animation

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        if self._animation is not None:
            self._animation.stop()  # it deletes itself
            self._animation = None

    def paintEvent(self, event: QPaintEvent) -> None:
        colours = theme.THEME
        painter = QPainter(self)
        width = max(self.width(), 1)
        shift = self._phase * width
        gradient = QLinearGradient(-width + shift, 0, width + shift, 0)
        for stop, token in (
            (0.0, colours.accent),
            (0.25, colours.accent_2),
            (0.5, colours.accent),
            (0.75, colours.accent_2),
            (1.0, colours.accent),
        ):
            gradient.setColorAt(stop, theme.qcolor(token))
        painter.fillRect(self.rect(), gradient)
        painter.end()


# -- the page's stylesheet ---------------------------------------------------------------------------


def rules(c: theme.Colours) -> str:
    """The Code page's stylesheet rules, from the tokens (registered with ``theme.register_rules``)."""
    r = theme.RADIUS
    line = theme.css(c.line)
    inner = theme.RADIUS_CARD - 1  # the strips at the card's ends follow its corners inside the hairline
    accent_grad = (
        f"qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {theme.mix(c.accent, c.on_accent, 0.10)}, "
        f"stop:1 {c.accent})"
    )
    return f"""
#codePage QPushButton[size="sm"], QDialog[lumen="true"] QPushButton[size="sm"] {{
    padding: 3px 10px; border-radius: 8px; min-height: 18px;
}}
#codePage QPushButton[size="sm"][role="primary"] {{ padding: 4px 11px; }}
QPushButton#codeRun[hint="true"] {{ padding-right: 58px; }}
#codePage QPushButton::menu-indicator {{
    image: {svg_url("caret", c.on_accent)}; subcontrol-origin: padding; subcontrol-position: right center;
    width: 12px; height: 12px; right: 6px;
}}
#codePage QPushButton[size="sm"][menu="true"] {{ padding-right: 20px; padding-left: 9px; }}
#codePage QToolButton[icon="true"] {{ padding: 4px; border-radius: 7px; color: {c.muted}; }}
QFrame#codeBar, QFrame#codeTabStrip, QFrame#codeStatusStrip {{ background: {c.panel}; border: 0; }}
QFrame#codeTabStrip {{
    border-bottom: 1px solid {line}; border-top-left-radius: {inner}px; border-top-right-radius: {inner}px;
}}
QFrame#codeBar {{ border-bottom: 1px solid {line}; }}
QFrame#codeStatusStrip {{
    border-top: 1px solid {line}; border-bottom-left-radius: {inner}px; border-bottom-right-radius: {inner}px;
}}
QFrame#codeStatusStrip QLabel {{ color: {c.faint}; font-size: 11px; }}
QFrame#codeStatusStrip QLabel#codeErrorCount {{ color: {c.error_text}; }}
QFrame#codeStatusStrip QToolButton {{ color: {c.faint}; padding: 1px 6px; font-size: 11px; }}
QFrame#codeStatusStrip QToolButton:checked {{
    background: transparent; border-color: transparent; color: {c.muted};
}}
QFrame#editorCard {{ background: {c.field}; border: 1px solid {line}; border-radius: {theme.RADIUS_CARD}px; }}
QFrame#editorCard QStackedWidget, QFrame#editorCard #presetView {{ background: {c.field}; }}
QPlainTextEdit[embedded="true"] {{
    background: {c.field}; border: 0; border-radius: 0; padding: 0; selection-background-color: {css_soft(c)};
    selection-color: {c.text};
}}
QTabBar#codeTabs {{ background: transparent; }}
QTabBar#codeTabs::tab {{
    background: transparent; border: 0; padding: 0 14px 0 12px; margin: 0 1px; min-width: 40px;
    color: {c.muted};
}}
QTabBar#codeTabs::close-button {{
    image: {svg_url("close", c.muted)}; subcontrol-position: right; margin-right: 6px; border-radius: 4px;
    width: 14px; height: 14px;
}}
QTabBar#codeTabs::close-button:hover {{
    background: {theme.css(c.hover)}; image: {svg_url("close", c.text)};
}}
QTabBar#codeTabs QToolButton {{ background: {c.panel}; border: 0; }}
QLabel#codeDirty {{ font-size: 11px; }}
QPushButton#noTimeLimit {{
    background: {c.raised}; border: 1px solid {theme.css(c.line_strong)}; border-radius: 11px;
    color: {c.muted}; padding: 1px 9px; font-size: 11px; font-weight: 500; min-height: 18px;
}}
QPushButton#noTimeLimit:checked {{
    background: {theme.css(c.accent_soft)}; border-color: {theme.css(c.accent_line)}; color: {c.accent_text};
}}
QPushButton#noTimeLimit:hover {{ color: {c.text}; }}
QLabel#codeNotice {{
    background: {theme.css(c.warning[:7] + "1f")};
    color: {c.warning}; border-bottom: 1px solid {theme.css(c.line)}; padding: 6px 14px;
}}
QWidget#findBar {{ background: {c.panel}; border-bottom: 1px solid {theme.css(c.line)}; }}
QLabel#codeState {{ color: {c.muted}; }}
QLabel#codeState[tone="bad"] {{ color: {c.error_text}; }}
QLabel#codeError {{ color: {c.text}; font-weight: 600; }}
QLabel#codeSyntax {{ color: {c.error_text}; }}
QLabel#codeTrace {{
    background: {c.field}; border: 1px solid {theme.css(c.line)}; border-radius: 10px; padding: 8px 12px;
    color: {c.muted};
}}
QFrame#codeHintCard {{
    background: {theme.css(c.accent_soft)}; border: 1px solid {theme.css(c.accent_line)}; border-radius: 12px;
}}
QFrame#codeHintCard QLabel {{ background: transparent; border: 0; }}
QFrame#codeErrorCard {{
    background: {c.raised}; border: 1px solid {theme.css(c.line_strong)}; border-radius: 12px;
}}
QFrame#codeErrorCard QLabel {{ background: transparent; border: 0; }}
QLabel#codeHintTitle {{ font-weight: 650; }}
QLabel#codeHint {{ color: {c.muted}; }}
QToolButton#codeFix {{
    background: {accent_grad}; color: {c.on_accent}; border: 0; border-radius: 8px; padding: 4px 11px;
    font-weight: 600;
}}
QToolButton#codeFix:hover {{ background: {theme.mix(c.accent, c.on_accent, 0.14)}; }}
QTabWidget#codePanel::pane {{ border: 0; border-top: 1px solid {theme.css(c.line)}; top: -1px; }}
QTabWidget#codePanel > QTabBar::tab {{ padding: 10px 11px 9px 11px; margin-left: 2px; }}
QTabWidget#codePanel > QTabBar {{ margin-left: 6px; }}
QTabWidget#codePanel QScrollArea, QWidget#codeOutputPage {{ background: {c.panel}; }}
QTreeWidget#codeExplorer {{ background: transparent; border: 0; }}
QTreeWidget#codeExplorer::item {{ padding: 0; margin: 0; border: 0; background: transparent; }}
QTreeWidget#codeExplorer::item:selected, QTreeWidget#codeExplorer::item:hover {{ background: transparent; }}
QListWidget#codeChapters {{ background: transparent; border: 0; }}
QListWidget#codeChapters::item {{ padding: 0; margin: 0; background: transparent; }}
QListView#codeCompletion {{
    background: {c.raised}; border: 1px solid {theme.css(c.line_strong)}; border-radius: 10px; padding: 4px;
    outline: 0;
}}
QListView#codeCompletion::item {{ padding: 5px 10px; border-radius: 7px; margin: 0; }}
QListView#codeCompletion::item:selected {{ background: {theme.css(c.accent_soft)}; color: {c.text}; }}
QLabel#paramsStatus {{ color: {c.muted}; }}
QLabel#paramsStatus[tone="bad"] {{ color: {c.error_text}; }}
QFrame#explorerFooter {{ background: transparent; border: 0; border-top: 1px solid {theme.css(c.line)}; }}
QFrame#presetHead {{ background: {c.panel}; border: 0; border-bottom: 1px solid {theme.css(c.line)}; }}
#codePage QPushButton[iconOnly="true"] {{ padding: 0; border-radius: 7px; }}
QDialog#quickOpen {{ background: {c.raised}; border: 1px solid {theme.css(c.line_strong)}; }}
QLineEdit#codeFilter QToolButton {{ padding: 0; margin: 0; border: 0; min-width: 0; min-height: 0; }}
QLineEdit#codeFilter {{ padding-left: 8px; border-radius: {r}px; }}
"""


def css_soft(c: theme.Colours) -> str:
    """The selection colour of the code: the accent at a third, so the syntax colours still read."""
    tint = theme.qcolor(c.accent)
    return f"rgba({tint.red()}, {tint.green()}, {tint.blue()}, 90)"


theme.register_rules(rules)
