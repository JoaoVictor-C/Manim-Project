"""The only module that knows Manim's API.

Maps document specs to Manim mobjects and clip kinds to Manim animations, and
declares which clip kinds each mobject type supports. Everything that depends
on Manim internals is meant to live here so a Manim upgrade touches one file.
"""

from __future__ import annotations

import copy
import json
import math
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

from .. import plugins
from ..logging_config import get_logger
from . import parts, subtitles
from .schema import (
    AXES_OBJECTS,
    CLIP_KIND_INFO,
    CODE_TYPES,
    CONNECTOR_TYPES,
    DIRECTIONS,
    MEDIA_TYPES,
    NUMBER_TYPES,
    RASTER_TYPES,
    TEXT_TYPES,
    TRACE_TYPES,
    Easing,
    Spec,
    SubtitleStyle,
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
    name: getattr(m, name)
    for name in sorted(_SHAPES | TEXT_TYPES | MEDIA_TYPES | NUMBER_TYPES | {"Axes", "TracedPath"})
}
MOBJECT_TYPES["Connector"] = m.Line  # drawn frame by frame by the evaluator (ADR 0036)
MOBJECT_TYPES["RightTriangle"] = m.VGroup
CHILD_ONLY_TYPES = AXES_OBJECTS  # built with their parent (build_child, ADR 0024, 0030)
GRAPH_SAMPLES = 400  # B37: plenty for smooth functions; very high frequencies are undersampled
GRAPH_BISECTIONS = 30  # where a run leaves the y range or the domain, to 1e-9 of the x span

# graph: a sibling's id; layer: another layer's id (a traced path's target, ADR 0033)
ParamKind = Literal["float", "int", "text", "choice", "point", "path", "graph", "layer"]


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
    file_filter: str = ""  # path params: the file dialog's filter (blank = images)

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
# names; "text" and "path" are passed positionally by _build. Anything not
# listed is still accepted from JSON but not shown. Style (fill/stroke) and the
# layer transform are separate.
MOBJECT_PARAMS: dict[str, tuple[Param, ...]] = {
    "Circle": (Param("radius", "float", 1.0, **_SIZE),),
    "Square": (Param("side_length", "float", 2.0, "Side length", **_SIZE),),
    "Rectangle": (Param("width", "float", 4.0, **_SIZE), Param("height", "float", 2.0, **_SIZE)),
    "Triangle": (),
    "RightTriangle": (
        Param("angle", "float", 45.0, "Acute angle (degrees)", minimum=15.0, maximum=75.0, step=1.0),
        Param("side_length", "float", 3.0, "Base length", minimum=0.5, maximum=8.0, step=0.1),
    ),
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
    # A number that clips count (ADR 0036); Manim's own keyword names and defaults.
    "DecimalNumber": (
        Param("number", "float", 0.0, "Value", minimum=-1e12, maximum=1e12, step=0.1),
        Param("num_decimal_places", "int", 2, "Decimal places", minimum=0, maximum=8, step=1),
        Param("unit", "text", "", "Unit (LaTeX, blank = none)"),
        Param("include_sign", "choice", "no", "Show + sign", choices=("no", "yes")),
        _FONT_SIZE,
    ),
    "ImageMobject": (Param("path", "path", "", "Image file"),),
    "SVGMobject": (
        Param("path", "path", "", "SVG file", file_filter="SVG drawings (*.svg)"),
        Param("height", "float", 2.0, minimum=0.05, maximum=50.0, step=0.1),
    ),
    # Axes and their graphs (ADR 0024); a graph's own params, its parent supplies the coordinates.
    "Axes": (
        Param("x_range", "point", (-5.0, 5.0), "x from / to"),
        Param("x_step", "float", 1.0, "x tick step", minimum=0.01, maximum=1000.0),
        Param("y_range", "point", (-3.0, 3.0), "y from / to"),
        Param("y_step", "float", 1.0, "y tick step", minimum=0.01, maximum=1000.0),
        Param("x_length", "float", 10.0, "Width", minimum=0.5, maximum=50.0),
        Param("y_length", "float", 6.0, "Height", minimum=0.5, maximum=50.0),
        Param("numbers", "choice", "no", "Numbers", choices=("no", "yes")),
    ),
    "Graph": (
        Param("expression", "text", "sin(x)", "y ="),
        Param("x_range", "point", (-5.0, 5.0), "x from / to"),
    ),
    # More objects on axes (ADR 0030), in axes units; graph params name a sibling Graph.
    "Point": (
        Param("x", "float", 1.0, minimum=-1000.0, maximum=1000.0, step=0.1),
        Param("y", "float", 1.0, minimum=-1000.0, maximum=1000.0, step=0.1),
        Param("radius", "float", 0.08, minimum=0.01, maximum=5.0, step=0.01),
    ),
    "Area": (
        Param("graph", "graph", "", "Under graph"),
        Param("x_range", "point", (0.0, 2.0), "x from / to"),
        Param("bounded_graph", "graph", "", "Down to graph (none: the x axis)"),
    ),
    "RiemannRectangles": (
        Param("graph", "graph", "", "Under graph"),
        Param("x_range", "point", (0.0, 3.0), "x from / to"),
        Param("dx", "float", 0.25, "Width", minimum=0.01, maximum=10.0, step=0.05),
        Param("sample", "choice", "left", "Height at", choices=("left", "right", "center")),
    ),
    "AxisLabels": (
        Param("x_label", "text", "x", "x label (LaTeX)"),
        Param("y_label", "text", "y", "y label (LaTeX)"),
    ),
    "GraphLabel": (
        Param("graph", "graph", "", "Graph"),
        Param("label", "text", "f(x)", "Label (LaTeX)"),
        Param("x", "float", 2.0, "At x", minimum=-1000.0, maximum=1000.0, step=0.1),
        Param(
            "direction",
            "choice",
            "UR",
            "Side",
            choices=("UR", "UL", "DR", "DL", "UP", "DOWN", "LEFT", "RIGHT"),
        ),
    ),
    # A code layer (ADR 0019): one Scene subclass; `from manim import *` and numpy as np are implied.
    "Code": (Param("code", "text", CODE_STARTER, "Manim code (one Scene)", multiline=True),),
    # Where another layer has been, frame by frame (ADR 0033).
    "TracedPath": (
        Param("target", "layer", "", "Trace"),
        Param("offset", "point", (0.0, 0.0), "Point (from its centre)"),
        Param("dissipate", "float", 0.0, "Fade after (s, 0 = never)", minimum=0.0, maximum=600.0, step=0.1),
    ),
    # A line or arrow between two layers, redrawn every frame (ADR 0036).
    "Connector": (
        Param("source", "layer", "", "From"),
        Param("target", "layer", "", "To"),
        Param("ends", "choice", "edges", "Ends at", choices=("edges", "centres")),
        Param("tips", "choice", "none", "Arrow tips", choices=("none", "end", "both")),
        Param("gap", "float", 0.1, "Gap at ends", minimum=0.0, maximum=5.0, step=0.05),
        Param("source_offset", "point", (0.0, 0.0), "From point (from its centre)"),
        Param("target_offset", "point", (0.0, 0.0), "To point (from its centre)"),
    ),
}

