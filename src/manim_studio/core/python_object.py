"""Python objects (P10.1, ADR 0051): an object built by the user's own Manim code - pure, no Manim.

A Python object is ``Spec(type="Python", params={"code": source, "values": {name: value}})``.
The source defines, at top level::

    PARAMS = {"angle": (30.0, 5.0, 85.0), "label": "ab", "show": True, "colour": "#ff0000"}

    def build(p):
        return Polygon(...)  # a Manim VMobject

``PARAMS`` maps each parameter to its default; the default's type is the parameter's type
(a float, an int, True/False, text, or a colour when the text is ``#rgb``/``#rrggbb``). A
number may be ``(default, minimum, maximum)``. ``PARAMS`` is read from the source **without
running it** (``ast.literal_eval``), so Properties lists the parameters of code that has not
run - code from an opened file runs only once the user trusts it (ADR 0019). ``build(p)`` gets
the defaults overridden by the spec's ``values``.

This module reads ``PARAMS``, checks values against it, keeps the values that still fit when
the code changes, decides whether code may run on this computer (the trust store of code
layers), and stops a build that runs too long. ``core/adapter.py`` runs the code.
"""

from __future__ import annotations

import ast
import math
import os
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Literal

PYTHON_TYPE = "Python"
MAX_CODE = 64 * 1024  # characters of source a Python object may hold
FILENAME = "<python object>"  # what tracebacks name the user's code (to find its lines)
HELPER_FILES = "<helper "  # ... and the helpers it imports (helpers.FILENAME_PREFIX, ADR 0058)
# Seconds a build may run before it is stopped (an endless loop must not freeze). It counts the
# LaTeX a build waits for: the first formula after a MiKTeX update can take many seconds.
TIME_LIMIT = 30.0
NOT_TRUSTED = "code not trusted yet"
TIMED_OUT = "building took longer than"  # how a stopped build's message starts

PyKind = Literal["float", "int", "bool", "text", "colour"]

STARTER = '''# A Python object: build(p) returns a Manim object that the editor moves, styles and
# animates like any other. Apply (Ctrl+Enter) builds it; errors show at their line.
#
# PARAMS become fields in Properties. They are read without running the code, so use
# plain values: numbers, text, True/False or a colour like "#ff0000". A number may be
# (default, minimum, maximum). Manim is imported (from manim import *), with numpy as
# np and math. build(p) must draw the same thing every time for the same p.

PARAMS = {
    "angle": (30.0, 5.0, 85.0),  # the acute angle at the end of the base, in degrees
    "side": (3.0, 0.5, 8.0),  # the length of the base
}


def build(p):
    """A right triangle: the base along x, the right angle at the origin, marked."""
    base = p["side"]
    height = base * math.tan(math.radians(p["angle"]))
    triangle = Polygon(ORIGIN, RIGHT * base, UP * height)
    size = 0.12 * min(base, height)
    mark = VGroup(  # the little square in the right angle
        Line(RIGHT * size, RIGHT * size + UP * size),
        Line(RIGHT * size + UP * size, UP * size),
    )
    return VGroup(triangle, mark)
'''


@dataclass(frozen=True)
class PyParam:
    """One parameter of a Python object, read from its ``PARAMS``."""

    name: str
    kind: PyKind
    default: Any
    minimum: float | None = None
    maximum: float | None = None

    def check(self, value: Any) -> str | None:
        """Why ``value`` cannot be this parameter's value, or None."""
        if self.kind == "bool":
            return None if isinstance(value, bool) else "True or False"
        if self.kind == "colour":
            return None if is_colour(value) else 'a colour like "#ff0000"'
        if self.kind == "text":
            return None if isinstance(value, str) else "text"
        number = isinstance(value, (int, float)) and not isinstance(value, bool)
        if self.kind == "int" and not (number and float(value).is_integer()):
            return "a whole number"
        if not number or not math.isfinite(value):
            return "a number"
        low = -math.inf if self.minimum is None else self.minimum
        high = math.inf if self.maximum is None else self.maximum
        if not low <= value <= high:
            return f"a number from {self.minimum:g} to {self.maximum:g}"
        return None


