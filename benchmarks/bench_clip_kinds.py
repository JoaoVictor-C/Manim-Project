"""B35 — candidate clip kinds against the random-access rule (ADR 0002, ADR 0007).

For each candidate Manim animation and object type, frames are rendered three
ways and compared with the sequential reference (begin, interpolate in order,
as ``Scene.play`` does):

* fresh: a new animation begun for every frame, alpha set directly;
* scrub: one animation, alphas in a shuffled order.

"Overlay" kinds draw something besides the object (a rectangle, flash lines):
their frame is the object plus ``anim.mobject``, as a scene that already shows
the object would draw it. Also reported: whether the object is unchanged at
alpha 1 (emphasis), and the cost of begin + one frame.

Run: ``python benchmarks/bench_clip_kinds.py``.
"""

from __future__ import annotations

import random
import sys
import time
from pathlib import Path

import manim as m
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

from manim_studio.core import adapter  # noqa: E402
from manim_studio.render.cairo_export import make_camera, render_frame  # noqa: E402
from support import CANVAS, FRAMES, MATH, SQUARE, TEXT  # noqa: E402

CANDIDATES: dict[str, tuple[type, dict, bool]] = {  # kind: (class, kwargs, overlay)
    "GrowFromEdge": (m.GrowFromEdge, {"edge": m.DOWN}, False),
    "GrowFromPoint": (m.GrowFromPoint, {"point": m.ORIGIN}, False),
    "SpiralIn": (m.SpiralIn, {}, False),
    "FadeIn(shift)": (m.FadeIn, {"shift": m.UP}, False),
    "FadeOut(shift)": (m.FadeOut, {"shift": m.DOWN}, False),
    "AddTextLetterByLetter": (m.AddTextLetterByLetter, {}, False),
    "RemoveTextLetterByLetter": (m.RemoveTextLetterByLetter, {}, False),
    "Blink": (m.Blink, {}, False),
    "Circumscribe": (m.Circumscribe, {}, True),
    "Flash": (m.Flash, {}, True),
    "FocusOn": (m.FocusOn, {}, True),
    "Broadcast": (m.Broadcast, {}, True),
    "ShowPassingFlash": (m.ShowPassingFlash, {}, False),
    "Indicate(color)": (m.Indicate, {"color": m.YELLOW, "scale_factor": 1.5}, False),
}
MORPHS = {
    "ClockwiseTransform": m.ClockwiseTransform,
    "CounterclockwiseTransform": m.CounterclockwiseTransform,
    "FadeTransformPieces": m.FadeTransformPieces,
}


def frame(camera, mob, anim, overlay: bool) -> np.ndarray:
    return render_frame(camera, [mob, anim.mobject] if overlay else [anim.mobject])


def check(cls, kwargs, spec, overlay: bool) -> str:
    camera = make_camera(CANVAS)
    try:
        mob = adapter.build_mobject(spec)
        anim = cls(mob, **kwargs)
        start = time.perf_counter()
        anim.begin()
        anim.interpolate(0.5)
        cost = (time.perf_counter() - start) * 1000
        anim.interpolate(0.0)
        reference = []
        for t in FRAMES:
            anim.interpolate(t)
            reference.append(frame(camera, mob, anim, overlay))
        anim.interpolate(1.0)
        anim.finish()
        unchanged = np.allclose(
            mob.family_members_with_points()[0].points, adapter.build_mobject(spec).family_members_with_points()[0].points
        ) if mob.family_members_with_points() else None
    except Exception as exc:  # noqa: BLE001 - a probe: report and go on
        return f"error: {type(exc).__name__}: {str(exc)[:60]}"
    worst_fresh = 0
    for i, t in enumerate(FRAMES):
        mob2 = adapter.build_mobject(spec)
        a2 = cls(mob2, **kwargs)
        a2.begin()
        a2.interpolate(t)
        worst_fresh = max(worst_fresh, int(np.abs(frame(camera, mob2, a2, overlay).astype(int) - reference[i]).max()))
    mob3 = adapter.build_mobject(spec)
    a3 = cls(mob3, **kwargs)
    a3.begin()
    order = random.Random(0).sample(range(len(FRAMES)), len(FRAMES))
    worst_scrub = 0
    for i in order:
        a3.interpolate(FRAMES[i])
        worst_scrub = max(worst_scrub, int(np.abs(frame(camera, mob3, a3, overlay).astype(int) - reference[i]).max()))
    verdict = "ok" if worst_fresh <= 1 and worst_scrub <= 1 else "FAIL"
    return f"{verdict} fresh {worst_fresh:3d} scrub {worst_scrub:3d} end-unchanged {unchanged} {cost:6.1f} ms"


def check_morph(cls) -> str:
    camera = make_camera(CANVAS)
    target = m.Circle(radius=1.5).set_fill("#ef4444", 0.5)
    source = adapter.build_mobject(SQUARE)
    anim = cls(source, target.copy())
    anim.begin()
    reference = []
    for t in FRAMES:
        anim.interpolate(t)
        reference.append(render_frame(camera, [anim.mobject]))
    a2 = cls(adapter.build_mobject(SQUARE), target.copy())
    a2.begin()
    worst = 0
    for i in random.Random(1).sample(range(len(FRAMES)), len(FRAMES)):
        a2.interpolate(FRAMES[i])
        worst = max(worst, int(np.abs(render_frame(camera, [a2.mobject]).astype(int) - reference[i]).max()))
    return f"{'ok' if worst <= 1 else 'FAIL'} scrub {worst:3d}"


def main() -> None:
    adapter.configure(Path(__file__).resolve().parents[1] / ".cache" / "manim")
    for kind, (cls, kwargs, overlay) in CANDIDATES.items():
        specs = (TEXT,) if "Letter" in kind else (SQUARE, TEXT, MATH)
        for spec in specs:
            print(f"{kind:26s} {spec.type:8s} {check(cls, kwargs, spec, overlay)}", flush=True)
    for kind, cls in MORPHS.items():
        print(f"{kind:26s} Square   {check_morph(cls)}", flush=True)


if __name__ == "__main__":
    main()