# The object library (S2 plan): menu sections in order.
# Plugins (ADR 0032) append their own sections: a list, changed in place.
LIBRARY: list[tuple[str, tuple[str, ...]]] = [
    (
        "Shapes",
        (
            "Circle",
            "Square",
            "Rectangle",
            "Triangle",
            "RightTriangle",
            "Star",
            "Dot",
            "Line",
            "Arrow",
            "Connector",
        ),
    ),
    ("Text", ("Text", "MathTex", "Tex", "DecimalNumber")),
    ("Media", ("ImageMobject", "SVGMobject")),
    ("Graphing", ("Axes",)),
    ("Simulation", ("TracedPath",)),
    ("Python", ("Code",)),
]

_REQUIRED = {"text", "path", "code", "expression", "graph", "target", "source"}  # always written to the spec
LIBRARY_LABELS = {
    "ImageMobject": "Image",
    "SVGMobject": "SVG",
    "TracedPath": "Traced path",
    "DecimalNumber": "Number",
}
SIMULATION_CHECKPOINT = 30  # a simulation state is kept every this many steps (B46: replays are cheap)


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


def build_mobject(spec: Spec, signature: str | None = None) -> m.Mobject:
    """Build a mobject centred on the origin; the layer transform places it.

    A media object (image, SVG) is built from its file as it is at ``signature``
    (``media_signature`` when not given); a file that cannot be drawn gives a
    dashed placeholder instead of an error (ADR 0027). So does a plugin object
    that cannot be built, or a type no installed plugin provides (ADR 0032).
    """
    if spec.type in CODE_TYPES:
        raise ValueError("code layers are rendered by the code runner, not built (ADR 0019)")
    if spec.type not in MOBJECT_TYPES:
        return _placeholder(2.0).copy()  # build_problem says why
    if spec.type in TRACE_TYPES:
        return trace_mobject([], spec.style)  # drawn frame by frame by the evaluator (ADR 0033)
    if spec.type in CONNECTOR_TYPES:
        return m.VMobject()  # drawn frame by frame by the evaluator (ADR 0036)
    if spec.type in plugins.SIMULATIONS:  # its start state; the evaluator steps it (ADR 0033)
        if simulation_problem(spec) is not None:
            return _placeholder(2.0).copy()
        sim = plugins.SIMULATIONS[spec.type]
        params = plugin_params(spec, sim.params)
        return simulation_drawing(spec, sim.draw(sim.start(dict(params)), dict(params)))
    if spec.type in plugins.TYPES:
        built = _plugin_cached(spec.model_dump_json())
        return (built if isinstance(built, m.Mobject) else _placeholder(2.0)).copy()
    if spec.type in MEDIA_TYPES:
        built = _media_cached(spec.model_dump_json(), signature or media_signature(spec))
        return (built if isinstance(built, m.Mobject) else media_placeholder(spec)).copy()
    return _build_cached(spec.model_dump_json()).copy()


