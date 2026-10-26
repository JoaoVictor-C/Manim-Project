"""B37 — axes and function graphs: what they cost and whether they scrub exactly.

Probes for P3b (graphs as child layers):

1. a whitelist expression compiler (``ast``: numbers, ``x``, + - * / ** and a
   few math functions) vs Python's ``eval`` on the same text: equal values,
   rejection of anything else, and compile/evaluate time;
2. building ``Axes`` without and with number labels (labels are LaTeX), cold
   (fresh Manim cache dir) and warm;
3. ``axes.plot`` of a function on the built axes;
4. Create on a graph and Transform between two graphs, played in order vs
   scrubbed in a shuffled order (max pixel diff).

Run: ``python benchmarks/bench_graphs.py``.
"""

from __future__ import annotations

import ast
import math
import random
import shutil
import sys
import tempfile
import time
from pathlib import Path

import manim as m
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

from manim_studio.core.engine import adapter
from manim_studio.render.cairo_export import make_camera, render_frame
from support import CANVAS, FRAMES

FUNCTIONS = {
    "sin": np.sin,
    "cos": np.cos,
    "tan": np.tan,
    "exp": np.exp,
    "log": np.log,
    "sqrt": np.sqrt,
    "abs": np.abs,
}
CONSTANTS = {"pi": math.pi, "e": math.e}
OPS = {ast.Add: np.add, ast.Sub: np.subtract, ast.Mult: np.multiply, ast.Div: np.divide, ast.Pow: np.power}


def compile_expression(text: str):
    """f(x) from text, or ValueError for anything outside the whitelist."""
    tree = ast.parse(text, mode="eval").body

    def build(node):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, (int, float))
            and not isinstance(node.value, bool)
        ):
            value = float(node.value)
            return lambda x: value
        if isinstance(node, ast.Name) and node.id == "x":
            return lambda x: x
        if isinstance(node, ast.Name) and node.id in CONSTANTS:
            value = CONSTANTS[node.id]
            return lambda x: value
        if isinstance(node, ast.BinOp) and type(node.op) in OPS:
            op, a, b = OPS[type(node.op)], build(node.left), build(node.right)
            return lambda x: op(a(x), b(x))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            a = build(node.operand)
            sign = -1.0 if isinstance(node.op, ast.USub) else 1.0
            return lambda x: sign * a(x)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in FUNCTIONS
            and len(node.args) == 1
            and not node.keywords
        ):
            fn, a = FUNCTIONS[node.func.id], build(node.args[0])
            return lambda x: fn(a(x))
        raise ValueError(f"not allowed: {ast.dump(node)[:40]}")

    return build(tree)


def probe_expressions() -> None:
    xs = np.linspace(-5, 5, 1001)
    worst = 0.0
    for text in ("sin(x)", "x**2/10 - 1", "exp(-x**2)*cos(3*x)", "sqrt(abs(x)) + pi", "-x + e"):
        start = time.perf_counter()
        f = compile_expression(text)
        compile_ms = (time.perf_counter() - start) * 1000
        start = time.perf_counter()
        got = f(xs)
        eval_ms = (time.perf_counter() - start) * 1000
        ref = eval(text, {"__builtins__": {}}, {**FUNCTIONS, **CONSTANTS, "x": xs})
        worst = max(worst, float(np.abs(got - ref).max()))
        print(f"  {text:24s} compile {compile_ms:5.2f} ms  1001 points {eval_ms:5.2f} ms")
    print(f"  max |whitelist - eval| = {worst:.1e}")
    for bad in (
        "__import__('os')",
        "x.__class__",
        "open('f')",
        "[x for x in ()]",
        "lambda: 1",
        "x if x else 1",
    ):
        try:
            compile_expression(bad)
            print(f"  ACCEPTED (bad): {bad}")
        except (ValueError, SyntaxError):
            pass
    print("  rejected: imports, attributes, calls outside the list, comprehensions, lambdas, conditionals")


def timed_build(**kwargs) -> tuple[m.Axes, float]:
    start = time.perf_counter()
    axes = m.Axes(**kwargs)
    axes.move_to(m.ORIGIN)
    return axes, (time.perf_counter() - start) * 1000


def probe_axes() -> m.Axes:
    plain = dict(x_range=[-5, 5, 1], y_range=[-3, 3, 1], x_length=10, y_length=6)
    numbered = dict(plain, axis_config={"include_numbers": True})
    _, cold_plain = timed_build(**plain)
    root = Path(__file__).resolve().parents[1] / ".cache"
    tmp = Path(tempfile.mkdtemp(dir=root, prefix="bench-axes-"))  # not %TEMP%: MiKTeX and 8.3 paths
    adapter.configure(tmp)  # an empty Manim cache: the numbers' LaTeX is compiled
    _, cold_numbers = timed_build(**numbered)
    _, warm_numbers = timed_build(**numbered)
    shutil.rmtree(tmp, ignore_errors=True)
    adapter.configure(Path(__file__).resolve().parents[1] / ".cache" / "manim")
    print(
        f"  Axes plain {cold_plain:.0f} ms; with numbers cold {cold_numbers:.0f} ms, warm {warm_numbers:.0f} ms"
    )
    axes, _ = timed_build(**plain)
    return axes


def probe_plot(axes: m.Axes) -> tuple[m.VMobject, m.VMobject]:
    f, g = compile_expression("sin(x)"), compile_expression("x**2/10 - 1")
    start = time.perf_counter()
    one = axes.plot(lambda x: float(f(x)), x_range=[-5, 5], color=m.BLUE)
    plot_ms = (time.perf_counter() - start) * 1000
    two = axes.plot(lambda x: float(g(x)), x_range=[-5, 5], color=m.YELLOW)
    print(f"  axes.plot sin(x) on [-5, 5]: {plot_ms:.1f} ms, {len(one.points)} points")
    return one, two


def probe_random_access(axes: m.Axes, one: m.VMobject, two: m.VMobject) -> None:
    camera = make_camera(CANVAS)
    for name, make in (
        ("Create", lambda: m.Create(one.copy())),
        ("Transform", lambda: m.Transform(one.copy(), two.copy())),
    ):
        anim = make()
        anim.begin()
        reference = []
        for t in FRAMES:
            anim.interpolate(t)
            reference.append(render_frame(camera, [axes, anim.mobject]))
        scrub = make()
        scrub.begin()
        worst = 0
        for i in random.Random(0).sample(range(len(FRAMES)), len(FRAMES)):
            scrub.interpolate(FRAMES[i])
            worst = max(
                worst,
                int(np.abs(render_frame(camera, [axes, scrub.mobject]).astype(int) - reference[i]).max()),
            )
        visible = int(
            np.abs(reference[len(FRAMES) // 2].astype(int) - render_frame(camera, [axes]).astype(int)).max()
        )
        print(f"  {name:9s} scrub diff {worst}  (the graph is visible: {visible} levels)")


def main() -> None:
    adapter.configure(Path(__file__).resolve().parents[1] / ".cache" / "manim")
    print("expressions")
    probe_expressions()
    print("axes")
    axes = probe_axes()
    print("plot")
    one, two = probe_plot(axes)
    print("random access")
    probe_random_access(axes, one, two)


if __name__ == "__main__":
    main()
