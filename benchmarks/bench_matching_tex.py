"""TransformMatchingTex planning (B33): keyed matching between two equations.

Manim's ``TransformMatchingAbstractBase`` transforms parts with equal keys into
each other and fades the rest. The editor's version keys **part layers** by
their TeX and every other glyph by its **shape** (as ``TransformMatchingShapes``
does). Measures, on ``a^2 + b^2 = c^2`` -> ``a^2 = c^2 - b^2`` (parts a^2, b^2, c^2):

* whether glyph shape keys agree between two separately compiled equations
  (so ``+``, ``=`` can match without being parts);
* which pieces match, fade out and fade in;
* whether frames at random alphas equal frames played in order (random access);
* build (begin) and per-frame cost.
"""

from __future__ import annotations

import random
import time
from pathlib import Path

import manim as m
import numpy as np
from manim.animation.transform_matching_parts import TransformMatchingAbstractBase

from manim_studio.core import adapter
from manim_studio.core.schema import Canvas
from manim_studio.render.cairo_export import make_camera, render_frame

adapter.configure(Path(__file__).resolve().parent.parent / ".cache" / "manim")


def shape_key(mob: m.Mobject) -> int:
    """TransformMatchingShapes' key: the outline, centred and scaled to height 1."""
    copy = mob.copy().center().set(height=1)
    return hash(np.round(copy.points, 3).tobytes())


class Keyed(TransformMatchingAbstractBase):
    """Pieces arrive already grouped, each tagged with its key."""

    @staticmethod
    def get_mobject_parts(mobject):
        return mobject.submobjects

    @staticmethod
    def get_mobject_key(mobject):
        return mobject.match_key


def pieces(eq: m.Mobject, parts: dict[str, list[int]]) -> m.VGroup:
    leaves = eq.family_members_with_points()
    taken = {i for idx in parts.values() for i in idx}
    out = []
    for tex, idx in parts.items():
        group = m.VGroup(*(leaves[i] for i in idx))
        group.match_key = f"tex:{tex}"
        out.append(group)
    for i, leaf in enumerate(leaves):
        if i not in taken:
            group = m.VGroup(leaf)
            group.match_key = f"shape:{shape_key(leaf)}"
            out.append(group)
    return m.VGroup(*out)


def main() -> None:
    m.logger.setLevel("WARNING")
    eq1 = m.MathTex(r"a^2 + b^2 = c^2").shift(m.UP)
    eq2 = m.MathTex(r"a^2 = c^2 - b^2").shift(m.DOWN)
    # glyph indices of the terms (B28 marker groups): eq1 a^2 0-1, b^2 3-4, c^2 6-7; eq2 a^2, c^2, b^2
    p1 = {"a^2": [0, 1], "b^2": [3, 4], "c^2": [6, 7]}
    p2 = {"a^2": [0, 1], "c^2": [3, 4], "b^2": [6, 7]}
    plus1, eq_sign1 = eq1.family_members_with_points()[2], eq1.family_members_with_points()[5]
    eq_sign2, minus2 = eq2.family_members_with_points()[2], eq2.family_members_with_points()[5]
    print(
        "shape keys equal across equations: '=' ->",
        shape_key(eq_sign1) == shape_key(eq_sign2),
        "| '+' vs '-' ->",
        shape_key(plus1) == shape_key(minus2),
    )

    source, target = pieces(eq1.copy(), p1), pieces(eq2.copy(), p2)
    s_keys = {g.match_key for g in source}
    t_keys = {g.match_key for g in target}
    print("matched:", sorted(k[:12] for k in s_keys & t_keys))
    print("fade out:", len(s_keys - t_keys), "fade in:", len(t_keys - s_keys))

    camera = make_camera(Canvas(width_px=640, height_px=360))
    t0 = time.perf_counter()
    anim = Keyed(source, target)
    anim.begin()
    begin_ms = (time.perf_counter() - t0) * 1000
    alphas = [i / 30 for i in range(31)]
    sequential = {}
    t0 = time.perf_counter()
    for a in alphas:
        anim.interpolate(a)
        sequential[a] = render_frame(camera, [anim.mobject])
    frame_ms = (time.perf_counter() - t0) * 1000 / len(alphas)
    shuffled = alphas[:]
    random.Random(1).shuffle(shuffled)
    worst = 0
    for a in shuffled:
        anim.interpolate(a)
        worst = max(
            worst,
            int(np.abs(render_frame(camera, [anim.mobject]).astype(int) - sequential[a].astype(int)).max()),
        )
    anim.interpolate(1.0)
    final = render_frame(camera, [anim.mobject]).astype(int)
    reference = render_frame(camera, [eq2]).astype(int)
    print(f"begin {begin_ms:.1f} ms, interpolate+render {frame_ms:.1f} ms/frame")
    print(f"random order vs in order: max diff {worst}")
    print(
        f"alpha 1 vs the target equation: max diff {np.abs(final - reference).max()}, "
        f"mean {np.abs(final - reference).mean():.3f}"
    )


if __name__ == "__main__":
    main()
