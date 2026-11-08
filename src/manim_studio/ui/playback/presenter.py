"""Full screen (P12): the animation alone, filling the screen, with a video player's controls.

The canvas moves out of the editor into a black, frameless full-screen window, drawn plain (no
selection outline, handles or motion path) and fitted to the screen, and goes back where it was when
the window closes. The editor's own playback drives it, so what is shown is the preview exactly.
Over the bottom of the picture is the player bar (``player_bar``): seek bar and times, the title,
start / back / play / forward / end / repeat, the speed, the volume and a button to leave.

    Space or a click   play / pause        Left, Right   one frame back / forward (Shift: ten)
    Home, End          start / end         L             repeat on / off
    Up, Down, M        volume, mute        Esc, F11, double-click   leave

The bar and the mouse pointer go away while the animation plays and the mouse rests, and come back
when it moves; a paused animation keeps the bar.
"""

from __future__ import annotations

import weakref
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer
from PySide6.QtGui import QCursor, QKeyEvent
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ...core.editing import slides
from ..canvas import viewport
from ..style import theme
from .player_bar import PlayerBar

if TYPE_CHECKING:
    from ..main_window import MainWindow

HINT = "Space: play / pause    ← →: frame (Shift: ten)    L: repeat    M: mute    Esc: leave"
SLIDES_HINT = "→ Page Down Space or click: next    ← Page Up: previous    Shift ← →: frame    Esc: leave"
KEYS_NEXT = (Qt.Key.Key_PageDown, Qt.Key.Key_Right, Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter)
KEYS_PREVIOUS = (Qt.Key.Key_PageUp, Qt.Key.Key_Left, Qt.Key.Key_Backspace)
IDLE_MS = 2500  # the pointer and the bar go away after this long without mouse movement (while playing)
HINT_MS = 3500  # the keys are listed for this long when full screen starts
POLL_MS = 100  # how often the pointer is looked at
BAR_HEIGHT = 96
KEYS_LEAVE = (Qt.Key.Key_Escape, Qt.Key.Key_F11)


class _CanvasGuard(QObject):
    """While presenting, the canvas only shows the picture: its tools must not select or move
    anything, so mouse and key events are taken here (a click plays or pauses, a double-click leaves)."""

    def __init__(self, presenter: Presenter) -> None:
        super().__init__(presenter)
        self.presenter = presenter

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        kind = event.type()
        if kind == QEvent.Type.MouseMove:
            self.presenter.wake()
            return True
        if kind == QEvent.Type.MouseButtonRelease:
            if self.presenter.slides_mode:
                self.presenter.next_slide()
            else:
                self.presenter.window_.toggle_play()
            return True
        if kind == QEvent.Type.MouseButtonDblClick:
            self.presenter.finish()
            return True
        if kind in (QEvent.Type.MouseButtonPress, QEvent.Type.Wheel, QEvent.Type.ContextMenu):
            return True
        if kind == QEvent.Type.KeyPress:
            self.presenter.keyPressEvent(event)  # type: ignore[arg-type]
            return True
        return False


