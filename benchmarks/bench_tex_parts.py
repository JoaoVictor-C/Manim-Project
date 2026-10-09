"""Part layers planning (B28): addressing parts of an equation without changing it.

Two ways to make one term of a MathTex addressable:

* Manim's ``substrings_to_isolate`` (isolates EVERY occurrence of each key);
* the editor's own span markers: a ``\\special{dvisvgm:raw <g id=...>}`` group
  around exactly the chosen span (what part layers use, ADR 0012).

For each, measures build time (fresh LaTeX each time, no disk-cache hit), the
pixel difference against the plain build at rest and mid-animation, and which
glyphs each part holds. Also checks spans right after ``^`` (bare and braced).
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path

import manim as m
import numpy as np

from manim_studio.core import adapter
from manim_studio.core.schema import Canvas
from manim_studio.render.cairo_export import make_camera, render_frame

ROOT = Path(__file__).resolve().parent.parent
adapter.configure(ROOT / ".cache" / "manim")

CASES = [
    (r"e^{i\pi} + 1 = 0", ["e^{i\\pi}", "+", "1", "=", "0"]),
    (r"a^2 + b^2 = c^2", ["a^2", "b^2", "c^2"]),
    (r"\int_0^1 x^2\,dx = \frac{1}{3}", ["x^2", "\\frac{1}{3}"]),
]
OPEN = "\\special{{dvisvgm:raw <g id='{}'>}}"
CLOSE = "\\special{dvisvgm:raw </g>}"
CAMERA = make_camera(Canvas(width_px=640, height_px=360))


def fresh_tag() -> str:
    """An invisible suffix that makes the LaTeX string new (no digits: they could match a key)."""
    letters = "".join(chr(97 + int(c, 16) % 26) for c in uuid.uuid4().hex[:8])
    return rf"\phantom{{\mathrm{{{letters}}}}}"


def render(mob: m.Mobject) -> np.ndarray:
    return render_frame(CAMERA, [mob.copy().move_to(m.ORIGIN)])[..., :3].astype(int)


def diff(a: m.Mobject, b: m.Mobject) -> str:
    d = np.abs(render(a) - render(b))
    return f"max {d.max()}, {int((d.max(axis=2) > 16).sum())} px"


def mid_animation_diff(a: m.Mobject, b: m.Mobject) -> str:
    worst = 0
    for kind in ("Write", "Create", "DrawBorderThenFill"):
        for alpha in (0.3, 0.6):
            frames = []
            for mob in (a, b):
                work = mob.copy()
                anim = getattr(m, kind)(work)
                anim.begin()
                anim.interpolate(alpha)
                frames.append(render_frame(CAMERA, [work])[..., :3].astype(int))
            worst = max(worst, int(np.abs(frames[0] - frames[1]).max()))
    return f"max {worst}"


def timed(build) -> tuple[m.Mobject, float]:
    t0 = time.perf_counter()
    mob = build()
    return mob, (time.perf_counter() - t0) * 1000


def glyph_indices(root: m.Mobject, group: m.Mobject) -> list[int]:
    index = {id(leaf): i for i, leaf in enumerate(root.family_members_with_points())}
    return [index[id(leaf)] for leaf in group.family_members_with_points()]


def main() -> None:
    m.logger.setLevel("WARNING")
    for tex, parts in CASES:
        tag = fresh_tag()
        whole, t_whole = timed(lambda: m.MathTex(tex + tag))  # noqa: B023
        isolated, t_isolated = timed(lambda: m.MathTex(tex + tag, substrings_to_isolate=parts))  # noqa: B023
        # Span markers around the FIRST occurrence of each key, nothing else.
        marked_tex, spans, cursor = tex, [], 0
        for i, key in enumerate(parts):
            start = marked_tex.find(key, cursor)
            mark = OPEN.format(f"p{i}")
            marked_tex = marked_tex[:start] + mark + key + CLOSE + marked_tex[start + len(key):]
            spans.append(f"p{i}")
            cursor = start + len(mark) + len(key) + len(CLOSE)
        marked, t_marked = timed(lambda: m.MathTex(marked_tex + tag))  # noqa: B023
        isolated_parts = {
            p: [len(isolated.id_to_vgroup_dict[i].family_members_with_points())
                for s, i in isolated.matched_strings_and_ids if s == p]
            for p in parts
        }
        print(tex)
        print(f"  build: whole {t_whole:.0f} ms, isolated {t_isolated:.0f} ms, span-marked {t_marked:.0f} ms")
        print(f"  glyphs: whole {len(whole.family_members_with_points())}, "
              f"isolated {len(isolated.family_members_with_points())}, marked {len(marked.family_members_with_points())}")
        print(f"  at rest vs whole: isolated {diff(whole, isolated)}; marked {diff(whole, marked)}")
        print(f"  mid Write/Create/DrawBorderThenFill vs whole: marked {mid_animation_diff(whole, marked)}")
        print(f"  substrings_to_isolate, glyphs per occurrence: {isolated_parts}")
        print(f"  span markers, glyph indices: "
              f"{ {p: glyph_indices(marked, marked.id_to_vgroup_dict[s]) for p, s in zip(parts, spans, strict=True)} }")

    tex, tag = r"\int_0^1 x^2\,dx = \frac{1}{3}", fresh_tag()
    whole = m.MathTex(tex + tag)
    i = tex.index("^1") + 1
    nested = m.MathTex(tex.replace("x^2", OPEN.format("xsq") + OPEN.format("x") + "x" + CLOSE + "^2" + CLOSE, 1) + tag)
    print("nested spans x^2 > x:", glyph_indices(nested, nested.id_to_vgroup_dict["xsq"]),
          glyph_indices(nested, nested.id_to_vgroup_dict["x"]), "at rest", diff(whole, nested))
    try:
        m.MathTex(tex[:i] + OPEN.format("sup") + tex[i] + CLOSE + tex[i + 1:] + tag)
        print("span right after ^: builds")
    except Exception as error:  # noqa: BLE001
        print(f"span right after ^: fails ({type(error).__name__})")
    braced = m.MathTex(tex[:i] + "{" + OPEN.format("sup") + tex[i] + CLOSE + "}" + tex[i + 1:] + tag)
    print("braced span after ^:", glyph_indices(braced, braced.id_to_vgroup_dict["sup"]), "at rest", diff(whole, braced))


if __name__ == "__main__":
    main()
