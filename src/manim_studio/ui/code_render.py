"""Rendering code layers from the editor (P2d.3, ADR 0019).

``CodeRenderService`` keeps every code layer of the current project rendered:
``sync(project)`` after each change compares each layer's cache key with the
frame cache and queues what is missing. Code runs only in single-use **warm
spares** — ``python -m manim_studio.code_runner`` processes started in advance,
so the Manim import (6-8 s here, B30) is paid before a job arrives. A spare
takes one job, renders it into the cache and exits; a new spare is started in
its place. Rules:

* spares run only while the project has code layers, at most ``max_spares``
  alive (one idle spare is kept ready, a second starts when jobs wait);
* one job per layer: newer code replaces a queued job, and kills a running one
  (single-use processes make killing the normal way to cancel);
* only trusted code is queued; other layers report ``untrusted``;
* a job that takes longer than ``timeout_s`` is killed and reported as an error;
* an error stays attached to that code until the code changes (or ``retry``).

The editor keeps showing the previous frames, or the placeholder, until a
render finishes; ``rendered(layer_id)`` then asks for a redraw.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal

from ..code_runner import Job
from ..core import error_hints, helpers
from ..core.code_cache import CodeCache
from ..core.evaluator import code_key
from ..core.schema import CODE_TYPES, Project
from ..core.trust import TrustStore, code_of
from ..logging_config import get_logger

log = get_logger(__name__)


@dataclass
class CodeStatus:
    state: str  # "ready", "queued", "rendering", "error", "untrusted"; "built": a Python object
    frames: int = 0  # rendered so far (rendering) or in the cache (ready)
    error: str = ""
    line: int | None = None
    error_type: str = ""  # the exception's class name ("NameError"); "" when unknown (P13.1)
    where: str = "code"  # "code", or "helper:<name>" when the error came from a helper (ADR 0058)
    traceback: str = ""  # the user's own frames, at most 4 KB
    helper_line: int | None = None

    @property
    def text(self) -> str:
        if self.state == "ready":
            return f"Ready - {self.frames} frames"
        if self.state == "built":  # a Python object (ADR 0051)
            return "Built - the object is on the canvas; its parameters are in Properties"
        if self.state == "queued":
            return "Waiting to render..."
        if self.state == "rendering":
            return f"Rendering... {self.frames} frames" if self.frames else "Rendering..."
        if self.state == "untrusted":
            return "Not run: this code is not trusted on this computer"
        if self.state == "cancelled":
            return "Cancelled - press Run to render it again"
        where = f"line {self.line}: " if self.line else ""
        if self.where.startswith("helper:"):
            at = f", line {self.helper_line}" if self.helper_line else ""
            where = f"helper {self.where.removeprefix('helper:')}{at}: "
        return f"Error - {where}{self.error}"


def _release(process: QProcess) -> None:
    """Detach a finished (or killed) process from Python callbacks and let Qt delete it."""
    for signal in (process.readyReadStandardOutput, process.readyReadStandardError, process.finished):
        with contextlib.suppress(RuntimeError, TypeError):  # nothing connected any more
            signal.disconnect()
    process.deleteLater()


@dataclass
class _Spare:
    process: QProcess
    ready: bool = False
    job: Job | None = None
    layer_id: str | None = None
    since: float = 0.0
    buffer: bytes = b""
    cancelled: bool = False
    frames: int = 0
    done: bool = False
    messages: list[dict] = field(default_factory=list)


class CodeRenderService(QObject):
    statusChanged = Signal(str)  # layer id
    rendered = Signal(str)  # layer id: new frames are in the cache

    def __init__(
        self,
        cache_dir: Path,
        trust: TrustStore,
        *,
        max_spares: int = 2,
        timeout_s: float = 120.0,
        program: str = sys.executable,
        args: list[str] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.cache_dir = Path(cache_dir)
        self.cache = CodeCache(self.cache_dir / "code")
        self.trust = trust
        self.max_spares = max_spares
        self.timeout_s = timeout_s
        self._program = program
        self._args = (
            args if args is not None else ["-m", "manim_studio.code_runner", "--cache-dir", str(cache_dir)]
        )
        self._spares: list[_Spare] = []
        self._queue: list[tuple[str, Job]] = []  # (layer id, job), oldest first
        self._wanted: dict[str, str] = {}  # layer id -> key it should show
        self._runnable = False  # some code layer is trusted: worth keeping a spare ready
        self._status: dict[str, CodeStatus] = {}
        self._errors: dict[str, CodeStatus] = {}  # key -> the error it produced
        self._project: Project | None = None
        self._stopped = False
        self._watchdog = QTimer(self)
        self._watchdog.setInterval(250)
        self._watchdog.timeout.connect(self._check_timeouts)

    # -- public ----------------------------------------------------------------

    def status(self, layer_id: str) -> CodeStatus | None:
        return self._status.get(layer_id)

    def sync(self, project: Project) -> None:
        """Bring renders in line with ``project`` (call after every change, undo and open)."""
        if self._stopped:
            return
        self._project = project
        wanted: dict[str, str] = {}
        jobs: dict[str, Job] = {}
        canvas = project.canvas
        sources = helpers.sources(project)  # importable by the code, those trusted only (ADR 0058)
        pairs = tuple(sorted(sources.items()))
        trusted = tuple(sorted(n for n, c in sources.items() if self.trust.is_trusted(c)))
        digest = helpers.digest(sources)
        for layer in project.layers:
            if layer.spec is None or layer.spec.type not in CODE_TYPES:
                continue
            key = code_key(project, layer, digest)
            wanted[layer.id] = key
            code = str(layer.spec.params.get("code", ""))
            jobs[layer.id] = Job(
                key, code, canvas.width_px, canvas.height_px, canvas.fps, canvas.frame_height, pairs, trusted
            )
        self._wanted = wanted
        self._runnable = any(self.trust.is_trusted(job.code) for job in jobs.values())
        for layer_id in [i for i in self._status if i not in wanted]:
            del self._status[layer_id]
        # A waiting job is replaced by today's (the same key may now trust another helper).
        self._queue = [(i, jobs[i]) for i, job in self._queue if wanted.get(i) == job.key]
        for spare in self._spares:  # a running job for code that changed or went away
            if spare.job is not None and wanted.get(spare.layer_id) != spare.job.key:
                self._cancel(spare)
        for layer_id, job in jobs.items():
            self._settle(layer_id, job)
        self._top_up()

    def retry(self, layer_id: str) -> None:
        """Render again after an error (e.g. the code imports a file that now exists)."""
        key = self._wanted.get(layer_id)
        if key is not None:
            self._errors.pop(key, None)
            if self._project is not None:
                self.sync(self._project)

    def cancel(self, layer_id: str) -> bool:
        """Stop rendering ``layer_id`` (or drop it from the queue); True when something was stopped.
        The process is killed and a warm spare replaces it; the layer shows *cancelled* until retried."""
        job = None
        for spare in self._spares:
            if (
                spare.layer_id == layer_id
                and spare.job is not None
                and not spare.done
                and not spare.cancelled
            ):
                job = spare.job
                self._cancel(spare)
        queued = [(i, j) for i, j in self._queue if i == layer_id]
        if queued:
            job = queued[0][1]
            self._queue = [(i, j) for i, j in self._queue if i != layer_id]
        if job is None:
            return False
        status = CodeStatus("cancelled")
        self._errors[job.key] = status
        self._set(layer_id, status)
        self._top_up()
        return True

    def trust_layers(self, project: Project, layer_ids: list[str]) -> None:
        """Mark these layers' code as safe to run (the user agreed) and render it. An id may be
        ``helper:<name>`` (``TrustStore.untrusted``, ADR 0058): a render that failed importing it is
        tried again."""
        self.trust.trust([code_of(project, i) for i in layer_ids])
        if any(i.startswith("helper:") for i in layer_ids):
            self._errors.clear()
        self.sync(project)

    def stop(self) -> None:
        self._stopped = True
        self._watchdog.stop()
        self._queue.clear()
        spares, self._spares = self._spares, []  # _on_exit ignores them from now on
        for spare in spares:
            self._kill(spare)
            spare.process.waitForFinished(2000)
            _release(spare.process)

    @property
    def spare_count(self) -> int:
        return len(self._spares)

    # -- scheduling ------------------------------------------------------------

    def _settle(self, layer_id: str, job: Job) -> None:
        clip = self.cache.open(job.key)
        if clip is not None:
            self._set(layer_id, CodeStatus("ready", frames=clip.frame_count))
            return
        if job.key in self._errors:
            self._set(layer_id, self._errors[job.key])
            return
        if not self.trust.is_trusted(job.code):
            self._set(layer_id, CodeStatus("untrusted"))
            return
        busy = [s for s in self._spares if s.job is not None and not s.done and not s.cancelled]
        if any(s.job.key == job.key and s.layer_id == layer_id for s in busy):
            return  # already rendering this very code
        if not any(i == layer_id for i, _ in self._queue):
            self._queue.append((layer_id, job))
            self._set(layer_id, CodeStatus("queued"))
        self._dispatch()

    def _dispatch(self) -> None:
        for spare in self._spares:
            if not self._queue:
                return
            if spare.ready and spare.job is None and not spare.cancelled:
                layer_id, job = self._queue.pop(0)
                spare.job, spare.layer_id, spare.since = job, layer_id, time.monotonic()
                spare.process.write((job.to_json() + "\n").encode("utf-8"))
                spare.process.closeWriteChannel()
                self._set(layer_id, CodeStatus("rendering"))
                log.info("rendering code layer %s (%s)", layer_id, job.key)
                self._watchdog.start()

    def _top_up(self) -> None:
        """Keep one idle spare ready while code layers exist, two when jobs wait."""
        if self._stopped or not self._runnable:
            for spare in [s for s in self._spares if s.job is None]:
                self._kill(spare)
            return
        idle = [s for s in self._spares if s.job is None and not s.cancelled]
        needed = max(1, len(self._queue)) - len(idle)
        while needed > 0 and len(self._spares) < self.max_spares:
            self._start_spare()
            needed -= 1

    def _set(self, layer_id: str, status: CodeStatus) -> None:
        if self._status.get(layer_id) != status:
            self._status[layer_id] = status
            self.statusChanged.emit(layer_id)

    # -- spares ----------------------------------------------------------------

    def _start_spare(self) -> None:
        # No Qt parent: the service may be garbage-collected right after a spare exits,
        # and a parent deleting a just-finished process aborted Qt; _release owns teardown.
        process = QProcess()
        process.setProgram(self._program)
        process.setArguments(self._args)
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONUTF8", "1")
        env.insert("PYTHONUNBUFFERED", "1")
        process.setProcessEnvironment(env)
        spare = _Spare(process)
        process.readyReadStandardOutput.connect(lambda: self._read(spare))
        process.readyReadStandardError.connect(lambda: self._log_stderr(spare))
        process.finished.connect(lambda *_: self._on_exit(spare))
        self._spares.append(spare)
        process.start()

    def _read(self, spare: _Spare) -> None:
        spare.buffer += bytes(spare.process.readAllStandardOutput().data())
        *lines, spare.buffer = spare.buffer.split(b"\n")
        for raw in lines:
            text = raw.strip()
            if text.startswith(b"{"):  # anything else is not the protocol (stray prints, logs)
                self._handle(spare, json.loads(text))

    def _handle(self, spare: _Spare, message: dict) -> None:
        if message.get("ready"):
            spare.ready = True
            self._dispatch()
            return
        if spare.job is None or spare.cancelled:
            return
        if "frame" in message:
            spare.frames = int(message["frame"])
            self._set(spare.layer_id, CodeStatus("rendering", frames=spare.frames))
        elif message.get("done"):
            spare.done = True
            self.cache.open(spare.job.key)  # pick up the finished render
            self._set(spare.layer_id, CodeStatus("ready", frames=int(message.get("frames", 0))))
            self.rendered.emit(spare.layer_id)
        elif "error" in message:
            spare.done = True
            text = str(message["error"])
            status = CodeStatus(
                "error",
                error=text,
                line=message.get("line"),
                error_type=str(message.get("type") or error_hints.split_legacy(text)[0]),
                where=str(message.get("where") or "code"),
                traceback=str(message.get("traceback") or ""),
                helper_line=message.get("helper_line"),
            )
            self._errors[spare.job.key] = status
            self._set(spare.layer_id, status)

    def _on_exit(self, spare: _Spare) -> None:
        if spare not in self._spares:
            return
        self._read(spare)  # the last lines may arrive with the exit
        self._spares.remove(spare)
        _release(spare.process)
        if spare.job is not None and not spare.done and not spare.cancelled:
            status = CodeStatus("error", error="the render process stopped unexpectedly")
            self._errors[spare.job.key] = status
            self._set(spare.layer_id, status)
        elif spare.job is None and not spare.ready and not spare.cancelled and not self._stopped:
            log.error("a code render process exited before it was ready")
            if self._project is not None:
                for layer_id in list(self._wanted):
                    if self._status.get(layer_id, CodeStatus("queued")).state == "queued":
                        self._set(layer_id, CodeStatus("error", error="the render process could not start"))
            self._queue.clear()
            self._runnable = False
            return  # do not loop on a broken interpreter
        if not self._stopped:
            self._top_up()
            self._dispatch()

    def _cancel(self, spare: _Spare) -> None:
        spare.cancelled = True
        self._kill(spare)

    def _kill(self, spare: _Spare) -> None:
        spare.cancelled = True
        if spare.process.state() != QProcess.ProcessState.NotRunning:
            spare.process.kill()

    def _check_timeouts(self) -> None:
        busy = [s for s in self._spares if s.job is not None and not s.done and not s.cancelled]
        if not busy:
            self._watchdog.stop()
            return
        for spare in busy:
            if time.monotonic() - spare.since > self.timeout_s:
                status = CodeStatus(
                    "error",
                    error=f"rendering took longer than {self.timeout_s:g} s",
                    error_type="TimeoutError",
                )
                self._errors[spare.job.key] = status
                self._set(spare.layer_id, status)
                self._cancel(spare)

    def _log_stderr(self, spare: _Spare) -> None:
        text = bytes(spare.process.readAllStandardError().data()).decode("utf-8", errors="replace")
        for line in text.splitlines():
            if line.strip():
                log.debug("code runner: %s", line)


class NoCodeRenderer(QObject):
    """Renders nothing (``MANIM_STUDIO_CODE=0``: tests, debugging): code layers keep their cache."""

    statusChanged = Signal(str)
    rendered = Signal(str)

    def __init__(self, cache_dir: Path, trust: TrustStore, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.cache = CodeCache(Path(cache_dir) / "code")
        self.trust = trust

    def status(self, layer_id: str) -> CodeStatus | None:
        return None

    def sync(self, project: Project) -> None:
        pass

    def retry(self, layer_id: str) -> None:
        pass

    def cancel(self, layer_id: str) -> bool:
        return False

    def trust_layers(self, project: Project, layer_ids: list[str]) -> None:
        self.trust.trust([code_of(project, i) for i in layer_ids])

    def stop(self) -> None:
        pass


def make_code_renderer(cache_dir: Path, trust: TrustStore, parent: QObject | None = None):
    """The real renderer, or none when ``MANIM_STUDIO_CODE=0``."""
    if os.environ.get("MANIM_STUDIO_CODE") == "0":
        return NoCodeRenderer(cache_dir, trust, parent)
    return CodeRenderService(cache_dir, trust, parent=parent)
