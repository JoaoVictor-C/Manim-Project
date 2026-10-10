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
from typing import Any, Literal

import manim as m
import numpy as np
from manim.animation.transform_matching_parts import TransformMatchingAbstractBase
from manim.utils import rate_functions

from ..logging_config import get_logger
from . import parts
from .schema import (
    CLIP_KIND_INFO,
    CODE_TYPES,
    DIRECTIONS,
    RASTER_TYPES,
    TEXT_TYPES,
    Easing,
    Spec,
    clip_params,
)

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


def cache_dir() -> Path:
    """Where Manim caches built objects (set by ``configure``; shared with the build worker)."""
    return Path(m.config.media_dir)


# --- patch: never reuse a half-written LaTeX SVG (ADR 0007) ---------------------
#
# Manim reuses ``<hash>.svg`` whenever the file exists. A process killed while
# dvisvgm writes it (a build worker past its timeout, a cancelled render) leaves
# a truncated file that would then fail that formula forever ("IndexError: list
# index out of range" while parsing). A complete SVG ends with ``</svg>``; anything
# else is deleted and compiled again.

from manim.mobject.text import tex_mobject as _tex_mobject  # noqa: E402
from manim.utils import tex_file_writing as _tex_files  # noqa: E402

_manim_tex_to_svg_file = _tex_files.tex_to_svg_file


def _complete_svg(path: Path) -> bool:
    try:
        with path.open("rb") as file:
            file.seek(max(0, path.stat().st_size - 64))
            return file.read().rstrip().endswith(b"</svg>")
    except OSError:
        return False


def _tex_to_svg_file(expression, environment=None, tex_template=None):
    template = tex_template if tex_template is not None else m.config["tex_template"]
    svg = _tex_files.generate_tex_file(expression, environment, template).with_suffix(".svg")
    if svg.exists() and not _complete_svg(svg):
        log.warning("discarding an incomplete cached LaTeX render: %s", svg.name)
        svg.unlink(missing_ok=True)
    return _manim_tex_to_svg_file(expression, environment, tex_template)


_tex_files.tex_to_svg_file = _tex_to_svg_file
_tex_mobject.tex_to_svg_file = _tex_to_svg_file


# --- mobjects ---------------------------------------------------------------

_SHAPES = {"Circle", "Square", "Rectangle", "Triangle", "Line", "Arrow", "Dot", "Star"}

MOBJECT_TYPES: dict[str, type] = {
    name: getattr(m, name) for name in sorted(_SHAPES | TEXT_TYPES | RASTER_TYPES)
}

ParamKind = Literal["float", "int", "text", "choice", "point", "path"]


@dataclass(frozen=True)
class Param:
    """One constructor parameter the properties panel exposes (S2 plan)."""

    name: str
    kind: ParamKind
    default: Any
    label: str = ""
    minimum: float | None = None
    maximum: float | None = None
    step: float = 0.1
    choices: tuple[str, ...] = ()
    multiline: bool = False  # long text (LaTeX) gets a text box

    @property
    def title(self) -> str:
        return self.label or self.name.replace("_", " ").capitalize()


MANIM_VERSION = m.__version__
CODE_STARTER = """class Orbit(Scene):
    def construct(self):
        t = ValueTracker(0)
        dot = Dot(color=YELLOW).add_updater(
            lambda d: d.move_to([2 * np.cos(t.get_value()), 2 * np.sin(t.get_value()), 0])
        )
        self.add(TracedPath(dot.get_center, stroke_color=YELLOW, stroke_width=4), dot)
        self.play(t.animate.set_value(TAU), run_time=3, rate_func=linear)
"""

_SIZE = {"minimum": 0.01, "maximum": 50.0}
_FONT_SIZE = Param("font_size", "float", 48.0, "Font size", minimum=4, maximum=400, step=1)

