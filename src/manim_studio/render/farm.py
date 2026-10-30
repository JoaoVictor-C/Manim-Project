"""Frames drawn by several processes at once and handed back in order (ADR 0065).

A frame is drawn by Python and Cairo on one processor core, and takes the same time whatever else the machine
is doing, so an export that draws its frames one after another uses one core of twelve. ``Farm`` starts a few
render processes (``processes.frame_worker``), each of which draws whole frames into a shared ring of memory,
and gives them back in frame order for the encoder - which is a different piece of hardware (the graphics
card, see ``encoders``) or at least other cores. Frames are independent: the evaluator answers any time
with the same picture whatever it drew before (ADR 0013), so who draws which frame does not matter.

The ring is a fixed number of frame-sized slots in one shared-memory block, so memory is bounded however long
the export is: a worker takes a free slot with each frame it is given, the farm frees it when the encoder is
done with the frame. Frames are given out in order, so the oldest frame not yet encoded is always one a worker
holds and the ring cannot fill with later frames and stop.

A render process that stops, or that fails on a frame, ends the farm with ``FarmError`` and the caller goes
on
by itself from ``next_frame``: if the frame really cannot be drawn, it fails there with its own error.
"""

from __future__ import annotations

import collections
import contextlib
import json
import queue
import subprocess
import sys
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from multiprocessing import shared_memory
from pathlib import Path

import numpy as np

from .. import lifeline
from ..core.model.schema import Project
from ..logging_config import get_logger
from . import resources

log = get_logger(__name__)

MIN_FRAMES = 90  # fewer frames than this: starting the processes (seconds, Manim loads in each) costs more
MIN_SECONDS = 8.0  # an export estimated to draw for less than this on one core is left to this process
MAX_AUTO = 6  # processes "auto" starts at most
RING_BYTES = 256 * 2**20  # the frames in flight, in all
WORKER_BYTES = (
    400 * 2**20
)  # what one render process is expected to hold, to count how many fit in free memory
CHUNK = 8  # frames given to a worker at once (consecutive: the evaluator's caches serve the next one)
DEPTH = 2  # chunks a worker holds at once, so it never waits for the next
MODULE = "manim_studio.processes.frame_worker"
GRACE_SECONDS = 5.0  # how long finished workers get to exit by themselves


class FarmError(RuntimeError):
    """A render process stopped or failed; the frames handed back so far are good."""


