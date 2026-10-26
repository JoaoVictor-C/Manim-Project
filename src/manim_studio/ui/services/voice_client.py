"""The editor's side of the voice helper (ADR 0060): list a provider's voices, speak texts, cancel.

Each request starts ``python -m manim_studio.processes.voice`` with ONE job (see that module), reads its
answers as they come and ends it. A provider's code never runs in the editor; a request that goes quiet
for ``timeout_s`` (counted from the last answer) is stopped and reported. Only one ``speak`` runs at a
time (a newer one is refused: ``speak`` returns False); lists of different providers may run together.
"""

from __future__ import annotations

import contextlib
import json
import sys
from dataclasses import dataclass, field

from PySide6.QtCore import QElapsedTimer, QObject, QProcess, QProcessEnvironment, QTimer, Signal

from ...logging_config import get_logger
from .code_render import _release

log = get_logger(__name__)

SPEAK_TIMEOUT_S = 180.0  # without any answer: one text, including the helper's own retries
LIST_TIMEOUT_S = 60.0


@dataclass
class _Run:
    kind: str  # "voices" | "speak"
    provider: str
    process: QProcess
    timer: QTimer
    buffer: bytes = b""
    pending: list[str] = field(default_factory=list)  # ids of texts not answered yet
    done: bool = False  # reported (or cancelled): ignore whatever the process still does
    finished_cleanly: bool = False  # the helper said {"done": true}
    answered_list: bool = False


