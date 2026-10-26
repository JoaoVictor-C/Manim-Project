"""B48 — subtitles: what a line of text costs to build and draw, and how long lines wrap.

1. Building a subtitle line with Manim's Text (Pango): a new text (cold disk
   cache), the same text again in a new process's memory (warm disk cache), and
   from the in-memory cache.
2. Wrapping: the width of a long line, and building it as two lines.
3. Drawing a frame with a subtitle and its band at 1280x720.

Run: ``python benchmarks/bench_subtitles.py``.
"""

from __future__ import annotations

import statistics
import time
import uuid
from pathlib import Path

import manim as m

from manim_studio.core.engine import adapter
from manim_studio.core.model.schema import Canvas
from manim_studio.render.cairo_export import make_camera, render_frame


def timed(build, repeat: int = 1) -> float:
    samples = []
    for _ in range(repeat):
        start = time.perf_counter()
        build()
        samples.append((time.perf_counter() - start) * 1000)
    return statistics.median(samples)


def main() -> None:
    adapter.configure(Path(__file__).resolve().parents[1] / ".cache" / "manim")
    words = f"Here is a curve: f(x) = x² / 4. ({uuid.uuid4().hex[:6]})"
    cold = timed(lambda: m.Text(words, font_size=26))
    warm = timed(lambda: m.Text(words, font_size=26), repeat=5)  # Manim's own disk cache, new objects
    copy_ms = timed(lambda: m.Text(words, font_size=26).copy(), repeat=5)
    print(f"subtitle line: cold {cold:.0f} ms, disk-cached {warm:.1f} ms, + copy {copy_ms:.1f} ms")

    long = "h is the gap between P and Q. Shrinking it to zero gives the exact slope of the tangent."
    line = m.Text(long, font_size=26)
    print(f"a {len(long)}-character line is {line.width:.1f} units wide (frame 14.2); ", end="")
    two = timed(lambda: m.Text(long[:44] + "\n" + long[44:], font_size=26), repeat=3)
    print(f"as two lines {two:.1f} ms (cached after the first)")

    canvas = Canvas()
    camera = make_camera(canvas)
    band = m.Rectangle(width=13.6, height=0.72, fill_color="#020617", fill_opacity=0.72, stroke_width=0)
    band.move_to([0, -3.52, 0])
    text = m.Text(words, font_size=26).move_to(band)
    empty = timed(lambda: render_frame(camera, []), repeat=10)
    with_sub = timed(lambda: render_frame(camera, [band, text]), repeat=10)
    print(f"frame at 1280x720: empty {empty:.1f} ms, with a subtitle and band {with_sub:.1f} ms")


if __name__ == "__main__":
    main()
