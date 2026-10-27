"""The voice helper (ADR 0060): lists a provider's voices and speaks texts, away from the editor.

A provider is code somebody installed and may load a large model or wait for a network, so it never runs
in the editor. Run as ``python -m manim_studio.processes.voice``; ONE job (a JSON line) on stdin, JSON
lines on stdout, then the process ends:

* ``{"op": "voices", "provider": "edge"}`` answers
  ``{"ok": true, "voices": [{"id", "name", "language", "gender"}, ...]}`` or
  ``{"ok": false, "error": "...", "unavailable": true}`` (``unavailable``: the provider cannot run here,
  and ``error`` says what to install);
* ``{"op": "speak", "provider": "edge", "items": [{"id", "text", "voice", "rate", "out"}, ...]}``
  answers one ``{"id": ..., "ok": true}`` or ``{"id": ..., "ok": false, "error": "..."}`` per item, as
  each finishes, then ``{"done": true}``.

A file is written under a temporary name and renamed when complete, so an unfinished one is never taken
for speech. A ``VoiceError`` that is ``retryable`` is tried again after a pause that grows
(``MANIM_STUDIO_VOICE_BACKOFF`` seconds, default 1.5, times the attempt; ``MANIM_STUDIO_VOICE_TRIES``,
default 6). Anything a provider prints goes to stderr: stdout carries only the protocol.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
import traceback
from collections.abc import Callable
from pathlib import Path

from .. import lifeline
from .worker import _claim_stdout, _send

BACKOFF_S = 1.5
TRIES = 6


def main(argv: list[str] | None = None) -> int:
    lifeline.die_with_editor()  # the helper ends with the editor, whatever happens to it
    protocol = _claim_stdout()
    job = json.loads(sys.stdin.readline())
    from .. import plugins
    from ..logging_config import setup_logging

    setup_logging(0, to_file=False)
    plugins.ensure_loaded()
    provider = plugins.VOICES.get(job.get("provider", ""))
    if provider is None:
        _send(protocol, {"ok": False, "error": f"no voice provider named {job.get('provider')!r}"})
        _send(protocol, {"done": True})
        return 0
    reason = provider.check() if provider.check is not None else None
    if reason:
        _send(protocol, {"ok": False, "error": reason, "unavailable": True})
        _send(protocol, {"done": True})
        return 0
    if job.get("op") == "voices":
        _send(protocol, list_voices(provider))
    elif job.get("op") == "speak":
        for item in job.get("items", []):
            _send(protocol, speak(provider, item))
        _send(protocol, {"done": True})
    else:
        _send(protocol, {"ok": False, "error": f"unknown job {job.get('op')!r}"})
    return 0


def list_voices(provider) -> dict:
    from ..plugins import VoiceError

    try:
        found = provider.voices()
    except VoiceError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return {
        "ok": True,
        "voices": [{"id": v.id, "name": v.name, "language": v.language, "gender": v.gender} for v in found],
    }


def speak(provider, item: dict) -> dict:
    """Speak one item, retrying the errors a provider calls retryable; the message to send."""
    from ..plugins import VoiceError

    out = Path(item["out"])
    out.parent.mkdir(parents=True, exist_ok=True)
    partial = out.with_name(f"{out.stem}.part{out.suffix}")
    backoff = float(os.environ.get("MANIM_STUDIO_VOICE_BACKOFF", BACKOFF_S))
    tries = int(os.environ.get("MANIM_STUDIO_VOICE_TRIES", TRIES))
    problem = "nothing was spoken"
    for attempt in range(1, tries + 1):
        partial.unlink(missing_ok=True)
        try:
            provider.synthesize(item["text"], item["voice"], float(item.get("rate", 1.0)), partial)
            if not partial.exists() or partial.stat().st_size == 0:
                raise VoiceError("the voice wrote no sound", retryable=True)
            partial.replace(out)
            return {"id": item["id"], "ok": True}
        except VoiceError as exc:
            problem = str(exc)
            if not exc.retryable:
                break
            if attempt < tries:
                time.sleep(backoff * attempt)
        except Exception as exc:  # a provider's bug: report it, go on with the next text
            traceback.print_exc()
            problem = f"{type(exc).__name__}: {exc}"
            break
    partial.unlink(missing_ok=True)
    return {"id": item["id"], "ok": False, "error": problem}


def run_job(
    job: dict, on_message: Callable[[dict], None] | None = None, timeout_s: float = 180.0
) -> list[dict]:
    """Run one job in a helper process and wait for it (the command line; the editor has its own client).

    ``on_message`` sees each answer as it comes; the answers are returned. A helper that says nothing for
    ``timeout_s`` seconds, or ends without ``{"done": true}``, is reported as one failed answer."""
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"}
    process = subprocess.Popen(
        [sys.executable, "-m", "manim_studio.processes.voice"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        env=env,
    )
    lines: queue.Queue[str | None] = queue.Queue()

    def read() -> None:
        for line in process.stdout:
            lines.put(line)
        lines.put(None)

    threading.Thread(target=read, daemon=True).start()
    process.stdin.write(json.dumps(job) + "\n")
    process.stdin.close()
    answers: list[dict] = []
    why = "the voice helper stopped before it finished"
    while True:
        try:
            line = lines.get(timeout=timeout_s)
        except queue.Empty:
            why = f"the voice helper gave no answer for {timeout_s:g} s"
            break
        if line is None:
            break
        try:
            message = json.loads(line)
        except ValueError:
            continue
        if not isinstance(message, dict):
            continue
        answers.append(message)
        if on_message is not None:
            on_message(message)
        if message.get("done"):
            process.wait(timeout=10)
            return answers
    process.kill()
    process.wait(timeout=10)
    failed = {"ok": False, "error": why}
    answers.append(failed)
    if on_message is not None:
        on_message(failed)
    return answers


if __name__ == "__main__":
    sys.exit(main())