def build_failure(exc: Exception) -> str:
    """Why an object could not be built, in one line: a computer without LaTeX says so (Windows
    reports only "file not found" when the compiler cannot be started)."""
    compiler = m.config["tex_template"].tex_compiler
    if isinstance(exc, FileNotFoundError) and shutil.which(compiler) is None:
        return f"LaTeX is not installed ({compiler} was not found): install MiKTeX or TeX Live"
    lines = [line for line in str(exc).splitlines() if line.strip()]
    return f"{type(exc).__name__}: {lines[0] if lines else ''}"[:200]


MISSING = "missing"  # the signature of a file that cannot be found or read


def media_signature(spec: Spec) -> str | None:
    """What a media object's build depends on besides its spec: its file's modification
    time and size (``MISSING`` when it cannot be stat-ed); ``None`` for other types."""
    if spec.type not in MEDIA_TYPES:
        return None
    path = str(spec.params.get("path") or "")
    try:
        stat = os.stat(path) if path else None
    except OSError:
        stat = None
    return f"{stat.st_mtime_ns}:{stat.st_size}" if stat is not None else MISSING


def build_problem(spec: Spec, signature: str | None = None) -> str | None:
    """Why an object is drawn as a placeholder (a media file, a plugin, a missing plugin), or None."""
    if spec.type in CODE_TYPES:
        return None
    if spec.type not in MOBJECT_TYPES and spec.type not in CHILD_ONLY_TYPES:
        return f"no installed plugin provides {spec.type}"
    if spec.type in plugins.TYPES:
        built = _plugin_cached(spec.model_dump_json())
        return None if isinstance(built, m.Mobject) else built
    if spec.type in plugins.SIMULATIONS:
        return simulation_problem(spec)
    return media_problem(spec, signature)


_CHECKED: set[str] = set()  # plugin types whose determinism was checked in this process


@lru_cache(maxsize=256)
def _plugin_cached(spec_json: str) -> m.Mobject | str:
    """A plugin object built from its spec (ADR 0032), or why it cannot be. The first build
    of each type is done twice: a plugin must be a pure function of its params."""
    spec = Spec.model_validate_json(spec_json)
    object_type = plugins.TYPES[spec.type]
    params = plugin_params(spec, object_type.params)
    try:
        mob = object_type.build(dict(params))
        if not isinstance(mob, m.VMobject):
            return f"the {spec.type} plugin must return a VMobject, not {type(mob).__name__}"
        if spec.type not in _CHECKED:
            again = object_type.build(dict(params))
            _CHECKED.add(spec.type)
            if not _same_drawing(mob, again):
                return (
                    f"the {spec.type} plugin draws differently each time (it must depend only on its params)"
                )
    except Exception as exc:  # a broken plugin must never break a frame (ADR 0032)
        log.warning("plugin object %s failed: %s", spec.type, exc)
        return f"the {spec.type} plugin failed: {type(exc).__name__}: {exc}"
    _apply_style(mob, spec.style)
    mob.move_to(m.ORIGIN)
    return mob


def _same_drawing(a: m.Mobject, b: m.Mobject) -> bool:
    fa, fb = a.family_members_with_points(), b.family_members_with_points()
    if len(fa) != len(fb):
        return False
    for x, y in zip(fa, fb, strict=True):
        if x.points.shape != y.points.shape or not np.allclose(x.points, y.points):
            return False
        colours = isinstance(x, m.VMobject) and isinstance(y, m.VMobject)
        if colours and not (
            np.allclose(x.get_fill_rgbas(), y.get_fill_rgbas())
            and np.allclose(x.get_stroke_rgbas(), y.get_stroke_rgbas())
        ):
            return False
    return True


def plugin_params(spec: Spec, params: tuple[Param, ...]) -> dict[str, Any]:
    """What a plugin is called with: every registered param (defaults filled, points as
    ``[x, y, 0]``) and any other param the spec has."""
    out = {p.name: param_value(spec, p) for p in params}
    out.update({k: v for k, v in spec.params.items() if k not in out})
    for p in params:
        if p.kind == "point":
            x, y = out[p.name][:2]
            out[p.name] = [float(x), float(y), 0.0]
    return out