# Hand-curated: what each object type lets the user change. Keys are Spec.params
# names; "text" and "path" are passed positionally by _build_cached. Anything not
# listed is still accepted from JSON but not shown. Style (fill/stroke) and the
# layer transform are separate.
MOBJECT_PARAMS: dict[str, tuple[Param, ...]] = {
    "Circle": (Param("radius", "float", 1.0, **_SIZE),),
    "Square": (Param("side_length", "float", 2.0, "Side length", **_SIZE),),
    "Rectangle": (Param("width", "float", 4.0, **_SIZE), Param("height", "float", 2.0, **_SIZE)),
    "Triangle": (),
    "Star": (
        Param("n", "int", 5, "Points", minimum=3, maximum=24, step=1),
        Param("outer_radius", "float", 1.0, "Radius", **_SIZE),
    ),
    "Dot": (Param("radius", "float", 0.08, minimum=0.01, maximum=5.0, step=0.01),),
    "Line": (Param("start", "point", (-1.0, 0.0)), Param("end", "point", (1.0, 0.0))),
    "Arrow": (
        Param("start", "point", (-1.0, 0.0)),
        Param("end", "point", (1.0, 0.0)),
        Param("buff", "float", 0.25, "Gap at ends", minimum=0.0, maximum=5.0, step=0.05),
    ),
    "Text": (
        Param("text", "text", "Text"),
        _FONT_SIZE,
        Param("font", "text", "", "Font (blank = default)"),
        Param("weight", "choice", "NORMAL", choices=("NORMAL", "BOLD")),
        Param("slant", "choice", "NORMAL", choices=("NORMAL", "ITALIC")),
    ),
    "MathTex": (Param("text", "text", r"e^{i\pi} + 1 = 0", "LaTeX (math)", multiline=True), _FONT_SIZE),
    "Tex": (Param("text", "text", r"Hello \LaTeX", "LaTeX (text)", multiline=True), _FONT_SIZE),
    "ImageMobject": (Param("path", "path", "", "Image file"),),
    # A code layer (ADR 0019): one Scene subclass; `from manim import *` and numpy as np are implied.
    "Code": (Param("code", "text", CODE_STARTER, "Manim code (one Scene)", multiline=True),),
}

# The object library (S2 plan): menu sections in order.
LIBRARY: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Shapes", ("Circle", "Square", "Rectangle", "Triangle", "Star", "Dot", "Line", "Arrow")),
    ("Text", ("Text", "MathTex", "Tex")),
    ("Media", ("ImageMobject",)),
    ("Python", ("Code",)),
)

_REQUIRED = {"text", "path", "code"}  # always written to the spec


def default_spec(type_name: str, **params: Any) -> Spec:
    """A new object of ``type_name`` as the library creates it."""
    if type_name not in MOBJECT_PARAMS:
        raise ValueError(f"unsupported mobject type {type_name!r}")
    required = {p.name: p.default for p in MOBJECT_PARAMS[type_name] if p.name in _REQUIRED}
    return Spec(type=type_name, params={**required, **params})


def param_value(spec: Spec, param: Param) -> Any:
    """The value the object is built with: the spec's, else the registry default."""
    value = spec.params.get(param.name, param.default)
    return tuple(value) if param.kind == "point" else value


def build_mobject(spec: Spec) -> m.Mobject:
    """Build a mobject centred on the origin; the layer transform places it."""
    if spec.type in CODE_TYPES:
        raise ValueError("code layers are rendered by the code runner, not built (ADR 0019)")
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
    for param in MOBJECT_PARAMS.get(spec.type, ()):
        if param.kind == "point" and param.name in params:
            x, y = params[param.name][:2]
            params[param.name] = (x, y, 0.0)  # documents are 2D
    spans = params.pop(parts.SPANS_PARAM, None)
    if spec.type in TEXT_TYPES:
        text = params.pop("text", "")
        mob = cls(parts.mark(text, spans) if spans else text, **params)
    elif spec.type == "ImageMobject":
        mob = cls(params.pop("path"), **params)
    else:
        mob = cls(**params)
    _apply_style(mob, spec.style)
    mob.move_to(m.ORIGIN)
    return mob