class VoiceClient(QObject):
    voicesListed = Signal(
        str, dict
    )  # provider, the helper's answer: {"ok": true, "voices": [...]} or an error
    spoken = Signal(str, bool, str)  # text id, spoken?, the error
    speakFinished = Signal(bool, str)  # every text answered?, why not ("cancelled", "timeout", ...)

    def __init__(
        self,
        *,
        program: str = sys.executable,
        args: list[str] | None = None,
        speak_timeout_s: float = SPEAK_TIMEOUT_S,
        list_timeout_s: float = LIST_TIMEOUT_S,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.program = program
        self.args = args if args is not None else ["-m", "manim_studio.processes.voice"]
        self.speak_timeout_s = speak_timeout_s
        self.list_timeout_s = list_timeout_s
        self._speaking: _Run | None = None
        self._listing: dict[str, _Run] = {}

    @property
    def busy(self) -> bool:
        return self._speaking is not None or bool(self._listing)

    @property
    def speaking(self) -> bool:
        return self._speaking is not None

    def list_voices(self, provider: str) -> None:
        """Ask for ``provider``'s voices; ``voicesListed`` answers (a newer request replaces one running)."""
        old = self._listing.pop(provider, None)
        if old is not None:
            old.done = True
            self._stop(old)
        self._start("voices", provider, {"op": "voices", "provider": provider})

    def speak(self, provider: str, items: list[dict]) -> bool:
        """Speak ``items`` (``{"id", "text", "voice", "rate", "out"}``); ``spoken`` answers each,
        ``speakFinished`` the whole request. False when one is running already."""
        if self._speaking is not None:
            return False
        self._start(
            "speak",
            provider,
            {"op": "speak", "provider": provider, "items": items},
            pending=[item["id"] for item in items],
        )
        return True

    def cancel(self) -> None:
        """Stop speaking: the running helper is killed, files it did not finish are not kept."""
        run = self._speaking
        if run is not None and not run.done:
            self._finish_speak(run, False, "cancelled")

    def stop(self) -> None:
        self.cancel()
        for run in list(self._listing.values()):
            run.done = True
            self._stop(run)
        self._listing.clear()

    def wait(self, timeout_ms: int = 60000) -> bool:
        """Block until every request has reported (tests); False when one is still running."""
        from PySide6.QtWidgets import QApplication

        clock = QElapsedTimer()
        clock.start()
        while self.busy and clock.elapsed() < timeout_ms:
            runs = [*self._listing.values(), *([self._speaking] if self._speaking else [])]
            for run in runs:
                run.process.waitForFinished(50)
            QApplication.processEvents()
        return not self.busy

    # -- internals ------------------------------------------------------------------------------

    def _start(self, kind: str, provider: str, job: dict, pending: list[str] | None = None) -> None:
        process = QProcess()  # no Qt parent: _release owns its teardown
        process.setProgram(self.program)
        process.setArguments(self.args)
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONUTF8", "1")
        env.insert("PYTHONUNBUFFERED", "1")
        process.setProcessEnvironment(env)
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(int((self.speak_timeout_s if kind == "speak" else self.list_timeout_s) * 1000))
        run = _Run(kind, provider, process, timer, pending=pending or [])
        if kind == "speak":  # registered before the process starts: it may fail to start at once
            self._speaking = run
        else:
            self._listing[provider] = run
        process.readyReadStandardOutput.connect(lambda: self._read(run))
        process.readyReadStandardError.connect(lambda: self._log_stderr(run))
        process.finished.connect(lambda *_: self._on_exit(run))
        process.errorOccurred.connect(lambda error: self._on_error(run, error))
        timer.timeout.connect(lambda: self._on_timeout(run))
        process.start()
        process.write((json.dumps(job) + "\n").encode("utf-8"))
        process.closeWriteChannel()
        timer.start()

    def _read(self, run: _Run) -> None:
        if run.done:
            return
        run.buffer += bytes(run.process.readAllStandardOutput().data())
        *lines, run.buffer = run.buffer.split(b"\n")
        for raw in lines:
            with contextlib.suppress(ValueError, UnicodeDecodeError):
                message = json.loads(raw.decode("utf-8").strip() or "null")
                if isinstance(message, dict):
                    self._on_message(run, message)
                    if run.done:
                        return

    def _on_message(self, run: _Run, message: dict) -> None:
        run.timer.start()  # an answer: the helper is alive
        if run.kind == "voices":
            if "ok" in message:
                run.answered_list = True
                self._finish_list(run, message)
            return
        if "id" in message and "ok" in message:
            if message["id"] in run.pending:
                run.pending.remove(message["id"])
            self.spoken.emit(str(message["id"]), bool(message["ok"]), str(message.get("error", "")))
        elif message.get("done"):
            run.finished_cleanly = True
            self._finish_speak(
                run, not run.pending, "" if not run.pending else "the helper skipped some texts"
            )
        elif message.get("ok") is False:  # the whole request is refused (an unknown or unavailable provider)
            self._refuse_speak(run, str(message.get("error", "the voice helper refused the request")))

    def _refuse_speak(self, run: _Run, error: str) -> None:
        for item_id in list(run.pending):
            run.pending.remove(item_id)
            self.spoken.emit(item_id, False, error)
        self._finish_speak(run, False, error)

    def _log_stderr(self, run: _Run) -> None:
        text = bytes(run.process.readAllStandardError().data()).decode("utf-8", errors="replace")
        for line in text.splitlines():
            if line.strip():
                log.debug("voice helper: %s", line)

    def _on_exit(self, run: _Run) -> None:
        if run.done:
            return
        self._read(run)
        if run.done:
            return
        why = "the voice helper stopped before it finished (see the log)"
        if run.kind == "voices":
            self._finish_list(run, {"ok": False, "error": why})
        else:
            self._refuse_speak(run, why)

    def _on_error(self, run: _Run, error) -> None:
        if run.done or error != QProcess.ProcessError.FailedToStart:
            return
        why = "could not start Python for the voice helper"
        if run.kind == "voices":
            self._finish_list(run, {"ok": False, "error": why})
        else:
            self._refuse_speak(run, why)

    def _on_timeout(self, run: _Run) -> None:
        if run.done:
            return
        why = f"the voice helper gave no answer for {run.timer.interval() // 1000} s"
        if run.kind == "voices":
            self._finish_list(run, {"ok": False, "error": why, "timeout": True})
        else:
            self._refuse_speak(run, why)

    def _finish_list(self, run: _Run, answer: dict) -> None:
        run.done = True
        if self._listing.get(run.provider) is run:
            del self._listing[run.provider]
        self._stop(run)
        self.voicesListed.emit(run.provider, answer)

    def _finish_speak(self, run: _Run, completed: bool, why: str) -> None:
        run.done = True
        if self._speaking is run:
            self._speaking = None
        self._stop(run)
        self.speakFinished.emit(completed, why)

    def _stop(self, run: _Run) -> None:
        run.timer.stop()
        run.timer.deleteLater()
        process = run.process
        if process.state() != QProcess.ProcessState.NotRunning:
            process.kill()
            process.waitForFinished(2000)
        _release(process)