def forget_plugin_builds() -> None:
    """Drop cached plugin builds (a type was unregistered: tests)."""
    _plugin_cached.cache_clear()
    _CHECKED.clear()
    _simulation_cached_problem.cache_clear()


# --- simulated layers (ADR 0033) ----------------------------------------------


def simulation_problem(spec: Spec) -> str | None:
    """Why a simulation cannot run (a failure, a drawing that is not a VMobject, steps that
    differ when run twice), or None. Its first steps are run twice and compared."""
    return _simulation_cached_problem(spec.model_dump_json())


@lru_cache(maxsize=256)
def _simulation_cached_problem(spec_json: str) -> str | None:
    spec = Spec.model_validate_json(spec_json)
    sim = plugins.SIMULATIONS[spec.type]
    params = plugin_params(spec, sim.params)

    def run() -> list[m.Mobject]:
        state = sim.start(dict(params))
        drawings = [sim.draw(copy.deepcopy(state), dict(params))]
        for _ in range(3):
            state = sim.step(copy.deepcopy(state), 1 / 30, dict(params))
            drawings.append(sim.draw(copy.deepcopy(state), dict(params)))
        return drawings

    try:
        first, second = run(), run()
    except Exception as exc:  # a broken plugin must never break a frame (ADR 0032)
        log.warning("simulation %s failed: %s", spec.type, exc)
        return f"the {spec.type} simulation failed: {type(exc).__name__}: {exc}"
    for drawing in first:
        if not isinstance(drawing, m.VMobject):
            return f"the {spec.type} simulation must draw a VMobject, not {type(drawing).__name__}"
    if not all(_same_drawing(a, b) for a, b in zip(first, second, strict=True)):
        return f"the {spec.type} simulation runs differently each time (it must depend only on its params)"
    return None


def simulation_drawing(spec: Spec, drawing: m.VMobject) -> m.VMobject:
    """A simulation's drawing with the layer's style, in its own units (not re-centred)."""
    _apply_style(drawing, spec.style)
    return drawing


def subtitle_mobject(text: str, style: SubtitleStyle) -> m.VGroup | None:
    """A subtitle as drawn (ADR 0035): its lines centred under each other, shrunk if still wider
    than ``style.max_width``, on a band, centred at ``style.y``; None for empty text. Shared and
    cached: never mutate it."""
    return _subtitle_cached(text, style.model_dump_json())


@lru_cache(maxsize=256)
def _subtitle_cached(text: str, style_json: str) -> m.VGroup | None:
    style = SubtitleStyle.model_validate_json(style_json)
    lines = [build_mobject(spec) for spec in subtitles.line_specs(text, style)]
    if not lines:
        return None
    k = style.font_size / 26
    for line in lines:
        line.set_fill(style.colour, opacity=1.0).set_stroke(width=0)
    block = m.VGroup(*lines).arrange(m.DOWN, buff=0.12 * k)
    if block.width > style.max_width:
        block.scale_to_fit_width(style.max_width)
    parts = [block]
    if style.band:
        band = m.Rectangle(width=block.width + 0.5 * k, height=block.height + 0.3 * k, stroke_width=0)
        band.set_fill(style.band_colour, opacity=style.band_opacity)
        parts.insert(0, band.move_to(block))
    group = m.VGroup(*parts)
    # ``y`` is the centre of a one-line subtitle; more lines grow upwards, as on television.
    bottom = style.y - (lines[0].height + (0.3 * k if style.band else 0.0)) / 2
    group.set_x(0.0).shift(m.UP * (bottom - group.get_bottom()[1]))
    return group


def number_kwargs(spec: Spec) -> dict[str, Any]:
    """A Number's DecimalNumber keyword arguments (ADR 0036): the spec's, with ``include_sign``
    as a bool and a blank unit left out."""
    kwargs = dict(spec.params)
    if "include_sign" in kwargs:
        kwargs["include_sign"] = kwargs["include_sign"] == "yes"
    if not kwargs.get("unit"):
        kwargs.pop("unit", None)
    return kwargs


CONNECTOR_CLASSES = {"none": m.Line, "end": m.Arrow, "both": m.DoubleArrow}


def connector_kwargs(spec: Spec) -> dict[str, Any]:
    """A connector's Line/Arrow keyword arguments besides its ends (ADR 0036): the gap as Manim's
    ``buff``, and the stroke colour (tips too) and width of its style."""
    kwargs: dict[str, Any] = {"buff": float(spec.params.get("gap", 0.1))}
    if spec.style.get("stroke") is not None:
        kwargs["color"] = spec.style["stroke"]
    if spec.style.get("stroke_width") is not None:
        kwargs["stroke_width"] = spec.style["stroke_width"]
    return kwargs