def part_regions(spec: Spec) -> list[tuple[int, ...]]:
    """Glyph indices (into ``family_members_with_points()``) of each marker group.

    ``spec`` carries ``parts.SPANS_PARAM``; entry ``i`` belongs to the part at
    ``Resolution.order[i]``. Indices hold for every copy of the built object.
    """
    return list(_regions_cached(spec.model_dump_json()))


@lru_cache(maxsize=256)
def _regions_cached(spec_json: str) -> tuple[tuple[int, ...], ...]:
    mob = _build_cached(spec_json)
    count = len(Spec.model_validate_json(spec_json).params.get(parts.SPANS_PARAM, ()))
    index = {id(leaf): i for i, leaf in enumerate(mob.family_members_with_points())}
    regions = []
    for i in range(count):
        group = mob.id_to_vgroup_dict.get(parts.marker_id(i))
        leaves = group.family_members_with_points() if group is not None else []
        regions.append(tuple(sorted(index[id(leaf)] for leaf in leaves if id(leaf) in index)))
    return tuple(regions)


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


# Offered in the properties panel; any Manim rate function name is accepted from JSON.
EASE_NAMES: tuple[str, ...] = (
    "smooth",
    "linear",
    "rush_into",
    "rush_from",
    "double_smooth",
    "there_and_back",
    "ease_in_sine",
    "ease_out_sine",
    "ease_in_out_sine",
    "ease_in_cubic",
    "ease_out_cubic",
    "ease_in_out_cubic",
    "ease_in_back",
    "ease_out_back",
    "ease_in_out_back",
    "ease_out_bounce",
    "ease_out_elastic",
)

# CSS-style curves (x1, y1, x2, y2), as in browsers' timing functions.
BEZIER_PRESETS: dict[str, tuple[float, float, float, float]] = {
    "CSS ease": (0.25, 0.1, 0.25, 1.0),
    "CSS ease-in": (0.42, 0.0, 1.0, 1.0),
    "CSS ease-out": (0.0, 0.0, 0.58, 1.0),
    "CSS ease-in-out": (0.42, 0.0, 0.58, 1.0),
    "Overshoot": (0.34, 1.56, 0.64, 1.0),
}

# Cubic beziers fitted to the named eases (B27, benchmarks/fit_ease_beziers.py): where
# the curve editor starts when a named ease is edited. Max error <= 0.025; eases that
# no cubic bezier can follow (double_smooth, ease_out_bounce, ease_out_elastic,
# there_and_back) are absent, so the editor refuses them.
EASE_BEZIER_FITS: dict[str, tuple[float, float, float, float]] = {
    "linear": (0.0, 0.0, 1.0, 1.0),
    "smooth": (0.615, -0.016, 0.385, 1.016),
    "rush_into": (0.557, 0.034, 0.7, 0.229),
    "rush_from": (0.3, 0.771, 0.444, 0.966),
    "ease_in_sine": (0.392, -0.008, 0.76, 0.631),
    "ease_out_sine": (0.241, 0.37, 0.609, 1.008),
    "ease_in_out_sine": (0.362, -0.002, 0.638, 1.002),
    "ease_in_cubic": (0.416, -0.014, 0.7, 0.108),
    "ease_out_cubic": (0.3, 0.892, 0.584, 1.013),
    "ease_in_out_cubic": (0.616, -0.058, 0.384, 1.058),
    "ease_in_back": (0.433, -0.063, 0.682, -0.452),
    "ease_out_back": (0.318, 1.452, 0.567, 1.064),
    "ease_in_out_back": (0.742, -0.518, 0.258, 1.518),
}


def ease_as_bezier(ease: Easing | None) -> tuple[float, float, float, float] | None:
    """The bezier the curve editor starts from, or None if the ease cannot be edited as one."""
    if ease is None:
        return None
    if ease.bezier is not None:
        return tuple(ease.bezier)
    return EASE_BEZIER_FITS.get(ease.name or "linear")


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