class Presenter(QWidget):
    def __init__(self, window: MainWindow) -> None:
        # A window of its own, but owned by the editor's window: it goes with it (a parentless one was never
        # deleted, and kept the whole editor alive through ``window_``).
        super().__init__(window, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self._window = weakref.ref(window)
        self.setWindowTitle("Manim Studio - full screen")
        self.setStyleSheet("background: black;")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.active = False
        # Slides (ADR 0087): on when the project has slide stops. ``current`` is the slide shown; ``waiting`` is
        # True while it rests (or loops) on its stop, False while it plays or before it has played.
        self.slides_mode = False
        self.current = 0
        self.waiting = False
        self._saved: tuple | None = None
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self.bar = PlayerBar(self)
        self.bar.hide()
        self.hint = QLabel(HINT, self)
        self.hint.setStyleSheet(
            f"color: {theme.css(theme.THEME.text)}; background: rgba(0, 0, 0, 150); padding: 6px 12px;"
        )
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._guard = _CanvasGuard(self)
        self._idle = QTimer(self)
        self._idle.setSingleShot(True)
        self._idle.setInterval(IDLE_MS)
        self._idle.timeout.connect(self._rest)
        self._hint_timer = QTimer(self)
        self._hint_timer.setSingleShot(True)
        self._hint_timer.setInterval(HINT_MS)
        self._hint_timer.timeout.connect(self.hint.hide)
        self._poll = QTimer(self)  # the pointer over the bar's own widgets sends this window nothing
        self._poll.setInterval(POLL_MS)
        self._poll.timeout.connect(self._look_at_pointer)
        self._last_pointer = QPoint()
        self._connect(window)

    @property
    def window_(self) -> MainWindow:
        return self._window()

    def _connect(self, window: MainWindow) -> None:
        bar = self.bar
        window.playheadMoved.connect(lambda _t: self._update_time())
        window.playingChanged.connect(self._on_playing)
        window.playUntilReached.connect(self._on_stop_reached)
        bar.seekRequested.connect(window.seek)
        bar.playToggled.connect(window.toggle_play)
        bar.skipRequested.connect(self._skip)
        bar.startRequested.connect(lambda: window.seek(0.0))
        bar.endRequested.connect(self._to_end)
        bar.loopToggled.connect(self._set_loop)
        bar.speedChanged.connect(window.set_play_speed)
        bar.volumeChanged.connect(self._set_volume)
        bar.muteToggled.connect(self._set_muted)
        bar.leaveRequested.connect(self.finish)

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
        self.slides_mode = bool(slides.stops(window.project))
        self.hint.setText(SLIDES_HINT if self.slides_mode else HINT)
        self._show_state()
        if self.slides_mode:
            self.first_slide()
        else:
            self.bar.set_slide(None)
        self.showFullScreen()
        canvas.set_view(viewport.View())  # Fit: the whole frame on the screen
        self.setFocus()
        self.activateWindow()
        self._place()
        self._update_time()
        self.hint.show()
        self._hint_timer.start()
        self._poll.start()
        self._last_pointer = QCursor.pos()
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
        if self.slides_mode:  # a talk left half way leaves nothing playing or looping in the editor
            window.pause()
            self.slides_mode = self.waiting = False
        self._idle.stop()
        self._poll.stop()
        self._hint_timer.stop()
        canvas.removeEventFilter(self._guard)
        canvas.unsetCursor()
        self.unsetCursor()
        self._layout.removeWidget(canvas)
        window.stage.layout().insertWidget(1, canvas, 1)
        canvas.setFocusPolicy(focus)
        canvas.presenting = False
        canvas.set_overlays(overlays)
        canvas.set_view(view)
        self.hide()
        window.refresh()

    def _show_state(self) -> None:
        """Bring the bar up to date with the project and the playback."""
        window = self.window_
        project = window.project
        self.bar.set_title(window.path.stem if window.path is not None else "Untitled")
        has_sound = bool(project is not None and project.audio and window.audio_player is not None)
        self.bar.set_audio_available(has_sound)
        self.bar.set_speed_available(not has_sound)
        self.bar.set_speed(1.0 if has_sound else window.play_speed)
        self.bar.set_loop(window.loop_playback)
        player = window.audio_player
        self.bar.set_volume(getattr(player, "volume", 1.0), getattr(player, "muted", False))
        self.bar.set_playing(window.play_timer.isActive())

    # -- the bar and the pointer ---------------------------------------------------------------

    def wake(self) -> None:
        """The mouse moved: the bar and the pointer show, and go again if it rests while playing."""
        self.unsetCursor()
        self.window_.canvas.unsetCursor()
        self.bar.show()
        self.bar.raise_()
        self._idle.start()

    def _rest(self) -> None:
        """Nothing moved: hide the bar and the pointer - unless it is paused or the pointer is on the bar."""
        if not self.active:
            return
        if not self.window_.play_timer.isActive() or self.bar.contains_global(QCursor.pos()):
            self._idle.start()
            return
        blank = QCursor(Qt.CursorShape.BlankCursor)
        self.setCursor(blank)
        self.window_.canvas.setCursor(blank)
        self.bar.hide()

    def _look_at_pointer(self) -> None:
        pointer = QCursor.pos()
        if pointer != self._last_pointer:
            self._last_pointer = pointer
            self.wake()

    def _place(self) -> None:
        width, height = self.width(), self.height()
        self.bar.setGeometry(0, height - BAR_HEIGHT, width, BAR_HEIGHT)
        self.hint.adjustSize()
        self.hint.move(QPoint((width - self.hint.width()) // 2, 24))
        self.bar.raise_()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place()

    # -- following and driving the playback -------------------------------------------------------

    def _update_time(self) -> None:
        project = self.window_.project
        if project is not None and self.active:
            self.bar.set_time(self.window_.t, project.canvas.duration)

    def _on_playing(self, playing: bool) -> None:
        self.bar.set_playing(playing)
        if self.active:
            self.wake()

    def _skip(self, seconds: float) -> None:
        window = self.window_
        if window.project is not None:
            window.seek(max(0.0, min(window.project.canvas.duration, window.t + seconds)))

    def _to_end(self) -> None:
        if self.window_.project is not None:
            self.window_.seek(self.window_.project.canvas.duration)

    def _set_loop(self, on: bool) -> None:
        self.window_.loop_playback = on

    def _set_volume(self, volume: float) -> None:
        player = self.window_.audio_player
        if player is not None:
            player.set_volume(volume)
            self.bar.set_volume(volume, player.muted)

    def _set_muted(self, muted: bool) -> None:
        player = self.window_.audio_player
        if player is not None:
            player.set_muted(muted)

    # -- slides (ADR 0087) ---------------------------------------------------------------------

    def _slides(self) -> list[slides.Slide]:
        return slides.windows(self.window_.project)

    def _show_slide_number(self) -> None:
        self.bar.set_slide(f"Slide {self.current + 1} of {len(self._slides())}")

    def _playing_a_slide(self) -> bool:
        window = self.window_
        return window.play_timer.isActive() and window.play_loop is None

    def first_slide(self) -> None:
        """The start of the talk: the first frame, paused (a title slide waits on it)."""
        first = self._slides()[0]
        if first.stop is not None and first.frames == 1:
            self._wait_at(0)
            return
        window = self.window_
        window.pause()
        window.seek(first.start)
        self.current, self.waiting = 0, False
        self._show_slide_number()

    def last_slide(self) -> None:
        """The end of the talk: the last slide, done."""
        self._wait_at(len(self._slides()) - 1)

    def next_slide(self) -> None:
        """Click, Right, Page Down, Space: finish the slide playing, or play the next one."""
        found = self._slides()
        if self._playing_a_slide():
            self._wait_at(self.current)
        elif not self.waiting:  # before it has played (the start, or the bar moved the playhead)
            here = slides.slide_at(self.window_.project, self.window_.t)
            self._play(here.index, self.window_.t)
        elif self.current + 1 < len(found):
            self._play(self.current + 1, found[self.current + 1].start)

    def previous_slide(self) -> None:
        """Left, Page Up: the stop before this slide, paused (before the first: the start)."""
        if self.current == 0:
            self.first_slide()
        else:
            self._wait_at(self.current - 1, loop=False)

    def _play(self, index: int, start: float) -> None:
        window = self.window_
        slide = self._slides()[index]
        window.pause()
        window.seek(start)
        self.current, self.waiting = index, False
        window.play_until = slide.stop_time
        window.play()
        self._show_slide_number()

    def _wait_at(self, index: int, loop: bool = True) -> None:
        """Rest on slide ``index``'s stop; a looping stop goes round its last moment silently."""
        window = self.window_
        slide = self._slides()[index]
        window.pause()
        window.seek(slide.stop_time)
        self.current, self.waiting = index, True
        frames = slides.loop_window(slide) if loop else None
        if frames is not None and frames[1] - frames[0] > 1:
            window.play_silent_loop(frames[0] / slide.fps, (frames[1] - 1) / slide.fps)
        self._show_slide_number()

    def _on_stop_reached(self) -> None:
        if self.active and self.slides_mode:
            self._wait_at(self.current)

    # -- keys ---------------------------------------------------------------------------------

    def _slide_key(self, event: QKeyEvent) -> bool:
        """Present mode's keys; False for a key it leaves to the player's own."""
        key = event.key()
        shift = event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        if shift and key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            self.window_.step(-1 if key == Qt.Key.Key_Left else 1)
            self.waiting = False
        elif key in KEYS_NEXT:
            self.next_slide()
        elif key in KEYS_PREVIOUS:
            self.previous_slide()
        elif key == Qt.Key.Key_Home:
            self.first_slide()
        elif key == Qt.Key.Key_End:
            self.last_slide()
        else:
            return False
        return True

    def keyPressEvent(self, event: QKeyEvent) -> None:
        window = self.window_
        key = event.key()
        step = 10 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
        player = window.audio_player
        self.wake()
        if key in KEYS_LEAVE:
            self.finish()
        elif self.slides_mode and self._slide_key(event):
            return
        elif key == Qt.Key.Key_Space:
            window.toggle_play()
        elif key == Qt.Key.Key_Left:
            window.step(-step)
        elif key == Qt.Key.Key_Right:
            window.step(step)
        elif key == Qt.Key.Key_Home:
            window.seek(0.0)
        elif key == Qt.Key.Key_End:
            self._to_end()
        elif key == Qt.Key.Key_L:
            self.bar.loop_button.toggle()
        elif key == Qt.Key.Key_M and player is not None and self.bar.mute_button.isEnabled():
            self.bar.mute_button.toggle()
        elif key in (Qt.Key.Key_Up, Qt.Key.Key_Down) and player is not None and self.bar.volume.isEnabled():
            delta = 5 if key == Qt.Key.Key_Up else -5
            self.bar.volume.setValue(max(0, min(100, self.bar.volume.value() + delta)))
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        self.finish()
        super().closeEvent(event)
