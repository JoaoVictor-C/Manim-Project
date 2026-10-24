"""Full screen (P12): the animation alone, filling the screen.

The canvas moves out of the editor into a black, frameless full-screen window, drawn plain (no
selection outline, handles or motion path) and fitted to the screen, and goes back where it was when
the window closes. The editor's own playback drives it, so what is shown is the preview exactly:

    Space or a click   play / pause        Left, Right   one frame back / forward (Shift: ten)
    Home, End          start / end         Esc or F11    leave

A line at the bottom says so and shows the time; it and the mouse pointer go away when the mouse
rests, and come back when it moves.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer
from PySide6.QtGui import QCursor, QKeyEvent
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from . import theme, viewport

if TYPE_CHECKING:
    from .main_window import MainWindow

HINT = "Space: play / pause    ← →: frame (Shift: ten)    Home End    Esc: leave"
IDLE_MS = 2500  # the pointer and the hint go away after this long without mouse movement
KEYS_LEAVE = (Qt.Key.Key_Escape, Qt.Key.Key_F11)


class _CanvasGuard(QObject):
    """While presenting, the canvas only shows the picture: its tools must not select or move
    anything, so mouse and key events are taken here (a click plays or pauses)."""

    def __init__(self, presenter: Presenter) -> None:
        super().__init__(presenter)
        self.presenter = presenter

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        kind = event.type()
        if kind == QEvent.Type.MouseMove:
            self.presenter.wake()
            return True
        if kind == QEvent.Type.MouseButtonRelease:
            self.presenter.window_.toggle_play()
            return True
        if kind in (
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonDblClick,
            QEvent.Type.Wheel,
            QEvent.Type.ContextMenu,
        ):
            return True
        if kind == QEvent.Type.KeyPress:
            self.presenter.keyPressEvent(event)  # type: ignore[arg-type]
            return True
        return False


class Presenter(QWidget):
    def __init__(self, window: MainWindow) -> None:
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.window_ = window
        self.setWindowTitle("Manim Studio - full screen")
        self.setStyleSheet("background: black;")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.active = False
        self._saved: tuple | None = None
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self.hint = QLabel(HINT, self)
        self.hint.setStyleSheet(
            f"color: {theme.css(theme.THEME.text)}; background: rgba(0, 0, 0, 150); padding: 6px 12px;"
        )
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.time_label = QLabel("", self)
        self.time_label.setStyleSheet(self.hint.styleSheet())
        self._guard = _CanvasGuard(self)
        self._idle = QTimer(self)
        self._idle.setSingleShot(True)
        self._idle.setInterval(IDLE_MS)
        self._idle.timeout.connect(self._rest)
        window.playheadMoved.connect(lambda _t: self._update_time())

    # -- going in and out -------------------------------------------------------------------

    def start(self) -> bool:
        """Show the animation full screen. False when there is nothing to show."""
        window = self.window_
        if self.active or window.project is None:
            return False
        canvas = window.canvas
        self._saved = (canvas.view, canvas.show_overlays, canvas.focusPolicy())
        window.stage.layout().removeWidget(canvas)
        self._layout.addWidget(canvas, 1)
        canvas.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        canvas.installEventFilter(self._guard)
        canvas.setMouseTracking(True)
        canvas.set_overlays(False)
        canvas.presenting = True
        canvas.show()
        self.active = True
        self.showFullScreen()
        canvas.set_view(viewport.View())  # Fit: the whole frame on the screen
        self.setFocus()
        self.activateWindow()
        self._place_labels()
        self._update_time()
        self.wake()
        return True

    def finish(self) -> None:
        """Back to the editor: the canvas returns to its place with the view it had."""
        if not self.active:
            return
        window = self.window_
        canvas = window.canvas
        view, overlays, focus = self._saved
        self.active = False
        self._idle.stop()
        canvas.removeEventFilter(self._guard)
        canvas.unsetCursor()
        self.unsetCursor()
        self._layout.removeWidget(canvas)
        window.stage.layout().insertWidget(0, canvas, 1)
        canvas.setFocusPolicy(focus)
        canvas.presenting = False
        canvas.set_overlays(overlays)
        canvas.set_view(view)
        self.hide()
        window.refresh()

    # -- the hint and the pointer -------------------------------------------------------------

    def wake(self) -> None:
        """Mouse movement: the pointer and the hint show, and go again when it rests."""
        self.unsetCursor()
        self.window_.canvas.unsetCursor()
        self.hint.show()
        self.time_label.show()
        self._idle.start()

    def _rest(self) -> None:
        if not self.active:
            return
        blank = QCursor(Qt.CursorShape.BlankCursor)
        self.setCursor(blank)
        self.window_.canvas.setCursor(blank)
        self.hint.hide()
        self.time_label.hide()

    def _place_labels(self) -> None:
        self.hint.adjustSize()
        self.time_label.adjustSize()
        width, height = self.width(), self.height()
        self.hint.move(QPoint((width - self.hint.width()) // 2, height - self.hint.height() - 24))
        self.time_label.move(QPoint(width - self.time_label.width() - 24, 24))

    def _update_time(self) -> None:
        project = self.window_.project
        if project is None or not self.active:
            return
        self.time_label.setText(f"{self.window_.t:.2f} / {project.canvas.duration:.2f} s")
        self.time_label.adjustSize()
        self._place_labels()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place_labels()

    # -- keys ---------------------------------------------------------------------------------

    def keyPressEvent(self, event: QKeyEvent) -> None:
        window = self.window_
        key = event.key()
        step = 10 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
        self.wake()
        if key in KEYS_LEAVE:
            self.finish()
        elif key == Qt.Key.Key_Space:
            window.toggle_play()
        elif key == Qt.Key.Key_Left:
            window.step(-step)
        elif key == Qt.Key.Key_Right:
            window.step(step)
        elif key == Qt.Key.Key_Home:
            window.seek(0.0)
        elif key == Qt.Key.Key_End and window.project is not None:
            window.seek(window.project.canvas.duration)
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        self.finish()
        super().closeEvent(event)
