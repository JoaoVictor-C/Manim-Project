"""When may Live mode re-run code the user is still typing (P13.7)? Pure: no Qt, nothing runs.

Live mode applies a Python object's text after a pause in typing. Typing is the dangerous moment:
a half-written line can be anything, and ``os.remove(path)`` is completed one character at a time. So
Live only runs text that parses, whose ``PARAMS`` can be read, and that does not touch files, processes,
the network or the import machinery - for those the user presses Run, which is a decision, not a pause.
This is a courtesy for typing, not a sandbox: a trusted layer that reaches those APIs still runs when
the user runs it (ADR 0019).
"""

from __future__ import annotations

import ast

from ..code import python_object

RISKY_NAMES = frozenset({"open", "exec", "eval", "compile", "__import__", "input", "breakpoint", "globals"})
RISKY_MODULES = frozenset(
    {
        "os",
        "sys",
        "subprocess",
        "shutil",
        "socket",
        "importlib",
        "pathlib",
        "ctypes",
        "multiprocessing",
        "threading",
        "urllib",
        "http",
        "requests",
        "webbrowser",
        "pickle",
        "shelve",
        "tempfile",
        "glob",
        "signal",
        "asyncio",
        "builtins",
        "io",
    }
)


def risky_uses(source: str) -> list[str]:
    """Every risky module or built-in the code names (``["os", "open"]``), in order of appearance; empty
    when it does not parse. What the import window tells the user before they allow the code to run."""
    try:
        tree = ast.parse(source.removeprefix("\ufeff"))
    except (SyntaxError, ValueError):
        return []
    found: dict[str, None] = {}
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names = [node.module.split(".")[0]]
        elif isinstance(node, ast.Name):
            names = [node.id]
        for name in names:
            if name in RISKY_MODULES or name in RISKY_NAMES:
                found[name] = None
    return list(found)


def risky_reason(source: str) -> str | None:
    """What makes ``source`` unsuitable for Live (``"uses os"``), or None. Text that does not parse
    has no reason here: it simply does not run (``live_problem`` says so)."""
    try:
        tree = ast.parse(source.lstrip("\ufeff"))
    except (SyntaxError, ValueError):
        return None
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.append(node.module.split(".")[0])
        elif isinstance(node, ast.Name):
            found.append(node.id)
    for name in found:
        if name in RISKY_MODULES or name in RISKY_NAMES:
            return f"uses {name}"
    return None


def live_problem(source: str) -> str | None:
    """Why ``source`` must not be applied by Live now: None when it may, else a short reason.

    ``"does not parse yet"`` and ``"PARAMS cannot be read yet"`` are quiet reasons (the user is
    mid-sentence); ``"uses os"`` and the like are the ones worth telling the user about."""
    try:
        ast.parse(source.lstrip("\ufeff"))
    except (SyntaxError, ValueError):
        return "does not parse yet"
    if python_object.params_problem(source.removeprefix("\ufeff")) is not None:
        return "PARAMS cannot be read yet"
    return risky_reason(source)


def is_quiet(reason: str) -> bool:
    """A reason the user does not need to be told about."""
    return reason in ("does not parse yet", "PARAMS cannot be read yet")
