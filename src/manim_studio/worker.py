"""Build worker: warms Manim's disk cache for text objects (ADR 0015).

Run as ``python -m manim_studio.worker --cache-dir DIR``. The protocol is one
JSON object per line:

* worker → editor, once started: ``{"ready": true}``
* editor → worker: ``{"id": 7, "spec": {...}}``
* worker → editor: ``{"id": 7, "ok": true, "ms": 1287.4}`` or
  ``{"id": 7, "ok": false, "error": "..."}``

Building the spec here leaves Manim's SVG cache warm, so the editor's own build
of the same object takes milliseconds (B18). New code of a Python object (ADR 0051)
is run here first: one stopped by its time limit is reported as a failure, so the
edit bringing it is dropped instead of freezing the editor. Anything Manim or LaTeX prints goes
to stderr: stdout carries only the protocol.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import IO

ERROR_LINES = 6  # enough of a LaTeX error to show the user


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m manim_studio.worker")
    parser.add_argument("--cache-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    protocol = _claim_stdout()

    from .core import adapter  # imports Manim: the slow part of starting up
    from .core.schema import Spec
    from .logging_config import setup_logging

    setup_logging(0, to_file=False)
    adapter.configure(args.cache_dir)
    _send(protocol, {"ready": True})
    for line in sys.stdin:
        if not line.strip():
            continue
        request = json.loads(line)
        started = time.perf_counter()
        try:
            spec = Spec.model_validate(request["spec"])
            adapter.build_mobject(spec)
            stopped = adapter.python_timed_out(spec)  # an endless loop in new code (ADR 0051)
        except Exception as exc:  # report every build failure; the editor decides what to show
            _send(protocol, {"id": request["id"], "ok": False, "error": _summary(exc)})
        else:
            if stopped:
                _send(protocol, {"id": request["id"], "ok": False, "error": stopped})
                continue
            ms = (time.perf_counter() - started) * 1000
            _send(protocol, {"id": request["id"], "ok": True, "ms": round(ms, 1)})
    return 0


def _claim_stdout() -> IO[str]:
    """Keep the real stdout for the protocol; route fd 1 (and print) to stderr."""
    protocol = os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf-8", newline="\n")
    sys.stdout.flush()
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    sys.stdout = sys.stderr
    return protocol


def _send(stream: IO[str], message: dict) -> None:
    stream.write(json.dumps(message) + "\n")
    stream.flush()


def _summary(exc: Exception) -> str:
    """One short message: LaTeX's own error lines when there is a log, else the exception."""
    if isinstance(exc, FileNotFoundError):  # no LaTeX on this computer says so
        from .core import adapter

        return adapter.build_failure(exc)
    message = str(exc)
    log_file = re.search(r"log file: (\S+\.log)", message)
    if log_file:
        latex_errors = _latex_errors(Path(log_file.group(1)))
        if latex_errors:
            return "LaTeX error: " + "; ".join(latex_errors)
    lines = [line for line in message.splitlines() if line.strip()]
    text = "\n".join(lines[:ERROR_LINES]) or type(exc).__name__
    return f"{type(exc).__name__}: {text}"


def _latex_errors(log: Path) -> list[str]:
    try:
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return [line[2:].strip() for line in lines if line.startswith("! ")][:3]


if __name__ == "__main__":
    sys.exit(main())