def connector_mobject(start: np.ndarray, end: np.ndarray, spec: Spec) -> m.VMobject:
    """A connector from ``start`` to ``end`` (world units), shortened by its gap at both ends."""
    cls = CONNECTOR_CLASSES[spec.params.get("tips", "none")]
    a, b = (np.array([p[0], p[1], 0.0], dtype=float) for p in (start, end))
    return cls(a, b, **connector_kwargs(spec))


def box_exit(point: np.ndarray, direction: np.ndarray, low: np.ndarray, high: np.ndarray) -> float:
    """How far from ``point`` along the unit ``direction`` the box ``[low, high]`` ends; 0 when the
    point is outside the box."""
    if np.any(point < low - 1e-9) or np.any(point > high + 1e-9):
        return 0.0
    distance = math.inf
    for axis in range(2):
        if direction[axis] > 1e-12:
            distance = min(distance, (high[axis] - point[axis]) / direction[axis])
        elif direction[axis] < -1e-12:
            distance = min(distance, (low[axis] - point[axis]) / direction[axis])
    return distance


def connector_ends(
    source: np.ndarray,
    target: np.ndarray,
    source_box: tuple[np.ndarray, np.ndarray],
    target_box: tuple[np.ndarray, np.ndarray],
    ends: str,
) -> tuple[np.ndarray, np.ndarray] | None:
    """Where a connector between the points ``source`` and ``target`` starts and ends (ADR 0036):
    the points themselves (``centres``), or where the line between them leaves each one's box
    (``edges``); None when nothing is left to draw (the points meet, the boxes overlap)."""
    source, target = np.asarray(source, dtype=float)[:2], np.asarray(target, dtype=float)[:2]
    delta = target - source
    length = float(np.linalg.norm(delta))
    if length < 1e-9:
        return None
    if ends != "edges":
        return source, target
    unit = delta / length
    a = box_exit(source, unit, *source_box)
    b = box_exit(target, -unit, *target_box)
    if a + b >= length - 1e-9:
        return None
    return source + unit * a, target - unit * b


def trace_mobject(runs: list[np.ndarray], style: dict[str, Any]) -> m.VMobject:
    """A traced path through runs of points (a new sub-path per run; one point is a zero-length
    line, as in Manim's TracedPath), white and 2 wide unless styled."""
    mob = m.VMobject(stroke_color=m.WHITE, stroke_width=2, fill_opacity=0.0)
    for run in runs:
        points = np.asarray(run, dtype=float)
        if len(points) == 1:
            points = np.vstack([points, points])
        mob.start_new_path(points[0])
        mob.add_points_as_corners(points[1:])
    _apply_style(mob, style)
    return mob


def media_problem(spec: Spec, signature: str | None = None) -> str | None:
    """Why a media object cannot be drawn (it shows a placeholder), or None."""
    if spec.type not in MEDIA_TYPES:
        return None
    built = _media_cached(spec.model_dump_json(), signature or media_signature(spec))
    return None if isinstance(built, m.Mobject) else built


@lru_cache(maxsize=256)
def _media_cached(spec_json: str, signature: str) -> m.Mobject | str:
    """The built media object, or the reason it cannot be built (both cached per signature)."""
    spec = Spec.model_validate_json(spec_json)
    if not spec.params.get("path"):
        return "no file chosen"
    if signature == MISSING:
        return "file not found"
    try:
        mob = _build(spec)
    except Exception as exc:  # a broken file must never break a frame or an export (ADR 0027)
        log.warning("cannot draw %s: %s", spec.params.get("path"), exc)
        return f"cannot read the file ({type(exc).__name__})"
    if spec.type == "SVGMobject" and not mob.family_members_with_points():
        return "the drawing is empty"
    return mob


@lru_cache(maxsize=32)
def _placeholder(height: float) -> m.Mobject:
    box = m.DashedVMobject(m.Rectangle(width=height * 16 / 9, height=height), num_dashes=48)
    box.set_stroke(m.ManimColor("#94a3b8"), width=3, opacity=0.9)
    return box


def media_placeholder(spec: Spec) -> m.Mobject:
    """A dashed 16:9 box the object's height, standing in for a file that cannot be drawn."""
    height = float(spec.params.get("height", 2.0)) if spec.type == "SVGMobject" else 2.0
    return _placeholder(height)


def longest_path(mob: m.Mobject) -> m.Mobject:
    """What a MoveAlongPath follows on ``mob`` (ADR 0025, 0027): the object itself when it
    has points of its own, else its longest drawn member (an SVG's or a text's)."""
    if mob.has_points() or not mob.family_members_with_points():
        return mob
    return max(mob.family_members_with_points(), key=_polygon_length)


