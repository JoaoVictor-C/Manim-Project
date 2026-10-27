"""Run on a helper (ADR 0058): import it once in a throwaway process and report what happened.

``HelperChecker.start`` launches ``python -m manim_studio.processes.helper_check`` with the project's helpers,
and ``finished(name, code, result)`` reports the result message (see ``helper_check``) - or a timeout
or a process that could not start, worded the same way. A newer check of the same helper replaces a
running one. The helper's code never runs in the editor's own process.
"""

from __future__ import annotations

import contextlib
import json
import sys
from dataclasses import dataclass

from PySide6.QtCore import QElapsedTimer, QObject, QProcess, QTimer, Signal

from ...logging_config import get_logger
from . import children
from .code_render import _release

log = get_logger(__name__)

TIMEOUT_S = 30.0  # as long as a Python object's build may take


@dataclass
class _Run:
    name: str
    code: str
    process: QProcess
    timer: QTimer
    buffer: bytes = b""
    result: dict | None = None
    done: bool = False


class HelperChecker(QObject):
    finished = Signal(str, str, dict)  # helper name, the code that was checked, the result message

    def __init__(
        self,
        *,
        program: str = sys.executable,
        args: list[str] | None = None,
        timeout_s: float = TIMEOUT_S,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.program = program
        self.args = args if args is not None else ["-m", "manim_studio.processes.helper_check"]
        self.timeout_s = timeout_s
        self._runs: dict[str, _Run] = {}

    def running(self, name: str) -> str | None:
        """The code of helper ``name`` being checked now, or None."""
        run = self._runs.get(name)
        return None if run is None else run.code

    @property
    def busy(self) -> bool:
        return bool(self._runs)

    def start(self, name: str, code: str, sources: dict[str, str], trusted: list[str]) -> None:
        """Import helper ``name`` (whose code is ``code``) with every helper in ``sources`` importable
        and those in ``trusted`` allowed to run."""
        self.cancel(name)
        process = QProcess()  # no Qt parent: _release owns its teardown (as the code renderer's)
        process.setProgram(self.program)
        process.setArguments(self.args)
        process.setProcessEnvironment(children.environment(PYTHONUNBUFFERED="1"))
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(int(self.timeout_s * 1000))
        run = _Run(name, code, process, timer)
        self._runs[name] = run
        process.readyReadStandardOutput.connect(lambda: self._read(run))
        process.readyReadStandardError.connect(lambda: self._log_stderr(run))
        process.finished.connect(lambda *_: self._on_exit(run))
        process.errorOccurred.connect(lambda error: self._on_error(run, error))
        timer.timeout.connect(lambda: self._on_timeout(run))
        job = {"name": name, "helpers": sorted(sources.items()), "trusted": sorted(trusted)}
        children.start(process)
        process.write((json.dumps(job) + "\n").encode("utf-8"))
        process.closeWriteChannel()
        timer.start()

    def cancel(self, name: str) -> None:
        """Forget a running check of ``name`` (its process is stopped; nothing is reported)."""
        run = self._runs.pop(name, None)
        if run is not None:
            run.done = True
            self._stop(run)

    def stop(self) -> None:
        for name in list(self._runs):
            self.cancel(name)

    def wait(self, timeout_ms: int = 30000) -> bool:
        """Block until every check has reported (tests); False when one is still running."""
        from PySide6.QtWidgets import QApplication

        clock = QElapsedTimer()
        clock.start()
        while self._runs and clock.elapsed() < timeout_ms:
            for run in list(self._runs.values()):
                run.process.waitForFinished(50)
            QApplication.processEvents()
        return not self._runs

    # -- internals ------------------------------------------------------------------------------

    def _read(self, run: _Run) -> None:
        run.buffer += bytes(run.process.readAllStandardOutput().data())
        *lines, run.buffer = run.buffer.split(b"\n")
        for raw in lines:
            with contextlib.suppress(ValueError, UnicodeDecodeError):
                message = json.loads(raw.decode("utf-8").strip() or "null")
                if isinstance(message, dict) and "ok" in message:
                    run.result = message

    def _log_stderr(self, run: _Run) -> None:
        text = bytes(run.process.readAllStandardError().data()).decode("utf-8", errors="replace")
        for line in text.splitlines():
            if line.strip():
                log.debug("helper check: %s", line)

    def _on_exit(self, run: _Run) -> None:
        if run.done:
            return
        self._read(run)
        if run.buffer.strip():
            run.buffer += b"\n"
            self._read(run)
        result = run.result or {
            "ok": False,
            "error": "the check stopped before it could say anything (see the log)",
            "type": "",
            "where": "code",
        }
        self._finish(run, result)

    def _on_error(self, run: _Run, error) -> None:
        if run.done or error != QProcess.ProcessError.FailedToStart:
            return
        self._finish(
            run,
            {"ok": False, "error": "could not start Python to test the helper", "type": "", "where": "code"},
        )

    def _on_timeout(self, run: _Run) -> None:
        if run.done:
            return
        self._finish(
            run,
            {
                "ok": False,
                "error": f"importing it took longer than {self.timeout_s:g} s",
                "type": "TimeoutError",
                "where": "code",
            },
        )

    def _finish(self, run: _Run, result: dict) -> None:
        run.done = True
        if self._runs.get(run.name) is run:
            del self._runs[run.name]
        self._stop(run)
        self.finished.emit(run.name, run.code, result)

    def _stop(self, run: _Run) -> None:
        run.timer.stop()
        run.timer.deleteLater()
        process = run.process
        if process.state() != QProcess.ProcessState.NotRunning:
            process.kill()
            process.waitForFinished(2000)
        _release(process)
