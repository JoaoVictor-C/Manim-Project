"""The outline of a piece of code (P13.3): its classes, functions and constants - pure, no Qt, no Manim.

The Code page shows this list beside the editor so the user can jump to a scene, to ``build`` or to a
constant. It is read from the syntax tree without running anything, so it works on code that has
not run (and gives nothing when the code has a syntax error, until the user fixes it).
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass

CONSTANT = re.compile(r"_*[A-Z][A-Z0-9_]*")


@dataclass(frozen=True)
class Symbol:
    """One entry of the outline. ``line`` and ``end_line`` are 1-based and inclusive.

    ``kind`` is ``"scene"`` (a class that is a Manim scene: a base class named ``...Scene``, or one that
    defines ``construct``), ``"class"``, ``"function"``, ``"method"``, ``"entry"`` (a function named
    ``build``, or a ``construct`` method or function: what runs), ``"params"`` (the top-level ``PARAMS``)
    or ``"constant"`` (a top-level UPPER_CASE name). A method has its class in ``parent``.
    """

    kind: str
    name: str
    line: int
    end_line: int
    parent: str = ""


def symbols(source: str) -> list[Symbol]:
    """The outline of ``source``, in the order of the lines; empty when it has a syntax error."""
    try:
        tree = ast.parse(source.lstrip("\ufeff"))
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return []
    out: list[Symbol] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            out.append(_symbol("scene" if _is_scene(node) else "class", node))
            for member in node.body:
                if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    kind = "entry" if member.name == "construct" else "method"
                    out.append(_symbol(kind, member, node.name))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            kind = "entry" if node.name in ("build", "construct") else "function"
            out.append(_symbol(kind, node))
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                for name in _names(target):
                    if name == "PARAMS":
                        out.append(_at("params", name, node))
                    elif CONSTANT.fullmatch(name):
                        out.append(_at("constant", name, node))
    out.sort(key=lambda s: s.line)  # stable: a class stays before its methods
    return out


def _symbol(
    kind: str, node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef, parent: str = ""
) -> Symbol:
    return Symbol(kind, node.name, node.lineno, node.end_lineno or node.lineno, parent)


def _at(kind: str, name: str, node: ast.stmt) -> Symbol:
    return Symbol(kind, name, node.lineno, node.end_lineno or node.lineno)


def _names(target: ast.expr) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        return [name for element in target.elts for name in _names(element)]
    return []


def _is_scene(node: ast.ClassDef) -> bool:
    for base in node.bases:
        name = base.id if isinstance(base, ast.Name) else base.attr if isinstance(base, ast.Attribute) else ""
        if name.endswith("Scene"):
            return True
    return any(
        isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)) and member.name == "construct"
        for member in node.body
    )
