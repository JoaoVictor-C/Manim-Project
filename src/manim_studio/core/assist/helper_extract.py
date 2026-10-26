"""Extract to helper (ADR 0058): move whole top-level functions and classes into a new helper.

``extract(source, name, ...)`` takes the functions and classes a selection covers (or the one under
the cursor), and returns the helper's text - those definitions, with the imports they use - and the
code without them, importing them back with ``from <name> import a, b`` at the top. It is
conservative: anything but whole top-level ``def`` and ``class`` statements is refused with a reason,
and so is a definition that uses a name staying in the code (it would fail in the helper), the scene
of a code layer and the ``build`` of a Python object. Read with the parser; nothing runs.

``defined_names(source)`` lists what a helper defines at its top level (for the Output). Pure.
"""

from __future__ import annotations

import ast
import builtins
from dataclasses import dataclass

from ..exchange.scene_import import scene_classes

DEFS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
WHOLE = "select whole top-level functions and classes, from their first line (or decorator) to their last"
# What the runners give user code without an import (code_runner.PRELUDE, the Python object's runner).
PROVIDED = {"np": "import numpy as np", "math": "import math"}
MANIM = "from manim import *"


class ExtractError(ValueError):
    """Why the selection cannot be extracted (said to the user as it is)."""


@dataclass(frozen=True)
class Extraction:
    helper_code: str  # the new helper's text
    code: str  # the code without the definitions, importing them from the helper
    names: tuple[str, ...]  # what was moved, in order


def extract(
    source: str,
    name: str,
    *,
    first: int | None = None,
    last: int | None = None,
    cursor: int = 1,
    origin: str = "",
) -> Extraction:
    """Move the top-level functions and classes on lines ``first``..``last`` (1-based, inclusive), or
    the one on line ``cursor`` when there is no selection, into helper ``name``. ``origin`` names the
    code in the helper's docstring. Raises ``ExtractError`` with the reason when it cannot."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        raise ExtractError("the code has a syntax error: fix it first") from None
    spans = [(_start(node), node.end_lineno or node.lineno, node) for node in tree.body]
    if first is None or last is None:
        chosen = [span for span in spans if span[0] <= cursor <= span[1]]
        if not chosen or not isinstance(chosen[0][2], DEFS):
            raise ExtractError("put the cursor in a top-level function or class, or " + WHOLE)
    else:
        if last < first:
            first, last = last, first
        chosen = [span for span in spans if span[1] >= first and span[0] <= last]
        if not chosen:
            raise ExtractError("the selection holds no function or class: " + WHOLE)
        for start, _end, node in chosen:
            if not isinstance(node, DEFS):
                raise ExtractError(f"line {start} is not a function or class: " + WHOLE)
        if chosen[0][0] < first or chosen[-1][1] > last:
            raise ExtractError(WHOLE)
    nodes = [node for _start_line, _end, node in chosen]
    names = tuple(node.name for node in nodes)
    scenes = set(scene_classes(source))
    for moved in names:
        if moved == "build":
            raise ExtractError("build(p) is the Python object itself: it stays in the code")
        if moved in scenes:
            raise ExtractError(f"{moved} is the scene of this code: it stays in the code layer")
    staying = _bound_at_top(node for node in tree.body if node not in nodes)
    used = _loads(nodes)
    clash = sorted((used & staying) - set(names))
    if clash:
        shown = ", ".join(clash[:3])
        raise ExtractError(f"it uses {shown}, which stays in the code: select {_it(clash)} too")

    lines = source.splitlines(keepends=True)
    begin, end = chosen[0][0], chosen[-1][1]
    moved_text = "".join(lines[begin - 1 : end]).rstrip() + "\n"
    helper_code = _helper_text(tree, source, nodes, used, moved_text, origin)

    rest = lines[: begin - 1] + lines[end:]
    rest = _squeeze_blanks(rest, begin - 1)
    at = _after_leading_imports(tree)  # before the cut: the definitions come after the imports
    statement = f"from {name} import {', '.join(names)}\n"
    head, tail = rest[:at], rest[at:]
    if head and not head[-1].endswith("\n"):
        head[-1] += "\n"
    if at == 0:
        code = statement + ("\n" if tail and tail[0].strip() else "") + "".join(tail)
    else:
        code = "".join(head) + statement + "".join(tail)
    return Extraction(helper_code, code, names)


def defined_names(source: str) -> list[str]:
    """The public names a module defines at its top level (functions, classes, assigned names), in
    order; imports are not counted. Empty when it does not parse."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return []
    out: list[str] = []
    for node in tree.body:
        for bound in sorted(_bound_at_top([node])):
            if not bound.startswith("_") and bound not in out:
                out.append(bound)
    return out


