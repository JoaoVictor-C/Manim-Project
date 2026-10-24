"""The control bar of the full-screen player (P12): the usual video player's, over the picture.

A seek bar with the elapsed and total time, then the title, the transport (start, back, play / pause,
forward, end, loop) and, at the right, the speed, the volume and the button that leaves full screen.
It only reports what was asked (signals) and shows what it is told (``set_*``): the presenter connects
it to the editor's own playback.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMenu,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import icons, theme

SEEK_STEPS = 1000  # slider steps per second
SKIP_SECONDS = 5.0  # the back and forward buttons
SPEEDS = (0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0)


def clock(seconds: float) -> str:
    """``0:02.40``: minutes, seconds and hundredths (an animation is short and its frames matter)."""
    seconds = max(0.0, seconds)
    minutes, rest = divmod(seconds, 60.0)
    return f"{int(minutes)}:{rest:05.2f}"


def speed_text(speed: float) -> str:
    return f"{speed:g}×"


class SeekSlider(QSlider):
    """A slider that jumps to where it is clicked, like a video player's seek bar."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setObjectName("seekBar")

    def _value_at(self, x: float) -> int:
        span = max(1, self.width())
        return round(self.minimum() + (self.maximum() - self.minimum()) * max(0.0, min(1.0, x / span)))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.setValue(self._value_at(event.position().x()))
            self.setSliderDown(True)
            self.sliderMoved.emit(self.value())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self.isSliderDown():
            self.setValue(self._value_at(event.position().x()))
            self.sliderMoved.emit(self.value())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.isSliderDown():
            self.setSliderDown(False)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class PlayerBar(QWidget):
    seekRequested = Signal(float)  # seconds, while the seek bar is pressed or dragged
    playToggled = Signal()
    skipRequested = Signal(float)  # seconds, negative to go back
    startRequested = Signal()
    endRequested = Signal()
    loopToggled = Signal(bool)
    speedChanged = Signal(float)
    volumeChanged = Signal(float)  # 0..1
    muteToggled = Signal(bool)
    leaveRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("playerBar")
        ink = theme.css(theme.THEME.text)
        accent = theme.css(theme.THEME.accent)
        self.setStyleSheet(
            f"#playerBar {{ background: rgba(0, 0, 0, 190); }}"
            f"QLabel {{ color: {ink}; background: transparent; }}"
            f"QToolButton {{ background: transparent; border: none; padding: 4px; color: {ink}; }}"
            "QSlider::groove:horizontal { height: 4px; background: rgba(255, 255, 255, 80);"
            " border-radius: 2px; }"
            f"QSlider::sub-page:horizontal {{ background: {accent}; border-radius: 2px; }}"
            f"QSlider::handle:horizontal {{ background: {accent}; width: 14px; margin: -5px 0;"
            " border-radius: 7px; }"
            "QToolButton:hover { background: rgba(255, 255, 255, 40); border-radius: 6px; }"
            "QToolButton:checked { background: rgba(255, 255, 255, 70); border-radius: 6px; }"
        )
        self.duration = 0.0
        self.speed = 1.0
        self.muted = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 8, 16, 10)
        outer.setSpacing(4)

        seek = QHBoxLayout()
        self.elapsed = QLabel(clock(0))
        self.total = QLabel(clock(0))
        self.seek = SeekSlider()
        self.seek.setRange(0, 0)
        self.seek.sliderMoved.connect(lambda value: self.seekRequested.emit(value / SEEK_STEPS))
        seek.addWidget(self.elapsed)
        seek.addWidget(self.seek, 1)
        seek.addWidget(self.total)
        outer.addLayout(seek)

        row = QHBoxLayout()
        self.title = QLabel("")
        font = self.title.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 2)
        self.title.setFont(font)
        self.start_button = self._button("player-start", "Back to the start (Home)", self.startRequested.emit)
        self.back_button = self._button(
            "player-back", f"Back {SKIP_SECONDS:g} s", lambda: self.skipRequested.emit(-SKIP_SECONDS)
        )
        self.play_button = self._button("play", "Play (Space)", self.playToggled.emit, size=40)
        self.forward_button = self._button(
            "player-forward", f"Forward {SKIP_SECONDS:g} s", lambda: self.skipRequested.emit(SKIP_SECONDS)
        )
        self.end_button = self._button("player-end", "To the end (End)", self.endRequested.emit)
        self.loop_button = self._button("player-loop", "Repeat (L)", None, checkable=True)
        self.loop_button.toggled.connect(self._on_loop)
        left = QHBoxLayout()
        left.addWidget(self.title)
        left.addStretch(1)
        centre = QHBoxLayout()
        for button in (
            self.start_button,
            self.back_button,
            self.play_button,
            self.forward_button,
            self.end_button,
            self.loop_button,
        ):
            centre.addWidget(button)
        right = QHBoxLayout()
        right.addStretch(1)
        self.speed_button = QToolButton()
        self.speed_button.setText(speed_text(1.0))
        self.speed_button.setToolTip("Playback speed")
        self.speed_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.speed_menu = QMenu(self.speed_button)
        self.speed_actions = {}
        for value in SPEEDS:
            action = self.speed_menu.addAction(speed_text(value))
            action.setCheckable(True)
            action.setChecked(value == 1.0)
            action.triggered.connect(lambda _=False, v=value: self.set_speed(v, announce=True))
            self.speed_actions[value] = action
        self.speed_button.setMenu(self.speed_menu)
        self.mute_button = self._button("player-volume", "Mute (M)", None, checkable=True)
        self.mute_button.toggled.connect(self._on_mute)
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setObjectName("volumeBar")
        self.volume.setRange(0, 100)
        self.volume.setValue(100)
        self.volume.setFixedWidth(90)
        self.volume.valueChanged.connect(lambda value: self.volumeChanged.emit(value / 100))
        self.leave_button = self._button(
            "fullscreen-exit", "Leave full screen (Esc)", self.leaveRequested.emit
        )
        for widget in (self.speed_button, self.mute_button, self.volume, self.leave_button):
            right.addWidget(widget)
        row.addLayout(left, 1)
        row.addLayout(centre, 0)
        row.addLayout(right, 1)
        outer.addLayout(row)
        self.set_playing(False)

    def _button(self, icon: str, tip: str, slot, *, checkable: bool = False, size: int = 28) -> QToolButton:
        button = QToolButton()
        button.setIcon(icons.icon(icon))
        button.setIconSize(QSize(size, size))
        button.setToolTip(tip)
        button.setCheckable(checkable)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        if slot is not None:
            button.clicked.connect(lambda _=False: slot())
        return button

    # -- what the bar is told -----------------------------------------------------------------

    def set_time(self, t: float, duration: float) -> None:
        """Show the playhead (without sending it back)."""
        self.duration = duration
        self.elapsed.setText(clock(t))
        self.total.setText(clock(duration))
        self.seek.blockSignals(True)
        self.seek.setRange(0, round(duration * SEEK_STEPS))
        if not self.seek.isSliderDown():
            self.seek.setValue(round(t * SEEK_STEPS))
        self.seek.blockSignals(False)

    def set_playing(self, playing: bool) -> None:
        self.play_button.setIcon(icons.icon("pause" if playing else "play"))
        self.play_button.setToolTip("Pause (Space)" if playing else "Play (Space)")

    def set_title(self, text: str) -> None:
        self.title.setText(text)

    def set_loop(self, on: bool) -> None:
        self.loop_button.blockSignals(True)
        self.loop_button.setChecked(on)
        self.loop_button.blockSignals(False)
        self._on_loop(on, announce=False)

    def set_speed(self, speed: float, announce: bool = False) -> None:
        self.speed = speed
        self.speed_button.setText(speed_text(speed))
        for value, action in self.speed_actions.items():
            action.setChecked(value == speed)
        if announce:
            self.speedChanged.emit(speed)

    def set_speed_available(self, available: bool) -> None:
        """Sound plays at its own speed: with sound the speed is 1x and cannot be changed."""
        self.speed_button.setEnabled(available)
        self.speed_button.setToolTip("Playback speed" if available else "A scene with sound plays at 1×")

    def set_audio_available(self, available: bool) -> None:
        self.volume.setEnabled(available)
        self.mute_button.setEnabled(available)
        if not available:
            self.volume.setToolTip("This project has no sound")
            self.mute_button.setToolTip("This project has no sound")
        else:
            self.volume.setToolTip("Volume (Up, Down)")
            self.mute_button.setToolTip("Mute (M)")

    def set_volume(self, volume: float, muted: bool) -> None:
        self.volume.blockSignals(True)
        self.volume.setValue(round(volume * 100))
        self.volume.blockSignals(False)
        self.mute_button.blockSignals(True)
        self.mute_button.setChecked(muted)
        self.mute_button.blockSignals(False)
        self.muted = muted
        self._show_volume_icon(volume, muted)

    # -- what the user does ------------------------------------------------------------------

    def _on_loop(self, on: bool, announce: bool = True) -> None:
        self.loop_button.setIcon(icons.icon("player-loop" if on else "player-loop-off"))
        if announce:
            self.loopToggled.emit(on)

    def _on_mute(self, on: bool) -> None:
        self.muted = on
        self._show_volume_icon(self.volume.value() / 100, on)
        self.muteToggled.emit(on)

    def _show_volume_icon(self, volume: float, muted: bool) -> None:
        silent = muted or volume <= 0
        self.mute_button.setIcon(icons.icon("player-mute" if silent else "player-volume"))

    def contains_global(self, point: QPoint) -> bool:
        """Is the pointer over the bar (it stays shown then)?"""
        return self.isVisible() and self.rect().contains(self.mapFromGlobal(point))