class CodeProblem(ValueError):  # noqa: N818 - a problem shown to the user, not a crash
    """Something wrong with a Python object's code, at ``line`` (1-based) when known. ``error_type`` is
    the exception's class name ("" when the problem is not an exception), ``traceback`` the user's own
    frames, at most 4 KB (P13.1).

    ``where`` is ``"code"``, or ``"helper:<name>"`` when the error was raised inside a helper the code
    imports (ADR 0058): then ``helper_line`` is the helper's line and ``line`` the code's line that
    led there (its import or call), as before."""

    def __init__(
        self,
        message: str,
        line: int | None = None,
        error_type: str = "",
        where: str = "code",
        traceback: str = "",
        helper_line: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.line = line
        self.error_type = error_type
        self.where = where
        self.traceback = traceback
        self.helper_line = helper_line

    def __str__(self) -> str:
        if self.where.startswith("helper:"):
            at = f", line {self.helper_line}" if self.helper_line else ""
            return f"helper {self.where.removeprefix('helper:')}{at}: {self.message}"
        return f"line {self.line}: {self.message}" if self.line else self.message


def is_colour(value: Any) -> bool:
    """``#rgb`` or ``#rrggbb`` (as ``schema.is_colour``; repeated so this module imports nothing)."""
    return (
        isinstance(value, str)
        and len(value) in (4, 7)
        and value.startswith("#")
        and all(c in "0123456789abcdefABCDEF" for c in value[1:])
    )


# -- PARAMS ----------------------------------------------------------------------------------------


def read_params(code: str) -> tuple[PyParam, ...]:
    """The parameters ``code`` declares, read without running it; raises ``CodeProblem``."""
    params, problem = _read(code)
    if problem is not None:
        raise problem
    return params


def params_problem(code: str) -> CodeProblem | None:
    """Why ``PARAMS`` (or the code's syntax) cannot be read, or None."""
    return _read(code)[1]


def is_python_object_code(code: str) -> bool:
    """Whether source has the Python-object ``build(p)`` shape rather than a Manim Scene.

    Detection is syntax-only: importing a file must never execute its code. A top-level
    ``build`` function identifies an object unless a top-level class defines ``construct``,
    which is the normal Manim Scene interface.
    """
    try:
        tree = ast.parse(code.lstrip("\ufeff"), FILENAME)  # a file saved with a BOM is still Python
    except (SyntaxError, ValueError):
        return False
    has_build = any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "build"
        for node in tree.body
    )
    has_scene = any(
        isinstance(node, ast.ClassDef)
        and any(
            isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)) and member.name == "construct"
            for member in node.body
        )
        for node in tree.body
    )
    return has_build and not has_scene


@lru_cache(maxsize=256)
def _read(code: str) -> tuple[tuple[PyParam, ...], CodeProblem | None]:
    try:
        tree = ast.parse(code, FILENAME)
    except SyntaxError as exc:
        return (), CodeProblem(f"SyntaxError: {exc.msg}", exc.lineno, "SyntaxError")
    except ValueError as exc:  # e.g. a NUL character
        return (), CodeProblem(f"SyntaxError: {exc}", error_type="SyntaxError")
    assignments = [
        node
        for node in tree.body
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        and any(isinstance(t, ast.Name) and t.id == "PARAMS" for t in _targets(node))
    ]
    if not assignments:
        return (), None  # no parameters
    node = assignments[-1]  # the last assignment wins, as when the code runs
    if node.value is None:
        return (), CodeProblem("PARAMS needs a value", node.lineno)
    try:
        value = ast.literal_eval(node.value)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return (), CodeProblem(
            "PARAMS must be written with plain values only (numbers, text, True/False, colours "
            'like "#ff0000"): it is read without running the code',
            node.lineno,
        )
    if not isinstance(value, dict):
        return (), CodeProblem("PARAMS must be a dict: {name: default}", node.lineno)
    out = []
    for name, default in value.items():
        try:
            out.append(_param(name, default))
        except ValueError as exc:
            return (), CodeProblem(str(exc), node.lineno)
    return tuple(out), None


def _targets(node: ast.Assign | ast.AnnAssign) -> list[ast.expr]:
    return node.targets if isinstance(node, ast.Assign) else [node.target]


def _param(name: Any, default: Any) -> PyParam:
    if not isinstance(name, str) or not name.isidentifier():
        raise ValueError(f"PARAMS: {name!r} is not a valid parameter name (use letters, digits and _)")
    if isinstance(default, tuple):
        if len(default) != 3 or not all(_is_number(v) for v in default):
            raise ValueError(
                f"PARAMS[{name!r}]: limits are written (default, minimum, maximum), with numbers"
            )
        value, low, high = default
        if not low <= value <= high:
            raise ValueError(f"PARAMS[{name!r}]: the default {value!r} is not from {low!r} to {high!r}")
        kind = "int" if all(isinstance(v, int) for v in default) else "float"
        if kind == "float":
            value, low, high = float(value), float(low), float(high)
        return PyParam(name, kind, value, low, high)
    if isinstance(default, bool):
        return PyParam(name, "bool", default)
    if isinstance(default, int):
        return PyParam(name, "int", default)
    if isinstance(default, float):
        if not math.isfinite(default):
            raise ValueError(f"PARAMS[{name!r}]: the default must be a finite number")
        return PyParam(name, "float", default)
    if isinstance(default, str):
        return PyParam(name, "colour" if is_colour(default) else "text", default)
    raise ValueError(
        f"PARAMS[{name!r}]: {type(default).__name__} is not a parameter type "
        "(use a number, text, True/False or a colour)"
    )


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


