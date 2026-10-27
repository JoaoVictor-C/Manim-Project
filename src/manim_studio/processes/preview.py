"""Preview render process: renders frames ahead of the editor's playhead (ADR 0028).

Run as ``python -m manim_studio.processes.preview --cache-dir DIR``. One JSON object per line:

* process → editor, once started: ``{"ready": true}``
* editor → process:
  ``{"project": {...}, "generation": 7}`` - the project as of that generation;
  ``{"view": {...}, "view_id": 3}`` - the framing (``render.preview.PreviewView``);
  ``{"want": [12, 13, ...]}`` - the frames to render, in order (replaces the last list);
  ``{"media": true}`` - re-read media files changed on disk (ADR 0027).
* process → editor: ``{"frame": 12, "view_id": 3, "generation": 7, "width": W,
  "height": H, "data": "<base64 of zlib-compressed RGBA>"}``, or
  ``{"failed": 12, "error": "..."}`` when a frame cannot be rendered.

A reader thread queues what arrives, so between two frames the newest project,
view and list apply and stale work is dropped. Code layers are read from the
editor's code cache, never run. stdout carries only the protocol.
"""

from __future__ import annotations

import argparse
import base64
import json
import queue
import sys
import threading
import zlib
from pathlib import Path
from typing import IO, Any

from .. import lifeline
from .worker import _claim_stdout, _send, _summary


def main(argv: list[str] | None = None) -> int:
    lifeline.die_with_editor()  # the helper ends with the editor, whatever happens to it
    parser = argparse.ArgumentParser(prog="python -m manim_studio.processes.preview")
    parser.add_argument("--cache-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    protocol = _claim_stdout()

    from ..core.engine import adapter  # imports Manim: the slow part of starting up
    from ..logging_config import setup_logging

    setup_logging(0, to_file=False)
    adapter.configure(args.cache_dir)
    inbox: queue.Queue[dict | None] = queue.Queue()
    threading.Thread(target=_read, args=(sys.stdin, inbox), daemon=True).start()
    renderer = Renderer(protocol)
    _send(protocol, {"ready": True})
    while True:
        messages = [inbox.get()] if not renderer.busy else []  # idle: wait for work
        while True:
            try:
                messages.append(inbox.get_nowait())
            except queue.Empty:
                break
        for message in messages:
            if message is None:  # the editor closed our stdin
                return 0
            renderer.apply(message)
        renderer.render_next()


def _read(stream: IO[str], inbox: queue.Queue) -> None:
    for line in stream:
        if line.strip():
            inbox.put(json.loads(line))
    inbox.put(None)


class Renderer:
    """The process's state: its own evaluator, the framing and the frames still wanted."""

    def __init__(self, protocol: IO[str]) -> None:
        self.protocol = protocol
        self.project = None
        self.generation = 0
        self.evaluator = None
        self.view_id = 0
        self.view = None
        self.camera = None
        self.want: list[int] = []

    @property
    def busy(self) -> bool:
        return bool(self.want) and self.evaluator is not None and self.camera is not None

    def apply(self, message: dict[str, Any]) -> None:
        from ..core.engine.evaluator import Evaluator
        from ..core.engine.frame_cache import changed_layers
        from ..core.model.schema import Project
        from ..render.preview import PreviewView, preview_camera

        camera_before = self.project.camera if self.project is not None else None
        if "project" in message:
            project = Project.model_validate(message["project"])
            changed = changed_layers(self.project, project) if self.project is not None else None
            if self.evaluator is None or changed is None:
                self.evaluator = Evaluator(project)
            else:
                self.evaluator.invalidate(project, changed, "spec" if changed else "timing")
            self.project, self.generation = project, int(message["generation"])
        if "view" in message:
            self.view_id = int(message["view_id"])
            self.view = PreviewView.from_json(message["view"])
        stale = "view" in message or self.camera is None or self.project.camera != camera_before
        if self.view is not None and self.project is not None and stale:
            self.camera = preview_camera(self.view, self.project.camera)  # as the canvas (ADR 0048)
        if "want" in message:
            self.want = [int(i) for i in message["want"]]
        if message.get("media") and self.evaluator is not None:
            self.evaluator.check_media()

    def render_next(self) -> None:
        from ..core.engine.frame_cache import frame_count, frame_time
        from ..render.cairo_export import render_frame

        if not self.busy:
            return
        index = self.want.pop(0)
        if not 0 <= index < frame_count(self.project):
            return
        try:
            t = frame_time(index, self.project.canvas.fps)
            layers = [mob for _, mob in self.evaluator.frame_layers(t)]
            pixels = render_frame(self.camera, layers, self.evaluator.overlay(t))
        except Exception as exc:  # the editor renders that frame live instead
            _send(self.protocol, {"failed": index, "error": _summary(exc)})
            return
        height, width = pixels.shape[:2]
        data = base64.b64encode(zlib.compress(pixels.tobytes(), 1)).decode("ascii")
        _send(
            self.protocol,
            {
                "frame": index,
                "view_id": self.view_id,
                "generation": self.generation,
                "width": width,
                "height": height,
                "data": data,
            },
        )


if __name__ == "__main__":
    raise SystemExit(main())