def _polygon_length(mob: m.Mobject) -> float:
    return float(np.linalg.norm(np.diff(mob.points, axis=0), axis=1).sum())


@lru_cache(maxsize=256)
def _build_cached(spec_json: str) -> m.Mobject:
    return _build(Spec.model_validate_json(spec_json))


def _build(spec: Spec) -> m.Mobject:
    cls = MOBJECT_TYPES[spec.type]
    params = dict(spec.params)
    for param in MOBJECT_PARAMS.get(spec.type, ()):
        if param.kind == "point" and param.name in params:
            x, y = params[param.name][:2]
            params[param.name] = (x, y, 0.0)  # documents are 2D
    spans = params.pop(parts.SPANS_PARAM, None)
    if spec.type == "RightTriangle":
        angle = math.radians(float(params.get("angle", 45.0)))
        base = float(params.get("side_length", 3.0))
        height = base * math.tan(angle)
        left, bottom = -base / 2, -height / 2
        corner = np.array([left, bottom, 0.0])
        base_end = np.array([left + base, bottom, 0.0])
        top = np.array([left, bottom + height, 0.0])
        marker = min(base, height) * 0.12
        mob = m.VGroup(
            m.Line(corner, base_end),
            m.Line(corner, top),
            m.Line(top, base_end),
            m.Line(corner + np.array([marker, 0, 0]), corner + np.array([marker, marker, 0])),
            m.Line(corner + np.array([marker, marker, 0]), corner + np.array([0, marker, 0])),
        )
    elif spec.type == "Axes":
        mob = _build_axes(spec)
    elif spec.type in TEXT_TYPES:
        text = params.pop("text", "")
        mob = cls(parts.mark(text, spans) if spans else text, **params)
    elif spec.type == "SVGMobject":
        # Manim's own SVG cache is keyed by the file's name, not its contents: an edited
        # file would come back as it was. Builds are cached here per signature instead.
        mob = cls(params.pop("path"), use_svg_cache=False, **params)
    elif spec.type in MEDIA_TYPES:
        mob = cls(params.pop("path"), **params)
    elif spec.type in NUMBER_TYPES:
        mob = cls(**number_kwargs(spec))
    else:
        mob = cls(**params)
    _apply_style(mob, spec.style)
    mob.move_to(m.ORIGIN)
    return mob


def _axes_param(spec: Spec, name: str):
    param = next(p for p in MOBJECT_PARAMS["Axes"] if p.name == name)
    return spec.params.get(name, param.default)


def _whole(value: float) -> float | int:
    """Whole numbers as ints, so the axes label 1, 2, 3 rather than 1.0, 2.0, 3.0."""
    return int(value) if float(value).is_integer() else float(value)


def _build_axes(spec: Spec) -> m.Axes:
    """Axes from the editor's params (ranges as [from, to] plus a step; numbers yes/no)."""
    x0, x1 = (_whole(v) for v in _axes_param(spec, "x_range")[:2])
    y0, y1 = (_whole(v) for v in _axes_param(spec, "y_range")[:2])
    return m.Axes(
        x_range=[x0, x1, _whole(_axes_param(spec, "x_step"))],
        y_range=[y0, y1, _whole(_axes_param(spec, "y_step"))],
        x_length=_axes_param(spec, "x_length"),
        y_length=_axes_param(spec, "y_length"),
        axis_config={"include_numbers": _axes_param(spec, "numbers") == "yes"},
    )


def build_child(parent: Spec, spec: Spec, graphs: dict[str, Spec] | None = None) -> m.Mobject:
    """A child object built against its parent (ADR 0024): a graph on its axes, or an object
    built from one of its graphs (``graphs``: the referenced graphs' specs by id, ADR 0030)."""
    refs = json.dumps({k: v.model_dump(mode="json") for k, v in sorted((graphs or {}).items())})
    return _child_cached(parent.model_dump_json(), spec.model_dump_json(), refs).copy()