def plan(requested: int | None, frames: int, frame_bytes: int) -> int:
    """How many render processes an export of ``frames`` frames uses (1: the exporting process draws).

    ``requested`` None chooses from the processor cores, the memory free now and the size of the export;
    a number is honoured, except that the ring must hold two frames for each process and each must have two
    frames to draw."""
    if requested == 1 or frames < 2:
        return 1
    if requested is None:
        if frames < MIN_FRAMES:
            return 1
        wanted = min(MAX_AUTO, max(1, resources.cores() // 2))
        wanted = min(wanted, int(resources.available_memory() * 0.5 // WORKER_BYTES))
    else:
        wanted = requested
    wanted = min(wanted, RING_BYTES // frame_bytes // 2, frames // 2)
    return wanted if wanted >= 2 else 1


@dataclass
class _Worker:
    index: int
    process: subprocess.Popen
    ready: bool = False
    load: int = 0  # frames given and not yet drawn
    drawn: int = 0
    stderr: collections.deque = field(default_factory=lambda: collections.deque(maxlen=30))


class Farm:
    def __init__(
        self,
        project: Project,
        first: int,
        last: int,
        workers: int,
        cache_dir: Path,
        *,
        trust_code: bool = False,
    ) -> None:
        """Start ``workers`` render processes for frames ``[first, last)`` of ``project`` (sized)."""
        canvas = project.canvas
        self.first, self.last = first, last
        self.next_frame = first  # the next frame to hand back; where the caller resumes after FarmError
        self._cursor = first  # the next frame to give to a worker
        frame_bytes = canvas.width_px * canvas.height_px * 4
        self._slots = max(workers * 2, min(workers * CHUNK * DEPTH, RING_BYTES // frame_bytes))
        self._chunk = max(1, min(CHUNK, self._slots // (workers * DEPTH)))
        self._ring: shared_memory.SharedMemory | None = shared_memory.SharedMemory(
            create=True, size=self._slots * frame_bytes
        )
        shape = (canvas.height_px, canvas.width_px, 4)
        self._views = [
            np.ndarray(shape, np.uint8, buffer=self._ring.buf, offset=k * frame_bytes)
            for k in range(self._slots)
        ]
        self._free = collections.deque(range(self._slots))
        self._slot_of: dict[int, int] = {}  # frame -> its slot, from the moment it is given to a worker
        self._done: set[int] = set()  # frames drawn and waiting for their turn
        self._events: queue.Queue = queue.Queue()
        self._workers: list[_Worker] = []
        hello = json.dumps(
            {
                "project": project.model_dump_json(by_alias=True),
                "cache_dir": str(cache_dir),
                "ring": self._ring.name,
                "slots": self._slots,
                "trust": trust_code,
            }
        )
        try:
            for index in range(workers):
                self._workers.append(self._spawn(index, hello))
        except BaseException:
            self.close()
            raise
        log.info(
            "farm: %d render processes, %d frame slots of %d KB, chunks of %d",
            workers,
            self._slots,
            frame_bytes // 1024,
            self._chunk,
        )

    # -- the frames -------------------------------------------------------------

    def frames(self) -> Iterator[tuple[int, np.ndarray]]:
        """``(frame, RGBA array)`` in order; the array is valid until the next one is asked for."""
        while self.next_frame < self.last:
            self._dispatch()
            while self.next_frame in self._done:
                self._done.discard(self.next_frame)
                slot = self._slot_of.pop(self.next_frame)
                yield self.next_frame, self._views[slot]
                self._free.append(slot)
                self.next_frame += 1
                self._dispatch()
            if self.next_frame < self.last:
                self._wait()

    def _dispatch(self) -> None:
        """Give the next frames to the workers that have room, while there are free slots."""
        while self._cursor < self.last and self._free:
            room = [w for w in self._workers if w.ready and w.load <= self._chunk * (DEPTH - 1)]
            if not room:
                return
            worker = min(room, key=lambda w: w.load)
            count = min(self._chunk, self.last - self._cursor, len(self._free))
            task = []
            for _ in range(count):
                slot = self._free.popleft()
                task.append([self._cursor, slot])
                self._slot_of[self._cursor] = slot
                self._cursor += 1
            worker.load += count
            try:
                worker.process.stdin.write((json.dumps({"frames": task}) + "\n").encode())
                worker.process.stdin.flush()
            except OSError as exc:
                raise FarmError(self._why(worker, f"cannot be written to ({exc})")) from exc

    def _wait(self) -> None:
        """Take one event from a worker: it is ready, it drew a frame, it failed, or it stopped."""
        try:
            worker, message = self._events.get(timeout=0.5)
        except queue.Empty:
            for worker in self._workers:
                if worker.process.poll() is not None:
                    raise FarmError(
                        self._why(worker, f"exited with code {worker.process.returncode}")
                    ) from None
            return
        if "dead" in message:
            raise FarmError(self._why(worker, "stopped"))
        if "error" in message:
            raise FarmError(self._why(worker, f"failed on frame {message.get('f')}: {message['error']}"))
        if message.get("ready"):
            worker.ready = True
            return
        worker.load -= 1
        worker.drawn += 1
        self._done.add(message["f"])

    # -- processes --------------------------------------------------------------

    def _spawn(self, index: int, hello: str) -> _Worker:
        flags = 0
        if sys.platform == "win32":  # the editor and the rest of the desktop stay responsive while it renders
            flags = subprocess.BELOW_NORMAL_PRIORITY_CLASS | subprocess.CREATE_NO_WINDOW
        process = subprocess.Popen(
            [sys.executable, "-m", MODULE],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=flags,
        )
        worker = _Worker(index, process)
        threading.Thread(target=self._read_events, args=(worker,), name=f"farm-{index}", daemon=True).start()
        threading.Thread(
            target=self._read_stderr, args=(worker,), name=f"farm-{index}-err", daemon=True
        ).start()
        try:
            process.stdin.write((hello + "\n").encode())
            process.stdin.flush()
        except OSError:
            pass  # it died at once: its "dead" event says so
        return worker

    def _read_events(self, worker: _Worker) -> None:
        try:
            for raw in worker.process.stdout:
                line = raw.strip()
                if line.startswith(b"{"):
                    self._events.put((worker, json.loads(line)))
        finally:
            self._events.put((worker, {"dead": True}))

    @staticmethod
    def _read_stderr(worker: _Worker) -> None:
        for raw in worker.process.stderr:
            worker.stderr.append(raw.decode("utf-8", errors="replace").rstrip())

    def _why(self, worker: _Worker, what: str) -> str:
        tail = " | ".join(line for line in worker.stderr if line.strip())[-400:]
        return f"render process {worker.index} {what}" + (f": {tail}" if tail else "")

    def close(self) -> None:
        """Stop the workers (waiting for those that finished, ending the rest) and free the ring."""
        finished = self.next_frame >= self.last
        for worker in self._workers:
            with contextlib.suppress(OSError):
                worker.process.stdin.close()
        for worker in self._workers:
            if finished:
                with contextlib.suppress(subprocess.TimeoutExpired):
                    worker.process.wait(GRACE_SECONDS)
            if worker.process.poll() is None:
                lifeline.kill_tree(worker.process.pid)
            with contextlib.suppress(subprocess.TimeoutExpired):
                worker.process.wait(GRACE_SECONDS)
            for stream in (worker.process.stdout, worker.process.stderr):
                with contextlib.suppress(OSError, ValueError):
                    stream.close()
        if self._workers:
            log.info("farm: frames drawn per process %s", [w.drawn for w in self._workers])
        self._workers = []
        self._views = []
        ring, self._ring = self._ring, None
        if ring is not None:
            try:
                ring.close()
            except BufferError:  # the caller still holds the last frame; the system frees it at exit
                log.debug("farm: the ring is still in use and stays until this process ends")
            with contextlib.suppress(FileNotFoundError):
                ring.unlink()

    def __enter__(self) -> Farm:
        return self

    def __exit__(self, *_exc) -> None:
        self.close()