# Kind metadata (category, introducer/remover, vector-only) is pure data in
# schema.CLIP_KIND_INFO; this table only maps each kind to its Manim class.
def shape_key(mob: m.Mobject) -> str:
    """A glyph's identity by outline: centred and scaled to height 1 (as TransformMatchingShapes)."""
    copy = mob.copy().center()
    if copy.height > 0:
        copy.set(height=1)
    return f"shape:{hash(np.round(copy.points, 3).tobytes())}"


def keyed_pieces(
    source: list[tuple[str | None, m.Mobject]], target: list[tuple[str | None, m.Mobject]]
) -> tuple[m.VGroup, m.VGroup]:
    """The pieces TransformMatchingTex transforms, keyed in two passes (ADR 0020).

    ``source`` and ``target`` list ``(part TeX or None, glyphs)``. A part stays
    one piece keyed ``tex:<TeX>`` only if the same TeX exists on the other side;
    every other glyph becomes its own piece keyed by its shape.
    """
    common = {tex for tex, _ in source if tex} & {tex for tex, _ in target if tex}

    def pieces(groups: list[tuple[str | None, m.Mobject]]) -> m.VGroup:
        out = m.VGroup()
        for tex, glyphs in groups:
            if tex in common:
                piece = m.VGroup(*glyphs.family_members_with_points())
                piece.match_key = f"tex:{tex}"
                out.add(piece)
                continue
            for glyph in glyphs.family_members_with_points():
                piece = m.VGroup(glyph)
                piece.match_key = shape_key(glyph)
                out.add(piece)
        return out

    return pieces(source), pieces(target)


class KeyedTransformMatching(TransformMatchingAbstractBase):
    """TransformMatchingTex on pieces that already carry their keys (``keyed_pieces``)."""

    @staticmethod
    def get_mobject_parts(mobject: m.Mobject) -> list[m.Mobject]:
        return list(mobject.submobjects)

    @staticmethod
    def get_mobject_key(mobject: m.Mobject) -> str:
        return mobject.match_key


ANIMATION_CLASSES: dict[str, type[m.Animation]] = {
    "Create": m.Create,
    "Uncreate": m.Uncreate,
    "Write": m.Write,
    "Unwrite": m.Unwrite,
    "DrawBorderThenFill": m.DrawBorderThenFill,
    "FadeIn": m.FadeIn,
    "FadeOut": m.FadeOut,
    "GrowFromCenter": m.GrowFromCenter,
    "SpinInFromNothing": m.SpinInFromNothing,
    "GrowFromEdge": m.GrowFromEdge,
    "SpiralIn": m.SpiralIn,
    "AddTextLetterByLetter": m.AddTextLetterByLetter,
    "RemoveTextLetterByLetter": m.RemoveTextLetterByLetter,
    "ShrinkToCenter": m.ShrinkToCenter,
    "Indicate": m.Indicate,
    "Wiggle": m.Wiggle,
    "ApplyWave": m.ApplyWave,
    "Circumscribe": m.Circumscribe,  # a Succession: made random-access below (ADR 0022)
    "Flash": m.Flash,
    "FocusOn": m.FocusOn,
    "Transform": m.ReplacementTransform,  # ADR 0005: the source hands off to the target
    "ClockwiseTransform": m.ClockwiseTransform,
    "CounterclockwiseTransform": m.CounterclockwiseTransform,
    "FadeTransform": m.FadeTransform,
    "FadeTransformPieces": m.FadeTransformPieces,
    "TransformMatchingShapes": m.TransformMatchingShapes,
    "TransformMatchingTex": KeyedTransformMatching,  # fed keyed_pieces by the evaluator (ADR 0020)
}