# -- internals ------------------------------------------------------------------------------------


def _start(node: ast.stmt) -> int:
    """A statement's first line, its decorators included."""
    decorators = getattr(node, "decorator_list", None) or []
    return min([node.lineno, *(d.lineno for d in decorators)])


def _it(names: list[str]) -> str:
    return "it" if len(names) == 1 else "them"


def _targets(target: ast.AST) -> set[str]:
    return {n.id for n in ast.walk(target) if isinstance(n, ast.Name)}


def _bound_at_top(nodes) -> set[str]:
    """The names these top-level statements bind, imports excepted (an import is copied, not lost)."""
    out: set[str] = set()
    for node in nodes:
        if isinstance(node, DEFS):
            out.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                out |= _targets(target)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign, ast.For, ast.AsyncFor)):
            out |= _targets(node.target)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if item.optional_vars is not None:
                    out |= _targets(item.optional_vars)
    return out


def _loads(nodes: list[ast.stmt]) -> set[str]:
    """The names these statements read that they do not bind themselves (roughly: their free names)."""
    loads: set[str] = set()
    bound: set[str] = set()
    for node in nodes:
        for inner in ast.walk(node):
            if isinstance(inner, ast.Name):
                (loads if isinstance(inner.ctx, ast.Load) else bound).add(inner.id)
            elif isinstance(inner, ast.arg):
                bound.add(inner.arg)
            elif isinstance(inner, DEFS):
                bound.add(inner.name)
            elif isinstance(inner, (ast.Import, ast.ImportFrom)):
                bound |= {alias.asname or alias.name.split(".")[0] for alias in inner.names}
            elif isinstance(inner, ast.ExceptHandler) and inner.name:
                bound.add(inner.name)
    return loads - bound


def _helper_text(
    tree: ast.Module, source: str, nodes: list[ast.stmt], used: set[str], moved: str, origin: str
) -> str:
    """The helper: a docstring, the imports the moved definitions use, then the definitions."""
    future: list[str] = []
    copied: list[str] = []
    resolved: set[str] = set()
    stars: list[str] = []
    for node in tree.body:
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        text = (ast.get_source_segment(source, node) or "").strip()
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            future.append(text)
            continue
        bound = {alias.asname or alias.name.split(".")[0] for alias in node.names}
        if "*" in bound:
            stars.append(text)
        elif bound & used:
            copied.append(text)
            resolved |= bound
    free = used - resolved - set(dir(builtins))
    prelude = [PROVIDED[n] for n in sorted(PROVIDED) if n in free and PROVIDED[n] not in copied]
    others = free - set(PROVIDED)
    if others:
        prelude.insert(0, MANIM)
        copied.extend(s for s in stars if s != MANIM)
    imports = [*future, *prelude, *(c for c in copied if c not in prelude)]
    where = f" from {origin}" if origin else ""
    head = f'"""Extracted{where}: {", ".join(n.name for n in nodes)}."""\n'
    body = "\n".join(imports)
    return head + ("\n" + body + "\n" if body else "") + "\n\n" + moved


def _squeeze_blanks(lines: list[str], at: int) -> list[str]:
    """At most two blank lines where the definitions were cut out (none at the very end)."""
    before = at
    while before > 0 and not lines[before - 1].strip():
        before -= 1
    after = at
    while after < len(lines) and not lines[after].strip():
        after += 1
    keep = 0 if before == 0 or after == len(lines) else min(after - before, 2)
    return lines[:before] + ["\n"] * keep + lines[after:]


def _after_leading_imports(tree: ast.Module) -> int:
    """The line after the module docstring and the imports at the start (0: the very top)."""
    at = 0
    for index, node in enumerate(tree.body):
        docstring = (
            index == 0
            and isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        )
        if docstring or isinstance(node, (ast.Import, ast.ImportFrom)):
            at = node.end_lineno or node.lineno
        else:
            break
    return at
