"""The only module that knows Manim's API.

Maps document specs to Manim mobjects and clip kinds to Manim animations, and
declares which clip kinds each mobject type supports. Everything that depends
on Manim internals is meant to live here so a Manim upgrade touches one file.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import manim as m
from manim.utils import rate_functions

from ..logging_config import get_logger
from .schema import ClipCategory, Easing, Spec

log = get_logger(__name__)


def configure(cache_dir: Path) -> None:
    """Point Manim's caches (Tex SVGs, text) at ``cache_dir`` and make LaTeX findable.

    MiKTeX aborts when PATH contains an entry that is a file instead of a
    directory, so such entries are dropped for this process.
    """
    m.config.media_dir = str(cache_dir)
    entries = [p for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    entries = [p for p in entries if not os.path.isfile(p)]
    miktex = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/MiKTeX/miktex/bin/x64"
    if miktex.is_dir() and str(miktex) not in entries:
        entries.append(str(miktex))
    os.environ["PATH"] = os.pathsep.join(entries)
    latex = shutil.which("latex")
    log.info("manim cache=%s latex=%s", cache_dir, latex or "NOT FOUND (MathTex/Tex unavailable)")


# --- mobjects ---------------------------------------------------------------

_SHAPES = {"Circle", "Square", "Rectangle", "Triangle", "Line", "Arrow", "Dot", "Star"}
_TEXT = {"Text", "MathTex", "Tex"}
_IMAGE = {"ImageMobject"}

MOBJECT_TYPES: dict[str, type] = {name: getattr(m, name) for name in sorted(_SHAPES | _TEXT | _IMAGE)}


def build_mobject(spec: Spec) -> m.Mobject:
    """Build a mobject centred on the origin; the layer transform places it."""
    cls = MOBJECT_TYPES.get(spec.type)
    if cls is None:
        raise ValueError(f"unsupported mobject type {spec.type!r}")
    mob = _build_cached(spec.model_dump_json()).copy()
    return mob


@lru_cache(maxsize=256)
def _build_cached(spec_json: str) -> m.Mobject:
    spec = Spec.model_validate_json(spec_json)
    cls = MOBJECT_TYPES[spec.type]
    params = dict(spec.params)
    if spec.type in ("Text", "MathTex", "Tex"):
        mob = cls(params.pop("text", ""), **params)
    elif spec.type == "ImageMobject":
        mob = cls(params.pop("path"), **params)
    else:
        mob = cls(**params)
    _apply_style(mob, spec.style)
    mob.move_to(m.ORIGIN)
    return mob


def _apply_style(mob: m.Mobject, style: dict[str, Any]) -> None:
    if not style or not isinstance(mob, m.VMobject):
        return
    if "fill" in style or "fill_opacity" in style:
        mob.set_fill(style.get("fill"), opacity=style.get("fill_opacity"))
    if "stroke" in style or "stroke_width" in style or "stroke_opacity" in style:
        mob.set_stroke(
            style.get("stroke"),
            width=style.get("stroke_width"),
            opacity=style.get("stroke_opacity"),
        )


# --- easing ------------------------------------------------------------------


def rate_func(ease: Easing) -> Callable[[float], float]:
    if ease.bezier is not None:
        return cubic_bezier(*ease.bezier)
    name = ease.name or "linear"
    func = getattr(rate_functions, name, None)
    if not callable(func):
        raise ValueError(f"unknown rate function {name!r}")
    return func


def cubic_bezier(x1: float, y1: float, x2: float, y2: float) -> Callable[[float], float]:
    """CSS cubic-bezier(x1, y1, x2, y2) as a Manim rate function."""

    def coord(t: float, p1: float, p2: float) -> float:
        return 3 * (1 - t) ** 2 * t * p1 + 3 * (1 - t) * t**2 * p2 + t**3

    def dcoord(t: float, p1: float, p2: float) -> float:
        return 3 * (1 - t) ** 2 * p1 + 6 * (1 - t) * t * (p2 - p1) + 3 * t**2 * (1 - p2)

    def func(x: float) -> float:
        if x <= 0:
            return 0.0
        if x >= 1:
            return 1.0
        t = x
        for _ in range(8):  # Newton
            err = coord(t, x1, x2) - x
            d = dcoord(t, x1, x2)
            if abs(err) < 1e-7 or abs(d) < 1e-9:
                break
            t -= err / d
        lo, hi = 0.0, 1.0
        t = min(max(t, lo), hi)
        if abs(coord(t, x1, x2) - x) > 1e-5:  # bisection fallback
            t = x
            for _ in range(40):
                if coord(t, x1, x2) < x:
                    lo = t
                else:
                    hi = t
                t = (lo + hi) / 2
        return coord(t, y1, y2)

    return func


# --- clips -------------------------------------------------------------------


@dataclass(frozen=True)
class ClipKind:
    cls: type[m.Animation]
    category: ClipCategory
    introducer: bool = False  # layer becomes visible at clip start
    remover: bool = False  # layer disappears at clip end
    clamp_alpha: bool = True  # content/emphasis clips cannot overshoot


CLIP_KINDS: dict[str, ClipKind] = {
    "Create": ClipKind(m.Create, "content", introducer=True),
    "Uncreate": ClipKind(m.Uncreate, "content", remover=True),
    "Write": ClipKind(m.Write, "content", introducer=True),
    "Unwrite": ClipKind(m.Unwrite, "content", remover=True),
    "DrawBorderThenFill": ClipKind(m.DrawBorderThenFill, "content", introducer=True),
    "FadeIn": ClipKind(m.FadeIn, "content", introducer=True),
    "FadeOut": ClipKind(m.FadeOut, "content", remover=True),
    "GrowFromCenter": ClipKind(m.GrowFromCenter, "content", introducer=True),
    "SpinInFromNothing": ClipKind(m.SpinInFromNothing, "content", introducer=True),
    "ShrinkToCenter": ClipKind(m.ShrinkToCenter, "content", remover=True),
    "Indicate": ClipKind(m.Indicate, "emphasis"),
    "Wiggle": ClipKind(m.Wiggle, "emphasis"),
    "ApplyWave": ClipKind(m.ApplyWave, "emphasis"),
    "Transform": ClipKind(m.ReplacementTransform, "morph", clamp_alpha=False),
    "FadeTransform": ClipKind(m.FadeTransform, "morph", clamp_alpha=False),
    "TransformMatchingShapes": ClipKind(m.TransformMatchingShapes, "morph", clamp_alpha=False),
}

# Text-drawing clips need VMobjects; images only fade/grow.
_VECTOR_ONLY = {"Create", "Uncreate", "Write", "Unwrite", "DrawBorderThenFill", "Wiggle", "ApplyWave"}


def allowed_clip_kinds(mobject_type: str) -> list[str]:
    if mobject_type in _IMAGE:
        return [k for k in CLIP_KINDS if k not in _VECTOR_ONLY]
    return list(CLIP_KINDS)


def make_animation(
    kind: str,
    mobject: m.Mobject,
    ease: Easing | None,
    params: dict[str, Any],
    target: m.Mobject | None = None,
) -> m.Animation:
    info = CLIP_KINDS[kind]
    kwargs = dict(params)
    if ease is not None:
        kwargs["rate_func"] = rate_func(ease)
    if kind == "Wiggle":
        # Manim pivots each submobject around the *current* centre of the whole
        # mobject, which drifts as earlier submobjects move, so every frame depends
        # on the previous one. Pinning the pivot to the start makes it random-access.
        center = mobject.get_center()
        kwargs.setdefault("scale_about_point", center)
        kwargs.setdefault("rotate_about_point", center)
    # run_time is irrelevant: the evaluator owns the clock and passes alpha.
    if info.category == "morph":
        if target is None:
            raise ValueError(f"{kind} needs a target layer")
        anim = info.cls(mobject, target, **kwargs)
    else:
        anim = info.cls(mobject, **kwargs)
    if info.clamp_alpha:
        raw = anim.rate_func
        anim.rate_func = lambda x: min(1.0, max(0.0, raw(x)))
    return anim
