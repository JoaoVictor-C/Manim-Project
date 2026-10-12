"""The Deliver page's render queue (P6b.5, ADR 0042): jobs and their states, without Qt.

A job holds the project as it was when it was added (documents replace their project on
every edit, so this is a reference), its render options, its output path and whether code
layers may run. ``RenderQueue`` only decides *which* job is next and what state each is in;
the page runs the job (an ``ExportJob``, one at a time) and reports back.

States: ``queued`` -> ``rendering`` -> ``done`` | ``failed`` | ``cancelled`` (a queued job can
also be cancelled). ``start()`` makes the queue run its queued jobs in order; ``advance()``
returns the next job to run, or None when one is rendering or nothing is left.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from ..core.schema import Project
from ..render.options import RenderOptions, apply_options, frame_window


class Status(StrEnum):
    QUEUED = "queued"
    RENDERING = "rendering"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


FINISHED = (Status.DONE, Status.FAILED, Status.CANCELLED)


@dataclass
class QueueJob:
    id: int
    project: Project  # as it was when the job was added
    options: RenderOptions
    output: Path
    trust: bool = False  # may code layers run? Fixed when the job is added, like the project
    status: Status = Status.QUEUED
    frame: int = 0
    total: int = 0
    message: str = ""  # why it failed, or a warning from a finished export
    result: Path | None = None  # where the video is, once done
    elapsed: float = 0.0

    @property
    def finished(self) -> bool:
        return self.status in FINISHED

    @property
    def percent(self) -> int:
        return round(100 * self.frame / self.total) if self.total else 0

    @property
    def summary(self) -> str:
        """'1920x1080 30 fps, 0.0-2.5 s' - what the job renders, from its own snapshot."""
        canvas = apply_options(self.project, self.options).canvas
        first, last = frame_window(canvas, self.options)
        text = f"{canvas.width_px}x{canvas.height_px} {canvas.fps} fps"
        return f"{text}, {first / canvas.fps:.2f}-{last / canvas.fps:.2f} s"


def unique_output(output: Path, taken: set[Path]) -> Path:
    """``output``, or ``<stem> (2)<suffix>`` (3, ...) when a pending job already writes there."""
    taken = {Path(str(p).lower()) for p in taken}  # Windows paths compare without case
    if Path(str(output).lower()) not in taken:
        return output
    n = 2
    while Path(str(output.with_name(f"{output.stem} ({n}){output.suffix}")).lower()) in taken:
        n += 1
    return output.with_name(f"{output.stem} ({n}){output.suffix}")


@dataclass
class RenderQueue:
    jobs: list[QueueJob] = field(default_factory=list)
    active: bool = False  # Start was pressed and queued jobs remain
    _next_id: int = 1

    def add(self, project: Project, options: RenderOptions, output: Path, trust: bool = False) -> QueueJob:
        """Queue an export. A pending job with the same output path makes this one ``name (2).mp4``."""
        output = Path(output)
        if output.suffix.lower() != ".mp4":
            output = output.with_suffix(".mp4")
        pending = {job.output for job in self.jobs if not job.finished}
        job = QueueJob(self._next_id, project, options, unique_output(output, pending), trust)
        self._next_id += 1
        self.jobs.append(job)
        return job

    def get(self, job_id: int) -> QueueJob | None:
        return next((job for job in self.jobs if job.id == job_id), None)

    @property
    def current(self) -> QueueJob | None:
        return next((job for job in self.jobs if job.status is Status.RENDERING), None)

    @property
    def queued(self) -> list[QueueJob]:
        return [job for job in self.jobs if job.status is Status.QUEUED]

    @property
    def busy(self) -> bool:
        return self.current is not None

    # -- running ---------------------------------------------------------------------

    def start(self) -> QueueJob | None:
        """Run the queued jobs in order; returns the job to launch now (None if one is rendering)."""
        self.active = bool(self.queued) or self.busy
        return self.advance()

    def advance(self) -> QueueJob | None:
        """The next queued job, marked rendering - or None (one is rendering, not started, or no more)."""
        if not self.active or self.busy:
            return None
        waiting = self.queued
        if not waiting:
            self.active = False
            return None
        job = waiting[0]
        job.status, job.frame, job.total, job.message = Status.RENDERING, 0, 0, ""
        return job

    def progress(self, job: QueueJob, frame: int, total: int) -> None:
        if job.status is Status.RENDERING:
            job.frame, job.total = frame, total

    def finish(self, job: QueueJob, path: Path, warning: str = "") -> None:
        if job.status is Status.RENDERING:
            job.status, job.result, job.message = Status.DONE, Path(path), warning
            job.frame = job.total = max(job.total, 1)

    def fail(self, job: QueueJob, message: str) -> None:
        if job.status is Status.RENDERING:
            job.status, job.message = Status.FAILED, message

    def cancel(self, job: QueueJob) -> bool:
        """Cancel a queued or rendering job; True if it was rendering (its process must be stopped)."""
        was_rendering = job.status is Status.RENDERING
        if job.status in (Status.QUEUED, Status.RENDERING):
            job.status, job.message = Status.CANCELLED, ""
        return was_rendering

    def cancel_all(self) -> bool:
        """Cancel everything pending and stop the queue; True if a job was rendering."""
        rendering = False
        for job in list(self.jobs):
            rendering |= self.cancel(job)
        self.active = False
        return rendering

    # -- editing the list ---------------------------------------------------------------

    def remove(self, job: QueueJob) -> bool:
        """Take a job off the list; not while it renders (cancel it first)."""
        if job.status is Status.RENDERING or job not in self.jobs:
            return False
        self.jobs.remove(job)
        return True

    def clear_finished(self) -> int:
        kept = [job for job in self.jobs if not job.finished]
        removed = len(self.jobs) - len(kept)
        self.jobs[:] = kept
        return removed
