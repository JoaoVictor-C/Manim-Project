"""A render process of an export (ADR 0065): draws whole frames into memory it shares with the exporter.

Started by ``render.farm`` as ``python -m manim_studio.processes.frame_worker``. The protocol is one JSON
object per line:

* farm → worker, first: ``{"project": "<json, options applied>", "cache_dir": "...", "ring": "<shared memory
  name>", "slots": 24, "trust": false}``
* worker → farm, once it can draw: ``{"ready": true}``
* farm → worker: ``{"frames": [[frame, slot], ...]}``
* worker → farm, for each frame once its slot holds the picture: ``{"f": frame}``; a frame that cannot be
  drawn is ``{"f": frame, "error": "..."}`` and the worker ends (the exporter then draws on by itself and
  meets the error with its own traceback)

It ends when its input does. Anything Manim prints goes to stderr: stdout carries only the protocol.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
from multiprocessing import shared_memory
from pathlib import Path

from .. import lifeline
from .worker import _claim_stdout, _send


def main(argv: list[str] | None = None) -> int:
    lifeline.die_with_editor()  # the helper ends with the editor, whatever happens to it
    protocol = _claim_stdout()
    hello = json.loads(sys.stdin.readline())
    _lower_priority()

    import numpy as np

    from ..core.code import python_object
    from ..core.engine import adapter, build_lock, warm
    from ..core.engine.evaluator import Evaluator
    from ..core.model.schema import PYTHON_TYPES, Project
    from ..logging_config import setup_logging
    from ..render.cairo_export import make_camera, render_frame

    setup_logging(0, to_file=False)
    cache = Path(hello["cache_dir"])
    adapter.configure(cache)
    # Frames drawn side by side meet the same new title together: one compiles it, the rest read it.
    adapter.guard_builds(
        lambda spec: spec.type not in PYTHON_TYPES and warm.warm_key(spec) is not None,
        build_lock.BuildLock(cache / "build.lock"),
    )
    if hello["trust"]:
        python_object.trust_everything()
    project = Project.model_validate_json(hello["project"])
    canvas = project.canvas
    shape = (canvas.height_px, canvas.width_px, 4)
    frame_bytes = canvas.width_px * canvas.height_px * 4
    ring = shared_memory.SharedMemory(name=hello["ring"], track=False)
    views = [
        np.ndarray(shape, np.uint8, buffer=ring.buf, offset=k * frame_bytes) for k in range(hello["slots"])
    ]
    camera = make_camera(canvas, project.camera, project.view_background)
    evaluator = Evaluator(project)
    _send(protocol, {"ready": True})
    for line in sys.stdin:
        if not line.strip():
            continue
        for frame, slot in json.loads(line)["frames"]:
            try:
                t = frame / canvas.fps
                layers = [mob for _, mob in evaluator.frame_layers(t)]
                camera.pixel_array = views[slot]  # drawn where the exporter will read it: no copy
                render_frame(camera, layers, evaluator.overlay(t), copy=False)
            except Exception as exc:  # the exporter draws this frame itself and reports the real error
                _send(protocol, {"f": frame, "error": f"{type(exc).__name__}: {exc}"})
                return 1
            _send(protocol, {"f": frame})
    return 0


def _lower_priority() -> None:
    """Below the editor and the desktop: an export may take every core and must not stall the window."""
    if sys.platform != "win32":
        with contextlib.suppress(OSError):
            os.nice(5)


if __name__ == "__main__":
    raise SystemExit(main())
