"""Python objects (P10.1, ADR 0051): an object built by the user's own Manim code - pure, no Manim.

A Python object is ``Spec(type="Python", params={"code": source, "values": {name: value}})``.
The source defines, at top level::

    PARAMS = {"angle": (30.0, 5.0, 85.0), "label": "ab", "show": True, "colour": "#ff0000"}

    def build(p):
        return Polygon(...)  # a Manim VMobject

``PARAMS`` maps each parameter to a default, or to a literal descriptor such as
``{"type": "float", "default": 2.0, "min": 0.1, "max": 8.0, "unit": "m"}``. Descriptors
can also set labels, steps and choices. ``PARAMS`` is read from the source **without running
it** (``ast.literal_eval``), so Properties lists the parameters of code that has not run -
code from an opened file runs only once the user trusts it (ADR 0019). ``build(p)`` gets the
defaults overridden by the spec's ``values``.

This module reads ``PARAMS``, checks values against it, keeps the values that still fit when
the code changes, decides whether code may run on this computer (the trust store of code
layers), and stops a build that runs too long. ``core/engine/adapter.py`` runs the code.
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

from . import limits

PYTHON_TYPE = "Python"
MAX_CODE = 64 * 1024  # characters of source a Python object may hold
FILENAME = "<python object>"  # what tracebacks name the user's code (to find its lines)
HELPER_FILES = "<helper "  # ... and the helpers it imports (helpers.FILENAME_PREFIX, ADR 0058)
# Seconds a build may run before it is stopped (an endless loop must not freeze). It counts the
# LaTeX a build waits for: the first formula after a MiKTeX update can take many seconds.
TIME_LIMIT = 30.0
NOT_TRUSTED = "code not trusted yet"
TIMED_OUT = "building took longer than"  # how a stopped build's message starts

PyKind = Literal["float", "int", "bool", "text", "colour", "choice", "point"]

STARTER = '''# A Python object: build(p) returns a Manim object that the editor moves, styles and
# animates like any other. Apply (Ctrl+Enter) builds it; errors show at their line.
#
# PARAMS become fields in Properties. Use plain defaults, numeric (default, min, max)
# tuples, or descriptors with type, default, min, max, unit, label and step. Choices and
# 2D points are supported too.
# HANDLES maps canvas labels to a point parameter or a pair of numeric parameter names.
# Manim is imported (from manim import *), with numpy as np and math.

PARAMS = {
    "angle": (30.0, 5.0, 85.0),  # in degrees
    "side": (3.0, 0.5, 8.0),  # in scene units
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
    label: str = ""
    unit: str = ""
    step: float | None = None
    choices: tuple[str, ...] = ()

    def check(self, value: Any) -> str | None:
        """Why ``value`` cannot be this parameter's value, or None."""
        if self.kind == "point":
            if (
                not isinstance(value, (tuple, list))
                or len(value) != 2
                or not all(_is_number(v) for v in value)
            ):
                return "a point with two finite numbers"
            low = -math.inf if self.minimum is None else self.minimum
            high = math.inf if self.maximum is None else self.maximum
            if any(not low <= coordinate <= high for coordinate in value):
                if self.minimum is not None and self.maximum is not None:
                    return f"a point with coordinates from {self.minimum:g} to {self.maximum:g}"
                if self.minimum is not None:
                    return f"a point with coordinates at least {self.minimum:g}"
                return f"a point with coordinates at most {self.maximum:g}"
            return None
        if self.kind == "choice":
            if isinstance(value, str) and value in self.choices:
                return None
            return "one of " + ", ".join(self.choices)
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
            if self.minimum is not None and self.maximum is not None:
                return f"a number from {self.minimum:g} to {self.maximum:g}"
            if self.minimum is not None:
                return f"a number at least {self.minimum:g}"
            return f"a number at most {self.maximum:g}"
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
    if isinstance(default, dict):
        return _descriptor(name, default)
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