@lru_cache(maxsize=256)
def _child_cached(parent_json: str, spec_json: str, refs_json: str = "{}") -> m.Mobject:
    parent, spec = Spec.model_validate_json(parent_json), Spec.model_validate_json(spec_json)
    if spec.type not in AXES_OBJECTS or parent.type != "Axes":
        raise ValueError(f"no child object {spec.type!r} on {parent.type!r}")
    axes = _build_cached(parent_json)  # the same axes, centred the same way, the root draws
    refs = {k: Spec.model_validate(v) for k, v in json.loads(refs_json).items()}

    def graph_of(name: str) -> m.VMobject | None:
        target = spec.params.get(name)
        if not target:
            return None
        if target not in refs:
            raise ValueError(f"{spec.type}: graph {target!r} was not given")
        return _child_cached(parent_json, refs[target].model_dump_json())

    p = spec.params
    if spec.type == "Graph":
        x_range = p.get("x_range") or _axes_param(parent, "x_range")
        mob = plot_runs(axes, p["expression"], float(x_range[0]), float(x_range[1]))
        mob.set_stroke(m.YELLOW, width=4)  # Manim's plot default
        _give_function(mob, axes, p["expression"], float(x_range[0]), float(x_range[1]))
    elif spec.type == "Point":
        mob = m.Dot(
            axes.c2p(float(p.get("x", 1.0)), float(p.get("y", 1.0))), radius=float(p.get("radius", 0.08))
        )
    elif spec.type == "Area":
        x0, x1 = (float(v) for v in p.get("x_range", (0.0, 2.0))[:2])
        mob = axes.get_area(graph_of("graph"), x_range=(x0, x1), bounded_graph=graph_of("bounded_graph"))
    elif spec.type == "RiemannRectangles":
        x0, x1 = (float(v) for v in p.get("x_range", (0.0, 3.0))[:2])
        mob = axes.get_riemann_rectangles(
            graph_of("graph"),
            x_range=(x0, x1),
            dx=float(p.get("dx", 0.25)),
            input_sample_type=p.get("sample", "left"),
        )
    elif spec.type == "AxisLabels":
        mob = axes.get_axis_labels(m.MathTex(p.get("x_label", "x")), m.MathTex(p.get("y_label", "y")))
    else:  # GraphLabel: next to the graph's point, not moved onto Manim's screen (ADR 0030)
        graph = graph_of("graph")
        mob = m.MathTex(p.get("label", "f(x)"))
        point = axes.input_to_graph_point(float(p.get("x", 2.0)), graph)
        mob.next_to(point, getattr(m, p.get("direction", "UR")), buff=m.MED_SMALL_BUFF)
        mob.set_color(graph.get_color())  # as get_graph_label
    _apply_style(mob, spec.style)
    return mob


def _give_function(graph: m.VMobject, axes: m.Axes, expression: str, x0: float, x1: float) -> None:
    """What Manim's Axes helpers read from a graph (ADR 0030): its function, clamped into the
    axes' y range (0 where undefined) so areas and rectangles never get a NaN point."""
    from .expressions import compile_expression

    f = compile_expression(expression)
    y0, y1 = float(axes.y_range[0]), float(axes.y_range[1])

    def underlying(x: float) -> float:
        with np.errstate(all="ignore"):
            y = float(f(np.array([x], dtype=float))[0])
        return min(max(y, y0), y1) if math.isfinite(y) else 0.0

    graph.underlying_function = underlying
    graph.function = lambda x: axes.c2p(x, underlying(x))
    graph.t_min, graph.t_max = min(x0, x1), max(x0, x1)


def plot_runs(axes: m.Axes, expression: str, x0: float, x1: float) -> m.VMobject:
    """The graph of ``expression`` on ``axes`` over [x0, x1], one subpath per drawable run.

    A sample is drawable when it is finite and within the axes' y range. Runs end
    exactly where the curve leaves the range or its domain (found by bisection
    between the last drawable sample and the next), so ``tan`` stops at the edge
    of the axes instead of spiking and ``sqrt`` starts at 0 (B37).
    """
    from .expressions import compile_expression

    f = compile_expression(expression)
    y0, y1 = axes.y_range[0], axes.y_range[1]

    def value(x: float) -> float:
        with np.errstate(all="ignore"):
            return float(f(np.array([x], dtype=float))[0])

    def drawable(y) -> np.ndarray:
        with np.errstate(invalid="ignore"):
            return np.isfinite(y) & (y >= y0) & (y <= y1)

    def edge(inside: float, outside: float) -> float:
        """The last drawable x between a drawable and an undrawable sample."""
        for _ in range(GRAPH_BISECTIONS):
            middle = (inside + outside) / 2
            if drawable(np.array([value(middle)]))[0]:
                inside = middle
            else:
                outside = middle
        return inside

    lo, hi = min(x0, x1), max(x0, x1)
    xs = np.linspace(lo, hi, GRAPH_SAMPLES)
    with np.errstate(all="ignore"):
        good = drawable(f(xs))
    graph = m.VMobject()
    start = None
    for i, ok in enumerate([*good, False]):  # a sentinel closes the last run
        if ok and start is None:
            start = i
        elif not ok and start is not None:
            left = edge(xs[start], xs[start - 1]) if start > 0 else xs[start]
            right = edge(xs[i - 1], xs[i]) if i < len(xs) else xs[i - 1]
            if right - left > 1e-9:
                samples = max(i - start, 2)
                piece = axes.plot(
                    value, x_range=[left, right, (right - left) / (samples - 1)], use_smoothing=False
                )
                if graph.has_points():
                    graph.append_vectorized_mobject(piece)
                else:
                    graph.set_points(piece.points)
            start = None
    return graph


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


