"""Test-imports one helper in a throwaway process (ADR 0058): Run on a helper.

A helper is a program like a code layer, so it never runs inside the editor. The Code page starts
``python -m manim_studio.processes.helper_check``, writes ONE job (a JSON line) to its stdin and reads ONE
result line back:

* job: ``{"name": "grid", "helpers": [[name, source], ...], "trusted": [name, ...]}`` - every helper
  of the project is importable (a helper may import another), those in ``trusted`` may run;
* result: ``{"ok": true, "output": "..."}`` with what the helper printed while it was imported, or
  ``{"ok": false, "error": "NameError: ...", "type": "NameError", "where": "helper:<name>",
  "helper_line": n, "traceback": "...", "output": "..."}``. ``where`` names the helper the error
  was raised in (it may be another helper this one imports); it is ``"code"`` when no helper frame
  is known.

Readers skip any other line. Nothing else is run: the helper's top level only.
"""

from __future__ import annotations

import importlib
import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout

from .. import lifeline

MAX_OUTPUT = 4096  # characters of printed output sent back (the end is kept)
NOT_A_FILE = "<helper check>"  # no user code is compiled under this name: every frame is a helper's


def check(name: str, sources: dict[str, str], trusted: frozenset[str] | set[str]) -> dict:
    """Import helper ``name`` once, served from ``sources``; the result message."""
    from ..core.assist.diagnostics import user_traceback
    from ..core.code import helpers

    printed = io.StringIO()
    try:
        with (
            helpers.install(sources, trusted=frozenset(trusted).__contains__),
            redirect_stdout(printed),
            redirect_stderr(printed),
        ):
            importlib.import_module(name)
    except (Exception, SystemExit) as error:
        place = helpers.locate(error, NOT_A_FILE)
        files = {helpers.filename(n): s for n, s in sources.items()}
        message = f"SyntaxError: {error.msg}" if isinstance(error, SyntaxError) else _describe(error)
        return {
            "ok": False,
            "error": message,
            "type": type(error).__name__,
            "where": place.where,
            "helper_line": place.helper_line,
            "traceback": user_traceback(error, files),
            "output": printed.getvalue()[-MAX_OUTPUT:],
        }
    return {"ok": True, "output": printed.getvalue()[-MAX_OUTPUT:]}


def _describe(error: BaseException) -> str:
    text = str(error)
    return f"{type(error).__name__}: {text}" if text else type(error).__name__


def main() -> int:
    lifeline.die_with_editor()  # the helper ends with the editor, whatever happens to it
    line = sys.stdin.readline()
    if not line.strip():
        return 0
    job = json.loads(line)
    sources = {str(n): str(s) for n, s in job.get("helpers", ())}
    result = check(str(job["name"]), sources, frozenset(job.get("trusted", ())))
    sys.__stdout__.write(json.dumps(result) + "\n")
    sys.__stdout__.flush()
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