def allowed_clip_kinds(mobject_type: str) -> list[str]:
    """The allow-list (ADR 0007): clip kinds verified for this mobject type."""
    if mobject_type in CODE_TYPES:
        return []  # code layers animate inside their code (ADR 0019)
    kinds = [
        kind
        for kind, info in CLIP_KIND_INFO.items()
        if info.only_types is None or mobject_type in info.only_types  # e.g. letter by letter: Text
    ]
    if mobject_type in RASTER_TYPES:
        return [k for k in kinds if not CLIP_KIND_INFO[k].vector_only]
    return kinds


SHAPES = {"rectangle": m.Rectangle, "circle": m.Circle}  # Circumscribe's shape choice


def clip_kwargs(kind: str, params: dict[str, Any]) -> dict[str, Any]:
    """A clip's params as Manim keyword arguments (ADR 0022).

    Registered params get their defaults and are converted (direction names and
    [x, y] vectors to 3D vectors, hex colours to ManimColor, shape names to
    classes); any other key passes through unchanged.
    """
    kwargs = dict(params)
    for param in clip_params(kind):
        value = params.get(param.name, param.default)
        if value is None:
            kwargs.pop(param.name, None)
            continue
        if param.kind == "direction":
            vector = getattr(m, value) if value in DIRECTIONS else [*value, 0.0][:3]
            value = np.array(vector, dtype=float)
        elif param.kind == "color":
            value = m.ManimColor(value)
        elif param.kind == "choice" and param.name == "shape":
            value = SHAPES[value]
        kwargs[param.name] = value
    return kwargs


def _random_access(anim: m.Succession) -> m.Succession:
    """Let a Succession be interpolated at any alpha, in any order (ADR 0022).

    Manim's Succession needs a scene and only moves forward: it finishes each
    part as time passes it and never goes back. Here every part is begun and
    finished once at begin, with a snapshot of the drawn family before each;
    a frame restores the snapshot of the part holding its time and interpolates
    that part alone.
    """
    anim.scene = None
    parts, timings, snapshots = anim.animations, anim.anims_with_timings, []

    def begin() -> None:
        for part in parts:
            snapshots.append(anim.mobject.copy())
            part.begin()
            part.finish()
        _restore(anim.mobject, snapshots[0])

    def interpolate(alpha: float) -> None:
        t = anim.rate_func(alpha) * anim.max_end_time
        index = next((i for i, w in enumerate(timings) if t < w["end"]), len(parts) - 1)
        _restore(anim.mobject, snapshots[index])
        part, start = parts[index], timings[index]["start"]
        part.interpolate(min(max((t - start) / part.run_time, 0.0), 1.0) if part.run_time else 1.0)

    def finish() -> None:
        interpolate(1.0)

    anim.begin, anim.interpolate, anim.finish = begin, interpolate, finish
    return anim


def _restore(mobject: m.Mobject, snapshot: m.Mobject) -> None:
    """Points and colours of ``snapshot`` written into ``mobject`` (same structure)."""
    for dst, src in zip(mobject.get_family(), snapshot.get_family(), strict=True):
        dst.points = src.points.copy()
        if isinstance(src, m.VMobject):
            for attr in ("fill_rgbas", "stroke_rgbas", "background_stroke_rgbas"):
                setattr(dst, attr, getattr(src, attr).copy())
            dst.stroke_width = src.stroke_width


def make_animation(
    kind: str,
    mobject: m.Mobject,
    ease: Easing | None,
    params: dict[str, Any],
    target: m.Mobject | None = None,
) -> m.Animation:
    info = CLIP_KIND_INFO[kind]
    cls = ANIMATION_CLASSES[kind]
    kwargs = clip_kwargs(kind, params)
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
        anim = cls(mobject, target, **kwargs)
    else:
        anim = cls(mobject, **kwargs)
    if isinstance(anim, m.Succession):
        _random_access(anim)
    if info.clamps_alpha:
        raw = anim.rate_func
        anim.rate_func = lambda x: min(1.0, max(0.0, raw(x)))
    return anim
