"""Run to cursor (P13.3): a scene's code cut after the statement under the cursor - pure, no Qt, no Manim.

"Run to cursor" renders a code layer's scene only as far as the statement the user's cursor is on, so
a long scene can be checked a piece at a time. ``truncate`` returns the source with the later statements
of ``construct`` removed; the runner then draws what is on screen at that point.

The line numbers of everything are kept: the removed text becomes empty lines (not deleted), so an
error in the kept part, or in code after the scene, still names the right line. The cursor may be
anywhere in the ``construct`` body: on a statement, inside a block (``for``, ``with``, ``if``: the
whole top-level statement of ``construct`` that holds it is kept, since stopping in the middle of a
block would change what it means), or on a blank/comment line (the statements before it are kept).
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

from .source_text import NEWLINE, SourceText

BOM = "\ufeff"


@dataclass(frozen=True)
class RunToCursor:
    """``source`` cut after the statement at the cursor.

    ``last_line`` is the last line of the last statement kept (1-based); ``statements_kept`` and
    ``statements_total`` count the statements of ``construct`` (its docstring does not count).
    ``scene`` is the name of the scene class the cursor is in, the one to render.
    """

    source: str
    last_line: int
    statements_kept: int
    statements_total: int
    scene: str = ""


def truncate(source: str, line: int) -> RunToCursor | None:
    """``source`` with ``construct`` cut after the statement holding ``line`` (1-based), or None.

    None when the line is not in the body of a ``construct`` method of a top-level class, when the code
    has a syntax error, or when the line is before the first statement (the signature, the docstring).
    With several scenes the one holding ``line`` is used; the others are left as they are.
    """
    bom = len(BOM) if source.startswith(BOM) else 0
    text = source[bom:]
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None
    found = _construct_at(tree, line)
    if found is None:
        return None
    scene, method = found
    body = method.body
    skip = 1 if _is_docstring(body[0]) else 0
    statements = body[skip:]
    kept = [s for s in statements if s.lineno <= line]  # the ones that start at or before the cursor
    if not kept:
        return None
    last = kept[-1]
    if not (last.end_lineno and method.end_lineno):
        return None
    where = SourceText(text)
    cut_start = where.offset(last.end_lineno, last.end_col_offset or 0)
    cut_end = where.offset(method.end_lineno, method.end_col_offset or 0)
    if len(kept) < len(statements):
        rest = text[cut_start : where.line_end(cut_start)].strip()
        if not rest or rest.startswith("#"):
            cut_start = where.after_line(cut_start)  # keep the statement's own comment
        # else `a(); b()` on one line: cut right after the statement
        text = text[:cut_start] + _blank(text[cut_start:cut_end]) + text[cut_end:]
    return RunToCursor(
        source=source[:bom] + text,
        last_line=last.end_lineno,
        statements_kept=len(kept),
        statements_total=len(statements),
        scene=scene,
    )


def _construct_at(tree: ast.Module, line: int) -> tuple[str, ast.FunctionDef] | None:
    """The scene class and its ``construct`` whose body holds ``line`` (after the signature)."""
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or not node.lineno <= line <= (node.end_lineno or 0):
            continue
        for member in node.body:
            if isinstance(member, ast.FunctionDef) and member.name == "construct" and member.body:
                first = member.body[0].lineno
                if first <= line <= (member.end_lineno or 0):
                    return node.name, member
    return None


def _is_docstring(statement: ast.stmt) -> bool:
    return (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Constant)
        and isinstance(statement.value.value, str)
    )


def _blank(segment: str) -> str:
    """``segment`` with everything but its line endings removed (the line count stays)."""
    return "".join(match.group() for match in NEWLINE.finditer(segment))
