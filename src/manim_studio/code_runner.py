"""Renders a code layer's scene into the frame cache (ADR 0019).

Runs user code, so it never runs inside the editor. Two entry points:

* ``python -m manim_studio.code_runner --cache-dir DIR`` — a single-use *warm
  spare*: imports Manim, prints ``{"ready": true}``, reads ONE job (a JSON line)
  from stdin, renders it, reports, and exits. The editor starts the next spare
  while this one works, so a code edit never waits for Manim's import (B30:
  ~6-8 s cold, ~0.9 s to the first frame warm).
* ``render_code(job, cache)`` — the same render in-process, for the export CLI,
  which is a separate process already.

Messages (one flushed JSON object per line; readers skip any other line):
``{"ready": true}``,
``{"frame": n}`` (every few frames), ``{"done": true, "frames": n}``, or
``{"error": "...", "line": n, "type": "NameError", "where": "code", "traceback": "..."}``: the line
number in the user's code, the exception's class name, where it came from (``"code"``, or
``"helper:<name>"``) and the traceback of the user's own frames (at most 4 KB). ``type``, ``where`` and
``traceback`` are optional for readers (older runners send only ``error`` and ``line``).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

PRELUDE = "from manim import *\nimport numpy as np\n"
CODE_FILENAME = "<code layer>"  # tracebacks name it, so lines map to the user's code
PROGRESS_EVERY = 10


@dataclass(frozen=True)
class Job:
    key: str
    code: str
    width: int
    height: int
    fps: int
    frame_height: float

    @classmethod
    def from_json(cls, line: str) -> Job:
        return cls(**json.loads(line))

    def to_json(self) -> str:
        return json.dumps(self.__dict__)


class CodeError(Exception):
    """The user's code failed; ``line`` is in the user's code (None if unknown). ``error_type`` is the
    exception's class name, ``where`` is ``"code"`` (or ``"helper:<name>"``) and ``traceback`` the
    user's own frames (P13.1)."""

    def __init__(
        self,
        message: str,
        line: int | None = None,
        error_type: str = "",
        where: str = "code",
        traceback: str = "",
    ) -> None:
        super().__init__(message)
        self.line = line
        self.error_type = error_type
        self.where = where
        self.traceback = traceback


def render_code(job: Job, cache, progress: Callable[[int], None] | None = None) -> int:
    """Play the job's scene once and store its frames under ``job.key``; returns the frame count."""
    import manim as m
    from manim.renderer.cairo_renderer import CairoRenderer

    scene_class = _scene_class(job.code)
    writer = cache.writer(job.key, job.width, job.height, job.fps)

    class CapturingRenderer(CairoRenderer):
        """Hands frames to the cache instead of a video writer (nothing is encoded)."""

        frames = 0

        def add_frame(self, frame, num_frames: int = 1) -> None:
            if self.skip_animations:
                return
            self.time += num_frames / self.camera.frame_rate
            for _ in range(num_frames):  # the same array: the writer stores it once
                writer.add(frame)
                CapturingRenderer.frames += 1
                if progress is not None and CapturingRenderer.frames % PROGRESS_EVERY == 0:
                    progress(CapturingRenderer.frames)

        def scene_finished(self, scene) -> None:
            # No movie to combine. A scene without animations is a still: one frame.
            if CapturingRenderer.frames == 0:
                self.update_frame(scene, ignore_skipping=True)
                self.add_frame(self.get_frame())

    options = {
        "pixel_width": job.width,
        "pixel_height": job.height,
        "frame_rate": job.fps,
        "frame_height": job.frame_height,
        "frame_width": job.frame_height * job.width / job.height,
        "background_opacity": 0.0,
        "disable_caching": True,
        "write_to_movie": False,
        "save_last_frame": False,
        "progress_bar": "none",
        "preview": False,
    }
    try:
        with m.tempconfig(options):
            scene_class(renderer=CapturingRenderer()).render()
    except CodeError:
        writer.abort()
        raise
    except Exception as error:
        writer.abort()
        raise _failure(error, job.code) from error
    writer.finish()
    return CapturingRenderer.frames


def _scene_class(code: str) -> type:
    import manim as m

    namespace: dict = {"__name__": "code_layer"}
    exec(PRELUDE, namespace)
    provided = dict(namespace)  # by identity: a user's `class Wait(Scene)` shadows Manim's Wait
    try:
        compiled = compile(code, CODE_FILENAME, "exec")
    except SyntaxError as error:
        raise _failure(error, code) from error
    try:
        exec(compiled, namespace)  # the user's own code, in this throwaway process
    except Exception as error:
        raise _failure(error, code) from error
    scenes = [
        v
        for k, v in namespace.items()
        if provided.get(k) is not v and isinstance(v, type) and issubclass(v, m.Scene)
    ]
    if len(scenes) != 1:
        found = ", ".join(s.__name__ for s in scenes) or "none"
        raise CodeError(f"define exactly one Scene subclass (found: {found})")
    return scenes[0]


def _failure(error: Exception, code: str) -> CodeError:
    """The user's exception as a ``CodeError``: its type and the traceback of the user's own frames."""
    from .core.diagnostics import user_traceback

    trace = user_traceback(error, {CODE_FILENAME: code})
    if isinstance(error, SyntaxError):
        return CodeError(f"SyntaxError: {error.msg}", error.lineno, "SyntaxError", traceback=trace)
    return CodeError(
        f"{type(error).__name__}: {error}", _user_line(error), type(error).__name__, traceback=trace
    )


def _user_line(error: BaseException) -> int | None:
    """The last line of the user's code in the traceback."""
    lines = [f.lineno for f in traceback.extract_tb(error.__traceback__) if f.filename == CODE_FILENAME]
    return lines[-1] if lines else None


def _emit(message: dict) -> None:
    print(json.dumps(message), flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m manim_studio.code_runner")
    parser.add_argument("--cache-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    logging.disable(logging.INFO)  # stdout carries the protocol; Manim's INFO lines would clutter it

    from .core import adapter
    from .core.code_cache import CodeCache

    adapter.configure(args.cache_dir)  # imports Manim: the expensive part, done before any job
    import manim as m

    m.logger.setLevel("WARNING")
    cache = CodeCache(args.cache_dir / "code")
    _emit({"ready": True})
    line = sys.stdin.readline()
    if not line.strip():
        return 0  # the editor closed: no job
    job = Job.from_json(line)
    try:
        frames = render_code(job, cache, progress=lambda n: _emit({"frame": n}))
    except CodeError as error:
        _emit(
            {
                "error": str(error),
                "line": error.line,
                "type": error.error_type,
                "where": error.where,
                "traceback": error.traceback,
            }
        )
        return 1
    _emit({"done": True, "frames": frames})
    return 0


if __name__ == "__main__":
    sys.exit(main())