class TabledMoveAlongPath(m.MoveAlongPath):
    """MoveAlongPath that measures its path once (ADR 0025).

    Manim's ``point_from_proportion`` measures every curve of the path on every
    frame (23.6 ms on a 399-curve graph, B38); the same points come from an
    arc-length table built here (0.005 ms).
    """

    TURN_STEP = 1e-6  # of a curve's parameter: the tiny chord whose direction is the tangent

    def __init__(self, mobject: m.Mobject, path: m.VMobject, rotate: str = "no", **kwargs: Any) -> None:
        super().__init__(mobject, path, **kwargs)
        count = path.get_num_curves()
        self._curves = [path.get_nth_curve_function(i) for i in range(count)]
        self._lengths = np.array([path.get_nth_curve_length(i) for i in range(count)])
        self._cumulative = np.concatenate([[0.0], np.cumsum(self._lengths)])
        self._turns = rotate == "along"  # ADR 0029

    def _point(self, alpha: float) -> np.ndarray:
        if not self._curves:
            return self.path.get_center()
        target = min(max(alpha, 0.0), 1.0) * self._cumulative[-1]
        i = min(int(np.searchsorted(self._cumulative, target, side="right")) - 1, len(self._curves) - 1)
        length = self._lengths[i]
        return self._curves[i]((target - self._cumulative[i]) / length if length > 0 else 0.0)

    def _direction(self, alpha: float) -> float:
        """The path's direction (an angle) at ``alpha`` of its length: the derivative of the
        curve under that point (a chord of 2e-6 of its parameter, one-sided at its ends)."""
        target = min(max(alpha, 0.0), 1.0) * self._cumulative[-1]
        i = min(int(np.searchsorted(self._cumulative, target, side="right")) - 1, len(self._curves) - 1)
        length = self._lengths[i]
        s = (target - self._cumulative[i]) / length if length > 0 else 0.0
        curve, step = self._curves[i], self.TURN_STEP
        delta = curve(min(s + step, 1.0)) - curve(max(s - step, 0.0))
        return math.atan2(delta[1], delta[0])

    def interpolate_mobject(self, alpha: float) -> None:
        eased = self.rate_func(alpha)
        if self._turns and self._curves:
            # From the object as it began, so a frame depends on alpha alone (random access).
            for dst, src in zip(
                self.mobject.family_members_with_points(),
                self.starting_mobject.family_members_with_points(),
                strict=True,
            ):
                dst.points = src.points.copy()
            turn = self._direction(eased) - self._direction(0.0)
            self.mobject.rotate(turn, about_point=self.mobject.get_center())
        self.mobject.move_to(self._point(eased))


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
    "ChangeDecimalToValue": m.ChangeDecimalToValue,  # a Number counts (ADR 0036)
    "MoveAlongPath": TabledMoveAlongPath,  # the evaluator passes the path in local units (ADR 0025)
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
    if mobject_type in TRACE_TYPES | CONNECTOR_TYPES or mobject_type in plugins.SIMULATIONS:
        return []  # simulated layers and connectors are drawn frame by frame (ADR 0033, 0036)
    kinds = [
        kind
        for kind, info in CLIP_KIND_INFO.items()
        if info.only_types is None or mobject_type in info.only_types  # e.g. letter by letter: Text
    ]
    if mobject_type in CHILD_ONLY_TYPES:  # a graph is locked to its axes: it cannot travel (ADR 0025)
        kinds = [k for k in kinds if CLIP_KIND_INFO[k].category != "motion"]
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
        elif param.kind == "layer":
            kwargs.pop(param.name, None)  # resolved by the evaluator into the target mobject
            continue
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
    # What a scene would show: the parts' mobjects (Succession's own group stays empty).
    drawn = {id(part.mobject): part.mobject for part in parts if part.mobject is not None}
    anim.mobject = m.Group(*drawn.values())

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
    if info.category in ("morph", "motion"):
        if target is None:
            raise ValueError(f"{kind} needs a target (the morph's end or the path)")
        anim = cls(mobject, target, **kwargs)
    else:
        anim = cls(mobject, **kwargs)
    if isinstance(anim, m.Succession):
        _random_access(anim)
    if info.clamps_alpha:
        raw = anim.rate_func
        anim.rate_func = lambda x: min(1.0, max(0.0, raw(x)))
    return anim


# Plugins load last: they register into the tables above (ADR 0032).
plugins.load_plugins()
