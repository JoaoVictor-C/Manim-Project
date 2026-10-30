"""Code layers rendered side by side for an export (ADR 0065).

A code layer's scene is played once by real Manim into the frame cache (ADR 0019) at the size being exported.
For a project of long scenes that is most of an export - the five-minute angular momentum project has seven
layers and needs over three minutes of it - and it was done one layer after another in one process, though
the layers do not depend on each other. ``render_all`` runs them in several of the single-job runner
processes the editor already uses (``code_runner``), longest first so the long ones are not left
for last, and reports a failed layer exactly as the serial path does.
"""

from __future__ import annotations

import collections
import contextlib
import json
import subprocess
import sys
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..logging_config import get_logger
from ..render import resources
from .code_runner import CodeError, Job

log = get_logger(__name__)

RUNNER_BYTES = 500 * 2**20  # what a runner is expected to hold (Manim, the scene, the frames it compresses)
MAX_AUTO = (
    4  # runners "auto" starts at most: each is a whole Manim, and the scenes also share the cores' caches
)
STOPPED = "the render process stopped unexpectedly"


def plan(requested: int | None, jobs: int) -> int:
    """How many runners to use for ``jobs`` layers (1: this process renders them one by one)."""
    if jobs < 2 or requested == 1:
        return 1
    if requested is not None:
        return min(requested, jobs)
    by_cores = min(MAX_AUTO, max(1, resources.cores() // 3))
    by_memory = int(resources.available_memory() * 0.5 // RUNNER_BYTES)
    return max(1, min(jobs, by_cores, by_memory))


def render_all(
    jobs: list[tuple[str, Job]],
    cache_dir: Path,
    workers: int,
    started: Callable[[str], None] | None = None,
) -> dict[str, CodeError]:
    """Render ``jobs`` ((layer id, job) pairs) in ``workers`` runner processes; the layers that failed, by id.

    ``started(layer id)`` is called, from a worker thread, as each layer begins."""
    ordered = sorted(jobs, key=lambda item: len(item[1].code), reverse=True)  # long scenes first
    failures: dict[str, CodeError] = {}

    def one(item: tuple[str, Job]) -> None:
        layer_id, job = item
        if started is not None:
            started(layer_id)
        error = _run(job, cache_dir)
        if error is not None:
            failures[layer_id] = error

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="code-render") as pool:
        list(pool.map(one, ordered))
    return failures


def _run(job: Job, cache_dir: Path) -> CodeError | None:
    """One layer in one runner process: None when it rendered, else why not."""
    process = subprocess.Popen(
        [sys.executable, "-m", "manim_studio.processes.code_runner", "--cache-dir", str(cache_dir)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    tail: collections.deque[str] = collections.deque(maxlen=20)

    def drain() -> None:
        for line in process.stderr:
            tail.append(line.rstrip())

    threading.Thread(target=drain, name="code-render-err", daemon=True).start()
    try:
        error = _talk(process, job)
    finally:
        with contextlib.suppress(OSError):
            process.stdin.close()
        try:
            process.wait(10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        for stream in (process.stdout, process.stderr):
            with contextlib.suppress(OSError, ValueError):
                stream.close()
    if error is not None and str(error) == STOPPED and any(tail):
        return CodeError(f"{STOPPED}: " + " | ".join(line for line in tail if line)[-400:])
    return error


def _talk(process: subprocess.Popen, job: Job) -> CodeError | None:
    """Wait for the runner to be ready, give it the job, read until it is done or has failed."""
    sent = False
    for raw in process.stdout:
        line = raw.strip()
        if not line.startswith("{"):
            continue  # anything but the protocol is skipped
        message = json.loads(line)
        if message.get("ready") and not sent:
            process.stdin.write(job.to_json() + "\n")
            process.stdin.flush()
            sent = True
        elif message.get("done"):
            return None
        elif "error" in message:
            return CodeError(
                str(message["error"]),
                message.get("line"),
                str(message.get("type") or ""),
                str(message.get("where") or "code"),
                str(message.get("traceback") or ""),
                message.get("helper_line"),
            )
    return CodeError(STOPPED)
