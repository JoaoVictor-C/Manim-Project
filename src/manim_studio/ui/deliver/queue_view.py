"""The pieces the Deliver page is drawn with (Lumen, ADR 0063): destination cards, the progress ring, the
rows of the render queue and the estimate tiles.

None of them holds a state the page does not hand it: the page owns the queue (``RenderQueue``), the options
and the jobs; these only show them. Everything is painted from the theme's tokens when it is shown.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from ..style import icons, theme
from ..style.elided_label import ElidedLabel
from ..style.icon_tile import IconTile

ROW_HEIGHT = 64  # px: a job in the queue
STATES = ("idle", "starting", "running", "queued", "done", "failed", "cancelled")


def _rules(c: theme.Colours) -> str:
    return f"""
QTreeWidget#queueTree {{ background: transparent; border: 0; }}
QTreeWidget#queueTree::item {{ border: 0; background: transparent; }}
QTreeWidget#queueTree::item:hover {{ background: {theme.css(c.hover)}; border-radius: 12px; }}
QTreeWidget#queueTree::item:selected {{ background: {theme.css(c.accent_soft)}; border-radius: 12px; }}
QFrame#estimateTile {{ background: {c.raised}; border: 1px solid {theme.css(c.line)}; border-radius: 12px; }}
QFrame#estimateTile QLabel {{ background: transparent; }}
QLabel[role="tileValue"] {{ color: {c.text}; font-size: 16px; font-weight: 700; }}
QFrame#queueNow {{ background: {c.raised}; border: 1px solid {theme.css(c.line)}; border-radius: 14px; }}
QFrame#queueNow[running="true"] {{ border-color: {theme.css(c.accent_line)}; }}
QFrame#queueNow QLabel {{ background: transparent; }}
QLabel[role="error"] {{ color: {c.error_text}; background: transparent; }}
QLabel[role="rowName"] {{ color: {c.text}; font-weight: 600; background: transparent; }}
QLabel[role="rowDetail"] {{ color: {c.faint}; font-size: 11px; background: transparent; }}
QLabel[role="destTitle"] {{ color: {c.text}; font-size: 13px; font-weight: 650; background: transparent; }}
QLabel[role="destSummary"] {{ color: {c.muted}; font-size: 11px; background: transparent; }}
"""


theme.register_rules(_rules)


def _soft(token: str, alpha: float) -> QColor:
    colour = QColor(theme.qcolor(getattr(theme.THEME, token)))
    colour.setAlphaF(alpha)
    return colour


class SlimBar(QProgressBar):
    """A progress bar drawn as a thin line (5 px): no text, and a minimum size that says so."""

    def __init__(self, height: int = 5, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTextVisible(False)
        self.setFixedHeight(height)

    def minimumSizeHint(self) -> QSize:
        return QSize(40, self.height())

    def sizeHint(self) -> QSize:
        return QSize(160, self.height())


class ProgressRing(QWidget):
    """A ring that shows where a job is: a gradient arc and the percent while it renders, a check when done,
    a cross when it failed or was cancelled, a dashed ring while it waits. ``set_state(state, fraction)``."""

    def __init__(self, size: int = 44, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.state, self.fraction = "idle", 0.0
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def sizeHint(self) -> QSize:
        return self.size()

    def set_state(self, state: str, fraction: float = 0.0) -> None:
        if state not in STATES:
            raise ValueError(state)
        self.state, self.fraction = state, max(0.0, min(1.0, fraction))
        self.update()

    def percent_text(self) -> str:
        return f"{round(100 * self.fraction)}%" if self.state == "running" else ""

    def paintEvent(self, _event: QPaintEvent) -> None:
        c = theme.THEME
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        thick = max(2.5, self.width() / 11)
        rect = QRectF(self.rect()).adjusted(thick / 2, thick / 2, -thick / 2, -thick / 2)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if self.state in ("done", "failed", "cancelled"):
            token = {"done": "success", "failed": "danger", "cancelled": "muted"}[self.state]
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(_soft(token, 0.16))
            painter.drawEllipse(rect)
            glyph = {"done": "check", "failed": "close", "cancelled": "close"}[self.state]
            side = round(self.width() * 0.5)
            target = QRectF(0, 0, side, side)
            target.moveCenter(rect.center())
            icons.icon(glyph, token).paint(painter, target.toRect())
            painter.end()
            return
        track = QPen(theme.qcolor(c.surface_3), thick)
        if self.state == "queued":
            track = QPen(theme.qcolor(c.line_strong), max(1.5, thick / 2), Qt.PenStyle.DashLine)
        painter.setPen(track)
        painter.drawEllipse(rect)
        if self.state in ("running", "starting"):
            gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
            gradient.setColorAt(0.0, theme.qcolor(c.accent))
            gradient.setColorAt(1.0, theme.qcolor(c.accent_2))
            pen = QPen(gradient, thick)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            share = self.fraction if self.state == "running" else 0.12
            painter.drawArc(rect, 90 * 16, -round(share * 360 * 16))
        text = self.percent_text()
        if text and self.width() >= 36:
            font = theme.mono_font(8)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(theme.qcolor(c.text))
            painter.drawText(QRectF(self.rect()), Qt.AlignmentFlag.AlignCenter, text)
        elif self.state in ("idle", "queued"):
            side = round(self.width() * 0.42)
            target = QRectF(0, 0, side, side)
            target.moveCenter(rect.center())
            icons.icon("clock" if self.state == "queued" else "deliver", "muted").paint(
                painter, target.toRect()
            )
        painter.end()


class JobRow(QWidget):
    """One job of the queue: a small ring, its file name and a line of detail; a hairline card around it."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)  # the tree takes the clicks
        self.ring = ProgressRing(34)
        self.name = ElidedLabel(minimum=60)
        self.name.setProperty("role", "rowName")
        self.detail = ElidedLabel(minimum=60)
        self.detail.setProperty("role", "rowDetail")
        words = QVBoxLayout()
        words.setSpacing(1)
        words.addWidget(self.name)
        words.addWidget(self.detail)
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 0, 12, 0)
        row.setSpacing(12)
        row.addWidget(self.ring)
        row.addLayout(words, 1)
        self.setMinimumHeight(ROW_HEIGHT - 8)

    def show_job(self, name: str, detail: str, state: str, fraction: float, tip: str = "") -> None:
        self.name.setText(name)
        self.detail.setText(detail)
        self.setToolTip(tip or name)
        self.ring.set_state(state, fraction)

    def paintEvent(self, _event: QPaintEvent) -> None:
        c = theme.THEME
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 3.5, -0.5, -3.5)
        painter.setBrush(theme.qcolor(c.raised))
        edge = c.accent_line if self.ring.state in ("running", "starting") else c.line
        painter.setPen(QPen(theme.qcolor(edge), 1))
        painter.drawRoundedRect(rect, 12, 12)
        painter.end()


