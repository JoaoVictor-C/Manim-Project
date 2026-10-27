"""The page switcher (Lumen, ADR 0063): a pill of segments - an icon, a label and a key hint each - with an
indicator that slides to the current one.

It speaks the part of ``QTabBar`` that ``PageHost`` and the tests use (``addTab``, ``setTabToolTip``,
``setTabData``, ``tabData``, ``tabText``, ``tabIcon``, ``count``, ``currentIndex``, ``setCurrentIndex``,
``currentChanged``), so it replaces the old page bar without anything that drives pages having to change.
In a narrow window the top bar asks for ``set_compact(True)`` and only the icons stay.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtGui import (
    QFontMetrics,
    QHelpEvent,
    QIcon,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from . import motion, theme

HEIGHT = 36
PAD = 3  # the pill's inner padding
SEGMENT_PAD = 13  # horizontal padding inside a segment
ICON = 16
GAP = 7  # between icon and label


@dataclass
class _Segment:
    text: str
    icon: QIcon
    tooltip: str = ""
    data: object = None
    hint: str = ""  # the key hint ("1")
    rect: QRectF = field(default_factory=QRectF)


class PageSwitcher(QWidget):
    currentChanged = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("pageSwitcher")
        self._segments: list[_Segment] = []
        self._current = -1
        self._hover = -1
        self._compact = False
        self._indicator = QRectF()
        self._animation: QVariantAnimation | None = None
        self.setFixedHeight(HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        theme.signals.themeChanged.connect(
            self._on_theme
        )  # a method: it goes with the widget (a lambda did not)

    def _on_theme(self, _name: str = "") -> None:
        self.update()

    # -- the QTabBar subset ----------------------------------------------------------------------

    def addTab(self, icon: QIcon, text: str) -> int:
        self._segments.append(_Segment(text, icon, hint=str(len(self._segments) + 1)))
        self._layout_segments()
        self.updateGeometry()
        if self._current < 0:
            self._current = 0
            self._indicator = QRectF(self._segments[0].rect)
        self.update()
        return len(self._segments) - 1

    def count(self) -> int:
        return len(self._segments)

    def tabText(self, index: int) -> str:
        return self._segments[index].text

    def tabIcon(self, index: int) -> QIcon:
        return self._segments[index].icon

    def setTabToolTip(self, index: int, tip: str) -> None:
        self._segments[index].tooltip = tip

    def setTabData(self, index: int, data: object) -> None:
        self._segments[index].data = data

    def tabData(self, index: int) -> object:
        return self._segments[index].data if 0 <= index < len(self._segments) else None

    def currentIndex(self) -> int:
        return self._current

    def setCurrentIndex(self, index: int) -> None:
        if not 0 <= index < len(self._segments) or index == self._current:
            return
        self._current = index
        self._slide_to(self._segments[index].rect)
        self.update()
        self.currentChanged.emit(index)

    # -- compact mode ----------------------------------------------------------------------------

    def set_compact(self, compact: bool) -> None:
        """Icons only (a narrow window)."""
        if compact != self._compact:
            self._compact = compact
            self._layout_segments()
            if 0 <= self._current < len(self._segments):
                self._indicator = QRectF(self._segments[self._current].rect)
            self.updateGeometry()
            self.update()

    def is_compact(self) -> bool:
        return self._compact

    def full_width(self) -> int:
        """The width the labelled form needs (the top bar compares it with the room it has)."""
        was, self._compact = self._compact, False
        self._layout_segments()
        width = self.sizeHint().width()
        self._compact = was
        self._layout_segments()
        return width

    # -- geometry --------------------------------------------------------------------------------

    def _layout_segments(self) -> None:
        label = QFontMetrics(theme.font("label"))
        hint = QFontMetrics(theme.font("caption", kind="mono"))
        x = float(PAD)
        for segment in self._segments:
            width = SEGMENT_PAD * 2 + ICON
            if not self._compact:
                width += GAP + label.horizontalAdvance(segment.text)
                width += GAP + hint.horizontalAdvance(segment.hint)
            segment.rect = QRectF(x, PAD, width, HEIGHT - 2 * PAD)
            x += width + 2
        self._total = x - 2 + PAD

    def sizeHint(self) -> QSize:
        return QSize(round(getattr(self, "_total", 2 * PAD)), HEIGHT)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def _slide_to(self, target: QRectF) -> None:
        self._stop_animation()
        if not motion.enabled() or not self.isVisible():
            self._indicator = QRectF(target)
            return
        animation = QVariantAnimation(self)
        animation.setDuration(motion.BASE)
        animation.setEasingCurve(motion.curve())
        animation.setStartValue(QRectF(self._indicator))
        animation.setEndValue(QRectF(target))
        animation.valueChanged.connect(self._on_slide)
        animation.finished.connect(self._forget_animation)
        self._animation = animation
        animation.start(QVariantAnimation.DeletionPolicy.DeleteWhenStopped)

    def _forget_animation(self) -> None:
        """A finished animation deletes itself (DeleteWhenStopped): drop our reference to the dead object."""
        self._animation = None

    def _stop_animation(self) -> None:
        animation, self._animation = self._animation, None
        if animation is not None:
            with contextlib.suppress(RuntimeError):  # already deleted
                animation.stop()

    def _on_slide(self, value: object) -> None:
        self._indicator = QRectF(value)
        self.update()

    # -- painting --------------------------------------------------------------------------------

    def paintEvent(self, event) -> None:
        c = theme.THEME
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        outer = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QPen(theme.qcolor(c.line), 1))
        painter.setBrush(theme.qcolor(c.panel))
        painter.drawRoundedRect(outer, 12, 12)
        if self._current >= 0:
            chip = QRectF(self._indicator)
            painter.setPen(QPen(theme.qcolor(c.line_strong), 1))
            painter.setBrush(theme.qcolor(c.surface_3))
            painter.drawRoundedRect(chip.adjusted(0.5, 0.5, -0.5, -0.5), 9, 9)
        label_font, hint_font = theme.font("label"), theme.font("caption", kind="mono")
        for i, segment in enumerate(self._segments):
            active = i == self._current
            tint = c.text if active or i == self._hover else c.muted
            rect = segment.rect
            icon_rect = QRectF(rect.left() + SEGMENT_PAD, rect.center().y() - ICON / 2, ICON, ICON)
            mode = QIcon.Mode.Active if active else QIcon.Mode.Normal
            pixmap = segment.icon.pixmap(ICON * 2, ICON * 2, mode)
            if active:
                pixmap = _tinted(pixmap, theme.qcolor(c.accent_text))
            elif i != self._hover:
                pixmap = _tinted(pixmap, theme.qcolor(c.muted))
            painter.drawPixmap(icon_rect.toRect(), pixmap)
            if self._compact:
                continue
            painter.setFont(label_font)
            painter.setPen(theme.qcolor(tint))
            text_left = icon_rect.right() + GAP
            label_width = QFontMetrics(label_font).horizontalAdvance(segment.text)
            painter.drawText(
                QRectF(text_left, rect.top(), label_width + 2, rect.height()),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                segment.text,
            )
            painter.setFont(hint_font)
            painter.setPen(theme.qcolor(c.faint))
            painter.drawText(
                QRectF(text_left + label_width + GAP, rect.top(), 24, rect.height()),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                segment.hint,
            )
        if self.hasFocus():
            path = QPainterPath()
            path.addRoundedRect(outer.adjusted(-1, -1, 1, 1), 13, 13)
            painter.setPen(QPen(theme.qcolor(c.accent), 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)

    # -- the mouse and the keyboard --------------------------------------------------------------

    def _at(self, point: QPointF) -> int:
        for i, segment in enumerate(self._segments):
            if segment.rect.adjusted(-1, -PAD, 1, PAD).contains(point):
                return i
        return -1

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        index = self._at(event.position())
        if index != self._hover:
            self._hover = index
            self.setCursor(Qt.CursorShape.PointingHandCursor if index >= 0 else Qt.CursorShape.ArrowCursor)
            self.update()

    def leaveEvent(self, event: QEvent) -> None:
        self._hover = -1
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            index = self._at(event.position())
            if index >= 0:
                self.setCurrentIndex(index)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        step = {Qt.Key.Key_Left: -1, Qt.Key.Key_Right: 1}.get(event.key())
        if step is not None and self._segments:
            self.setCurrentIndex(max(0, min(len(self._segments) - 1, self._current + step)))
            return
        super().keyPressEvent(event)

    def event(self, event: QEvent) -> bool:
        if event.type() == QEvent.Type.ToolTip and isinstance(event, QHelpEvent):
            index = self._at(QPointF(event.pos()))
            tip = (self._segments[index].tooltip or self._segments[index].text) if index >= 0 else ""
            if tip:
                QToolTip.showText(event.globalPos(), tip, self)
            else:
                QToolTip.hideText()
            return True
        return super().event(event)


def _tinted(pixmap, colour):
    """``pixmap`` with its opaque pixels painted in ``colour`` (the icons are drawn in one ink)."""
    from PySide6.QtGui import QPixmap

    out = QPixmap(pixmap.size())
    out.setDevicePixelRatio(pixmap.devicePixelRatio())
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.drawPixmap(0, 0, pixmap)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(out.rect(), colour)
    painter.end()
    return out