# -- values ----------------------------------------------------------------------------------------


def spec_problem(params: dict[str, Any]) -> str | None:
    """Why a Python object's spec params are not acceptable (the file format), or None.

    Code that cannot be read is accepted: the object shows its error at its line (a placeholder).
    """
    code = params.get("code")
    if not isinstance(code, str):
        return "a Python object needs its code (text)"
    if len(code) > MAX_CODE:
        return f"the code is longer than {MAX_CODE // 1024} KB"
    unknown = sorted(set(params) - {"code", "values"})
    if unknown:
        return f"unknown params {unknown} (a Python object has code and values)"
    values = params.get("values", {})
    if not isinstance(values, dict):
        return "values must map parameter names to values"
    declared, problem = _read(code)
    if problem is not None:
        return None
    by_name = {p.name: p for p in declared}
    for name, value in values.items():
        param = by_name.get(name)
        if param is None:
            return f"no parameter {name!r} in PARAMS"
        why = param.check(value)
        if why is not None:
            return f"{name} must be {why}, not {value!r}"
    return None


def call_values(code: str, values: dict[str, Any]) -> dict[str, Any]:
    """What ``build(p)`` is called with: every declared default, overridden by ``values``."""
    params, _ = _read(code)
    out = {p.name: p.default for p in params}
    for p in params:
        if p.name in values:
            value = values[p.name]
            out[p.name] = float(value) if p.kind == "float" else int(value) if p.kind == "int" else value
    return out


def kept_values(code: str, values: dict[str, Any]) -> dict[str, Any]:
    """The ``values`` that still fit new ``code`` (a parameter removed or retyped drops its value)."""
    params, problem = _read(code)
    if problem is not None:
        return dict(values)  # unreadable for now: keep everything until the code is fixed
    by_name = {p.name: p for p in params}
    return {k: v for k, v in values.items() if k in by_name and by_name[k].check(v) is None}


# -- trust (ADR 0019) --------------------------------------------------------------------------------

_trust_everything = False  # the CLI's --trust-code, an exported scene the user renders
_store: tuple[object, Any] | None = None  # (the store file's stamp, the TrustStore read from it)


def trust_everything(on: bool = True) -> None:
    """Let every Python object's code run in this process (the user asked: ``--trust-code``)."""
    global _trust_everything
    _trust_everything = on


def is_trusted(code: str) -> bool:
    """May ``code`` run here? Only when its hash is in the user's trusted store (the code layers'
    store, re-read when the file changes, so every process - the editor, its build worker and
    preview process, an export - agrees), or everything is trusted."""
    global _store
    if _trust_everything:
        return True
    from .trust import TrustStore, default_path

    path = default_path()
    try:
        stat = os.stat(path)
        stamp: object = (str(path), stat.st_mtime_ns, stat.st_size)
    except OSError:
        stamp = (str(path), None)
    if _store is None or _store[0] != stamp:
        _store = (stamp, TrustStore(path))
    return _store[1].is_trusted(code)


# -- a time limit ------------------------------------------------------------------------------------


class TimeLimit(BaseException):
    """A build ran longer than its time limit."""


@contextmanager
def time_limit(seconds: float) -> Iterator[None]:
    """Stop the code run inside after ``seconds``: ``TimeLimit`` is raised in it.

    A trace function looks at the clock on every Python call and on every line of the user's
    code (``FILENAME``), so an endless loop in the code - or one calling Manim - is stopped. It
    cannot stop a single call that never returns into Python (a huge numpy computation, a sleep).
    The editor's build worker, which is killed when a build takes too long (ADR 0015), covers
    those for code applied in the editor.
    """
    deadline = time.perf_counter() + seconds
    previous = sys.gettrace()

    def check() -> None:
        if time.perf_counter() > deadline:
            raise TimeLimit(f"{TIMED_OUT} {seconds:g} s (an endless loop?)")

    def lines(frame, event, arg):
        if event == "line":
            check()
        return lines

    def calls(frame, event, arg):
        check()
        name = frame.f_code.co_filename
        return lines if name == FILENAME or name.startswith(HELPER_FILES) else None  # helpers: ADR 0058

    sys.settrace(calls)
    try:
        yield
    finally:
        sys.settrace(previous)