def _descriptor(name: str, descriptor: dict[Any, Any]) -> PyParam:
    """Read a literal parameter descriptor; no user expression is evaluated."""
    allowed = {"type", "default", "min", "max", "unit", "label", "step", "choices"}
    unknown = set(descriptor) - allowed
    if unknown:
        keys = ", ".join(map(str, sorted(unknown, key=str)))
        raise ValueError(f"PARAMS[{name!r}]: unknown descriptor keys: {keys}")
    if "type" not in descriptor or "default" not in descriptor:
        raise ValueError(f"PARAMS[{name!r}]: a descriptor needs 'type' and 'default'")
    kind = descriptor["type"]
    kind = "colour" if kind == "color" else kind
    if kind not in ("float", "int", "bool", "text", "colour", "choice", "point"):
        raise ValueError(f"PARAMS[{name!r}]: unsupported type {kind!r}")
    value = descriptor["default"]
    low, high = descriptor.get("min"), descriptor.get("max")
    unit, label, step = descriptor.get("unit", ""), descriptor.get("label", ""), descriptor.get("step")
    choices_value = descriptor.get("choices", ())
    if kind != "choice" and "choices" in descriptor:
        raise ValueError(f"PARAMS[{name!r}]: 'choices' only fits the choice type")
    if not isinstance(unit, str) or not isinstance(label, str):
        raise ValueError(f"PARAMS[{name!r}]: 'unit' and 'label' must be text")
    if kind in ("float", "int", "point"):
        for bound, key in ((low, "min"), (high, "max")):
            if bound is not None and not _is_number(bound):
                raise ValueError(f"PARAMS[{name!r}]: {key!r} must be a finite number")
        if low is not None and high is not None and low > high:
            raise ValueError(f"PARAMS[{name!r}]: 'min' must not exceed 'max'")
        if step is not None and (not _is_number(step) or step <= 0):
            raise ValueError(f"PARAMS[{name!r}]: 'step' must be a positive finite number")
        if kind == "int" and any(
            bound is not None and not float(bound).is_integer() for bound in (low, high)
        ):
            raise ValueError(f"PARAMS[{name!r}]: integer limits must be whole numbers")
        if kind == "int" and step is not None and not float(step).is_integer():
            raise ValueError(f"PARAMS[{name!r}]: an integer 'step' must be a whole number")
    elif low is not None or high is not None or step is not None:
        raise ValueError(f"PARAMS[{name!r}]: limits and steps only fit numeric and point parameters")
    if unit and kind not in ("float", "int", "point"):
        raise ValueError(f"PARAMS[{name!r}]: 'unit' only fits numeric and point parameters")
    if kind == "float":
        if not _is_number(value):
            raise ValueError(f"PARAMS[{name!r}]: a float default must be a finite number")
        value = float(value)
    elif kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"PARAMS[{name!r}]: an int default must be a whole number")
    elif kind == "bool":
        if not isinstance(value, bool):
            raise ValueError(f"PARAMS[{name!r}]: a bool default must be True or False")
    elif kind == "text":
        if not isinstance(value, str):
            raise ValueError(f"PARAMS[{name!r}]: a text default must be text")
    elif kind == "colour":
        if not is_colour(value):
            raise ValueError(f"PARAMS[{name!r}]: a colour default must look like '#ff0000'")
    elif kind == "choice":
        if (
            not isinstance(choices_value, (tuple, list))
            or not choices_value
            or not all(isinstance(choice, str) for choice in choices_value)
        ):
            raise ValueError(f"PARAMS[{name!r}]: a choice needs a non-empty list of text 'choices'")
        if len(set(choices_value)) != len(choices_value) or value not in choices_value:
            raise ValueError(f"PARAMS[{name!r}]: the default must be one of its distinct choices")
        choices_value = tuple(choices_value)
    elif kind == "point":
        if not isinstance(value, (tuple, list)) or len(value) != 2 or not all(_is_number(v) for v in value):
            raise ValueError(f"PARAMS[{name!r}]: a point default must be a pair of finite numbers")
        value = tuple(float(v) for v in value)
    if kind in ("float", "int", "point"):
        coordinates = value if kind == "point" else (value,)
        if any((low is not None and v < low) or (high is not None and v > high) for v in coordinates):
            raise ValueError(f"PARAMS[{name!r}]: the default must be within its 'min' and 'max'")
    return PyParam(
        name,
        kind,
        value,
        low,
        high,
        label,
        unit,
        float(step) if step is not None else None,
        tuple(choices_value),
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


@dataclass(frozen=True)
class PyHandle:
    """A named point handle declared by ``HANDLES`` and backed by two numeric parameters."""

    label: str
    x: str
    y: str
    x_kind: PyKind
    y_kind: PyKind
    x_minimum: float | None = None
    x_maximum: float | None = None
    y_minimum: float | None = None
    y_maximum: float | None = None
    point: str | None = None
    point_minimum: float | None = None
    point_maximum: float | None = None
    unit: str = ""
    step: float = 0.25


@lru_cache(maxsize=256)
def read_handles(code: str) -> tuple[PyHandle, ...]:
    """Read ``HANDLES = {label: (x_param, y_param)}`` or ``{label: point_param}`` safely.

    Pair coordinates must be backed by numeric ``PARAMS``; a string target must be a point parameter.
    Invalid or incomplete declarations simply provide no handles, so editing a half-written object
    never executes or breaks its code.
    """
    try:
        tree = ast.parse(code, FILENAME)
        params = read_params(code)
    except (SyntaxError, ValueError, CodeProblem):
        return ()
    assignments = [
        node
        for node in tree.body
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        and any(isinstance(target, ast.Name) and target.id == "HANDLES" for target in _targets(node))
    ]
    if not assignments or assignments[-1].value is None:
        return ()
    try:
        declared = ast.literal_eval(assignments[-1].value)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return ()
    if not isinstance(declared, dict):
        return ()
    by_name = {param.name: param for param in params}
    numeric = {param.name: param for param in params if param.kind in ("float", "int")}
    out = []
    for label, target in declared.items():
        if not isinstance(label, str) or not label.strip():
            return ()
        if isinstance(target, str):
            point = by_name.get(target)
            if point is None or point.kind != "point":
                return ()
            out.append(
                PyHandle(
                    label,
                    target,
                    target,
                    "float",
                    "float",
                    point=target,
                    point_minimum=point.minimum,
                    point_maximum=point.maximum,
                    unit=point.unit,
                    step=point.step or 0.25,
                )
            )
            continue
        if (
            not isinstance(target, (tuple, list))
            or len(target) != 2
            or not all(isinstance(name, str) and name in numeric for name in target)
        ):
            return ()
        x, y = numeric[target[0]], numeric[target[1]]
        out.append(
            PyHandle(
                label,
                x.name,
                y.name,
                x.kind,
                y.kind,
                x.minimum,
                x.maximum,
                y.minimum,
                y.maximum,
                unit=x.unit if x.unit == y.unit else "",
                step=x.step if x.step is not None and x.step == y.step else 0.25,
            )
        )
    return tuple(out)


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


def trusts_everything() -> bool:
    """Is every Python object's code allowed to run in this process (``--trust-code``)?"""
    return _trust_everything


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
    those for code applied in the editor. With the user's **No time limit** switch on (ADR 0059) the
    code runs without a deadline.
    """
    if limits.unlimited():
        yield
        return
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
