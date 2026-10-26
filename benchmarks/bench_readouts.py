"""B49 — value readouts and connectors: what a number that changes every frame costs.

1. Manim's DecimalNumber (one LaTeX glyph per character, cached on disk): building
   one, set_value to a new value, the first time and once its digits are cached.
2. Composing a number from cached glyph mobjects (copy + arrange) per frame.
3. A connector: a Line/Arrow between two points rebuilt per frame.

Run: ``python benchmarks/bench_readouts.py``.
"""

from __future__ import annotations

import statistics
import time
from pathlib import Path

import manim as m

from manim_studio.core.engine import adapter


def timed(build, repeat: int = 1) -> float:
    samples = []
    for _ in range(repeat):
        start = time.perf_counter()
        build()
        samples.append((time.perf_counter() - start) * 1000)
    return statistics.median(samples)


def main() -> None:
    adapter.configure(Path(__file__).resolve().parents[1] / ".cache" / "manim")
    first = timed(lambda: m.DecimalNumber(3.14159, num_decimal_places=2))
    again = timed(lambda: m.DecimalNumber(2.71828, num_decimal_places=2), repeat=5)
    number = m.DecimalNumber(0.0, num_decimal_places=2)
    values = iter(range(1, 10_000))
    set_ms = timed(lambda: number.set_value(next(values) / 7), repeat=30)
    print(f"DecimalNumber: first {first:.0f} ms, another value {again:.1f} ms, set_value {set_ms:.1f} ms")

    glyphs = {ch: m.MathTex(ch) for ch in "0123456789.-"}

    def compose(text: str) -> m.VGroup:
        return m.VGroup(*(glyphs[ch].copy() for ch in text)).arrange(m.RIGHT, buff=0.05)

    compose_ms = timed(lambda: compose(f"{next(values) / 7:.2f}"), repeat=30)
    print(f"number composed from cached glyphs: {compose_ms:.2f} ms per frame")

    line_ms = timed(lambda: m.Line([-2, -1, 0], [2, 1.5, 0]), repeat=50)
    arrow_ms = timed(lambda: m.Arrow([-2, -1, 0], [2, 1.5, 0], buff=0.2), repeat=50)
    print(f"connector per frame: Line {line_ms:.2f} ms, Arrow {arrow_ms:.2f} ms")


if __name__ == "__main__":
    main()
