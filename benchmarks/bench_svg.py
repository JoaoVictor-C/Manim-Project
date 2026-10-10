"""B40 — SVG import: build cost, what survives, and drawing clips under scrubbing.

Probes for P3e (SVGMobject layers):

1. build a small SVG (paths, a circle, a rect, fills and strokes) and a large one
   (400 paths) with Manim's ``SVGMobject``: time cold and on a second build;
2. colours and submobject count (does the drawing keep its own colours?);
3. Create, DrawBorderThenFill and Write played in order vs scrubbed in a shuffled
   order (max pixel diff), and whether the drawing is visible.

Run: ``python benchmarks/bench_svg.py``.
"""

from __future__ import annotations

import random
import sys
import tempfile
import time
from pathlib import Path

import manim as m
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

from manim_studio.core import adapter  # noqa: E402
from manim_studio.render.cairo_export import make_camera, render_frame  # noqa: E402
from support import CANVAS, FRAMES  # noqa: E402

SMALL = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
  <rect x="5" y="5" width="40" height="40" fill="#f97316" stroke="#111827" stroke-width="2"/>
  <circle cx="70" cy="30" r="20" fill="#22d3ee"/>
  <path d="M10 90 C 30 50, 70 50, 90 90" fill="none" stroke="#a3e635" stroke-width="4"/>
</svg>"""


def large(n: int) -> str:
    rng = random.Random(1)
    paths = "".join(
        f'<path d="M{rng.randint(0, 900)} {rng.randint(0, 900)} q {rng.randint(-50, 50)} {rng.randint(-50, 50)} '
        f'{rng.randint(-80, 80)} {rng.randint(-80, 80)} z" fill="#{rng.randint(0, 0xFFFFFF):06x}"/>'
        for _ in range(n)
    )
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000">{paths}</svg>'


def timed(path: Path) -> tuple[m.SVGMobject, float]:
    start = time.perf_counter()
    mob = m.SVGMobject(str(path))
    return mob, (time.perf_counter() - start) * 1000


def scrub(mob: m.Mobject, cls) -> tuple[int, int]:
    camera = make_camera(CANVAS)
    played = cls(mob.copy())
    played.begin()
    reference = []
    for t in FRAMES:
        played.interpolate(t)
        reference.append(render_frame(camera, [played.mobject]))
    scrubbed = cls(mob.copy())
    scrubbed.begin()
    worst = 0
    for i in random.Random(0).sample(range(len(FRAMES)), len(FRAMES)):
        scrubbed.interpolate(FRAMES[i])
        worst = max(worst, int(np.abs(render_frame(camera, [scrubbed.mobject]).astype(int) - reference[i]).max()))
    blank = render_frame(camera, [])
    visible = int(np.abs(reference[-1].astype(int) - blank.astype(int)).max())
    return worst, visible


def main() -> None:
    adapter.configure(Path(__file__).resolve().parents[1] / ".cache" / "manim")
    folder = Path(tempfile.mkdtemp(dir=Path(__file__).resolve().parents[1] / ".cache", prefix="bench-svg-"))
    small, big = folder / "small.svg", folder / "big.svg"
    small.write_text(SMALL, encoding="utf-8")
    big.write_text(large(400), encoding="utf-8")
    for path in (small, big):
        mob, cold = timed(path)
        _, again = timed(path)
        fills = {sub.get_fill_color().to_hex() for sub in mob.family_members_with_points()}
        print(f"{path.name}: {len(mob.family_members_with_points())} paths, build {cold:.0f} ms (again {again:.0f} ms), "
              f"{len(fills)} fill colours, height {mob.height:.2f}")
    mob, _ = timed(small)
    for cls in (m.Create, m.DrawBorderThenFill, m.Write, m.FadeIn):
        worst, visible = scrub(mob, cls)
        print(f"  {cls.__name__:18s} scrub diff {worst}, visible {visible}")


if __name__ == "__main__":
    main()
