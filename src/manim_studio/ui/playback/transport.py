"""The transport pill (Lumen, ADR 0063): play, the ends, the time, a scrub bar, repeat and speed - floating
over the bottom of the stage instead of a bar under it.

``PlayButton`` is the round accent button; it draws a play triangle or two pause bars from its *text*
(``"Play"`` or ``"Pause"``, which the window sets as before), so the text stays the accessible name. The pill
owns no behaviour: the window hands it the callables to run and the existing play button and slider.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, QRectF, QSize, Qt
from PySide6.QtGui import QAction, QLinearGradient, QPainter, QPainterPath, QPaintEvent, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMenu, QPushButton, QSlider, QToolButton, QWidget

from ..style import icons, theme
from ..style.card import Pill

SPEEDS = (0.25, 0.5, 1.0, 1.5, 2.0)
MARGIN = 16  # from the bottom of the stage


class PlayButton(QPushButton):
    """The round play/pause button: gradient accent circle, glyph by the text (``Play`` or ``Pause``)."""

    SIZE = 38

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Play", parent)
        self.setObjectName("playButton")
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Play or pause (Space)")
        self.setFlat(True)

    def sizeHint(self) -> QSize:
        return QSize(self.SIZE, self.SIZE)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def paintEvent(self, event: QPaintEvent) -> None:
        c = theme.THEME
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        box = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        gradient = QLinearGradient(box.topLeft(), box.bottomRight())
        gradient.setColorAt(0.0, theme.qcolor(c.accent))
        gradient.setColorAt(1.0, theme.qcolor(c.accent_2))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawEllipse(box)
        if self.underMouse():
            painter.setBrush(theme.qcolor(c.hover))
            painter.drawEllipse(box)
        if self.hasFocus():
            painter.setPen(QPen(theme.qcolor(c.on_accent), 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(box.adjusted(2, 2, -2, -2))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme.qcolor(c.on_accent))
        cx, cy = box.center().x(), box.center().y()
        if self.text() == "Pause":
            painter.drawRoundedRect(QRectF(cx - 6, cy - 7, 4, 14), 1.5, 1.5)
            painter.drawRoundedRect(QRectF(cx + 2, cy - 7, 4, 14), 1.5, 1.5)
        else:
            path = QPainterPath()
            path.moveTo(cx - 4.5, cy - 8)
            path.lineTo(cx + 8, cy)
            path.lineTo(cx - 4.5, cy + 8)
            path.closeSubpath()
            painter.drawPath(path)


class TransportPill(Pill):
    """Start, play, end | time | scrub | repeat, speed."""

    def __init__(
        self,
        play_button: PlayButton,
        slider: QSlider,
        *,
        to_start: Callable[[], None],
        to_end: Callable[[], None],
        set_loop: Callable[[bool], None],
        set_speed: Callable[[float], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("pill")
        row = QHBoxLayout(self)
        row.setContentsMargins(6, 6, 12, 6)
        row.setSpacing(6)
        self.start_button = self._tool("player-start", "Back to the start (Home)", to_start)
        self.play_button = play_button
        self.end_button = self._tool("player-end", "To the end (End)", to_end)
        row.addWidget(self.start_button)
        row.addWidget(play_button)
        row.addWidget(self.end_button)
        row.addWidget(self._separator())
        self.time = QLabel("0:00.00")
        self.time.setFont(theme.font("label", kind="mono"))
        self.time.setMinimumWidth(66)
        self.total = QLabel("/ 0:00.00")
        self.total.setFont(theme.font("label", kind="mono"))
        self.total.setProperty("role", "hint")
        row.addWidget(self.time)
        row.addWidget(self.total)
        slider.setFixedWidth(160)
        self.slider = slider
        row.addWidget(slider)
        self.tail_separator = self._separator()
        row.addWidget(self.tail_separator)
        self.loop_button = self._tool("player-loop", "Repeat", lambda: None, checkable=True)
        self.loop_button.toggled.connect(set_loop)
        row.addWidget(self.loop_button)
        self.speed_button = QToolButton()
        self.speed_button.setObjectName("speedButton")
        self.speed_button.setToolTip("Playback speed")
        self.speed_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.speed_button.setFont(theme.font("caption", kind="mono"))
        menu = QMenu(self.speed_button)
        self.speed_actions: dict[float, QAction] = {}
        for speed in SPEEDS:
            action = menu.addAction(f"{speed:g}×")
            action.setCheckable(True)
            action.triggered.connect(lambda _=False, s=speed: (set_speed(s), self.set_speed(s)))
            self.speed_actions[speed] = action
        self.speed_button.setMenu(menu)
        row.addWidget(self.speed_button)
        self.set_speed(1.0)

    def _tool(
        self, glyph: str, tip: str, slot: Callable[[], None], *, checkable: bool = False
    ) -> QToolButton:
        button = QToolButton()
        button.setObjectName("iconButton")
        button.setIcon(icons.icon(glyph, "muted"))
        button.setIconSize(QSize(16, 16))
        button.setToolTip(tip)
        button.setCheckable(checkable)
        button.setFixedSize(30, 30)
        if not checkable:
            button.clicked.connect(slot)
        return button

    @staticmethod
    def _separator() -> QWidget:
        line = QWidget()
        line.setFixedSize(1, 18)
        line.setObjectName("topBarSeparator")  # the same hairline as the top bar's
        line.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        return line

    # -- fitting a narrow stage ------------------------------------------------------------------------

    def set_compact(self, compact: bool) -> None:
        """Only the buttons and the time (a narrow stage); the scrub bar, repeat and speed come back when
        there is room."""
        for widget in (self.total, self.slider, self.tail_separator, self.loop_button, self.speed_button):
            widget.setVisible(not compact)
        self.layout().invalidate()

    def fit(self, room: int) -> None:
        """Show everything if it fits in ``room`` pixels, else the compact form."""
        self.set_compact(False)
        if self.layout().sizeHint().width() > room:
            self.set_compact(True)

    # -- state -------------------------------------------------------------------------------------

    def set_time(self, t: float, duration: float) -> None:
        self.time.setText(_clock(t))
        self.total.setText(f"/ {_clock(duration)}")

    def set_speed(self, speed: float) -> None:
        self.speed_button.setText(f"{speed:g}×")
        for value, action in self.speed_actions.items():
            action.setChecked(value == speed)

    def set_loop(self, on: bool) -> None:
        if self.loop_button.isChecked() != on:
            self.loop_button.blockSignals(True)
            self.loop_button.setChecked(on)
            self.loop_button.blockSignals(False)


def _clock(seconds: float) -> str:
    seconds = max(0.0, seconds)
    minutes, rest = divmod(seconds, 60.0)
    return f"{int(minutes)}:{rest:05.2f}"


class _Placer(QObject):
    """Keeps a floating widget at the bottom centre of its parent as the parent is resized."""

    def __init__(self, parent: QWidget, child: QWidget) -> None:
        super().__init__(parent)
        self.parent_widget, self.child = parent, child
        parent.installEventFilter(self)
        self.place()

    def place(self) -> None:
        child, parent = self.child, self.parent_widget
        if hasattr(child, "fit"):
            child.fit(parent.width() - 2 * MARGIN)
        child.layout().activate()
        child.adjustSize()
        width = min(child.sizeHint().width(), max(parent.width() - 2 * MARGIN, 120))
        child.setGeometry(
            round((parent.width() - width) / 2),
            parent.height() - (child.layout().sizeHint().height() + 2) - MARGIN,
            width,
            (child.layout().sizeHint().height() + 2),
        )
        child.raise_()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Show) and watched is self.parent_widget:
            self.place()
        return False


def float_at_bottom(parent: QWidget, child: QWidget) -> _Placer:
    """Make ``child`` (already parented to ``parent``) float at the bottom centre of ``parent``."""
    return _Placer(parent, child)


def install_transport_rules() -> None:
    """The round button paints itself: no padding or minimum height from the general button rule."""

    def rules(c: theme.Colours) -> str:
        size = PlayButton.SIZE
        return (
            f"QPushButton#playButton {{ padding: 0px; min-height: {size}px; min-width: {size}px;"
            " border: 0; background: transparent; }"
        )

    theme.register_rules(rules)


install_transport_rules()