class BlankTextDelegate(QStyledItemDelegate):
    """Draws the item's background and nothing else: the row widget on top of it says everything."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        shown = QStyleOptionViewItem(option)
        self.initStyleOption(shown, index)
        shown.text = ""
        shown.state &= ~QStyle.StateFlag.State_HasFocus
        widget = option.widget
        style = widget.style() if widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, shown, painter, widget)

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:
        return QSize(120, ROW_HEIGHT)


class DestinationCard(QAbstractButton):
    """A large selectable card: an icon tile (a gradient), a title and a one-line summary. The chosen one is
    tinted with the accent and has a check at its right."""

    def __init__(
        self,
        key: str,
        title: str,
        summary: str,
        icon: str,
        gradient: tuple[str, str] | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.key = key
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(66)
        self.setAccessibleName(title)
        self.setText(title)
        self.tile = IconTile(icon, tone="neutral", gradient=gradient, size=40, radius=12)
        self.title_label = QLabel(title)
        self.title_label.setProperty("role", "destTitle")
        self.summary_label = QLabel(summary)
        self.summary_label.setProperty("role", "destSummary")
        self.summary_label.setWordWrap(True)
        words = QVBoxLayout()
        words.setSpacing(1)
        words.addWidget(self.title_label)
        words.addWidget(self.summary_label)
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 10, 38, 10)
        row.setSpacing(12)
        row.addWidget(self.tile)
        row.addLayout(words, 1)
        for child in (self.tile, self.title_label, self.summary_label):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setToolTip(summary)

    def set_summary(self, text: str) -> None:
        self.summary_label.setText(text)
        self.setToolTip(text)

    def sizeHint(self) -> QSize:
        return QSize(240, max(66, self.layout().sizeHint().height()))

    def minimumSizeHint(self) -> QSize:
        return QSize(180, 66)

    def hasHeightForWidth(self) -> bool:
        return False

    def paintEvent(self, _event: QPaintEvent) -> None:
        c = theme.THEME
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self.isChecked():
            fill, edge = theme.qcolor(c.accent_soft), theme.qcolor(c.accent_line)
        else:
            fill = theme.qcolor(c.surface_3 if self.underMouse() else c.raised)
            edge = theme.qcolor(c.line_strong if self.underMouse() else c.line)
        if self.hasFocus():
            edge = theme.qcolor(c.accent)
        painter.setBrush(fill)
        painter.setPen(QPen(edge, 1))
        painter.drawRoundedRect(rect, 14, 14)
        if self.isChecked():
            mark = QRectF(0, 0, 18, 18)
            mark.moveCenter(QRectF(rect.right() - 22, rect.center().y(), 0, 0).center())
            icons.icon("check", "accent_text").paint(painter, mark.toRect())
        painter.end()


class EstimateTile(QFrame):
    """A caption over a value in mono type: "Length", "0:07 - 210 frames"."""

    def __init__(self, caption: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("estimateTile")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.caption = QLabel(caption)
        self.caption.setProperty("role", "hint")
        self.value = ElidedLabel("-", minimum=40)
        self.value.setProperty("role", "tileValue")
        self.value.setFont(theme.mono_font())
        column = QVBoxLayout(self)
        column.setContentsMargins(14, 10, 14, 10)
        column.setSpacing(2)
        column.addWidget(self.caption)
        column.addWidget(self.value)

    def set_value(self, text: str, tip: str = "") -> None:
        self.value.setText(text)
        self.setToolTip(tip)
