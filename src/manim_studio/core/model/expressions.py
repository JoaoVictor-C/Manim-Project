"""Function expressions for graphs (P3b, ADR 0024): a whitelist over Python's syntax tree.

``check(text)`` says why an expression is not allowed (or None); ``compile_expression``
turns it into a vectorized ``f(x)``. Allowed: numbers, ``x``, ``pi``, ``e``,
``+ - * / **``, unary signs and the functions in ``FUNCTIONS``. Nothing else is
accepted and nothing is ever passed to ``eval`` - a project file cannot run code
through a graph (B37).
"""

from __future__ import annotations

import ast
import math
from collections.abc import Callable

import numpy as np

FUNCTIONS: dict[str, Callable[[np.ndarray], np.ndarray]] = {
    "sin": np.sin,
    "cos": np.cos,
    "tan": np.tan,
    "exp": np.exp,
    "log": np.log,
    "sqrt": np.sqrt,
    "abs": np.abs,
}
CONSTANTS = {"pi": math.pi, "e": math.e}
_OPS = {ast.Add: np.add, ast.Sub: np.subtract, ast.Mult: np.multiply, ast.Div: np.divide, ast.Pow: np.power}
MAX_LENGTH = 500


class ExpressionError(ValueError):
    """An expression outside the whitelist, or not an expression at all."""


def check(text: str) -> str | None:
    """Why ``text`` is not an allowed expression, or None."""
    try:
        compile_expression(text)
    except ExpressionError as exc:
        return str(exc)
    return None


def compile_expression(text: str) -> Callable[[np.ndarray], np.ndarray]:
    """``f(x)`` for an allowed expression; ``ExpressionError`` otherwise."""
    if not isinstance(text, str) or not text.strip():
        raise ExpressionError("write a function of x, e.g. sin(x)")
    if len(text) > MAX_LENGTH:
        raise ExpressionError(f"longer than {MAX_LENGTH} characters")
    try:
        tree = ast.parse(text.strip(), mode="eval").body
    except SyntaxError as exc:
        raise ExpressionError(f"not a formula ({exc.msg})") from None
    return _build(tree)


def _build(node: ast.AST) -> Callable[[np.ndarray], np.ndarray]:
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        value = float(node.value)
        return lambda x: np.full_like(x, value, dtype=float)
    if isinstance(node, ast.Name):
        if node.id == "x":
            return lambda x: x
        if node.id in CONSTANTS:
            value = CONSTANTS[node.id]
            return lambda x: np.full_like(x, value, dtype=float)
        raise ExpressionError(f"unknown name {node.id!r} (use x, pi, e)")
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        op, left, right = _OPS[type(node.op)], _build(node.left), _build(node.right)
        return lambda x: op(left(x), right(x))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        operand, sign = _build(node.operand), -1.0 if isinstance(node.op, ast.USub) else 1.0
        return lambda x: sign * operand(x)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        name = node.func.id
        if name not in FUNCTIONS:
            raise ExpressionError(f"unknown function {name!r} (use {', '.join(FUNCTIONS)})")
        if len(node.args) != 1 or node.keywords:
            raise ExpressionError(f"{name} takes one argument")
        fn, arg = FUNCTIONS[name], _build(node.args[0])
        return lambda x: fn(arg(x))
    raise ExpressionError(f"not allowed in a formula: {type(node).__name__}")


def evaluate(text: str, xs: np.ndarray) -> np.ndarray:
    """``f(xs)`` with numpy's warnings silenced: bad points become nan/inf (split later)."""
    f = compile_expression(text)
    with np.errstate(all="ignore"):
        return np.asarray(f(np.asarray(xs, dtype=float)), dtype=float)
