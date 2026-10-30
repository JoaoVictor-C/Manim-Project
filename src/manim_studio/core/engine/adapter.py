"""The only module that knows Manim's API.

Maps document specs to Manim mobjects and clip kinds to Manim animations, and
declares which clip kinds each mobject type supports. Everything that depends
on Manim internals is meant to live here so a Manim upgrade touches one file.
"""

from __future__ import annotations

import builtins
import copy
import hashlib
import json
import math
import os
import shutil
import sys
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import manim as m
import numpy as np
from manim.animation.transform_matching_parts import TransformMatchingAbstractBase
from manim.utils import rate_functions

from ... import plugins
from ...logging_config import get_logger
from ..assist.diagnostics import user_traceback
from ..code import helpers, python_object
from ..code.code_cache import code_hash
from ..code.python_object import CodeProblem
from ..model import parts, shape
from ..model.schema import (
    AXES_OBJECTS,
    CLIP_KIND_INFO,
    CODE_TYPES,
    CONNECTOR_TYPES,
    DIRECTIONS,
    GLYPH_COLOURS,
    GROUP_TYPES,
    MEDIA_TYPES,
    NUMBER_TYPES,
    PYTHON_TYPES,
    RASTER_TYPES,
    SHAPE_TYPES,
    SMART_MORPHS,
    TEXT_TYPES,
    TRACE_TYPES,
    Easing,
    Spec,
    SubtitleStyle,
    clip_params,
)
from ..sound import subtitles
from . import morph

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


# --- patch: one process at a time writes Manim's text and LaTeX cache -------------------------
#
# The editor, its build worker and the render-ahead process share the cache. Manim writes a file
# when it does not exist yet, so two of them building the same text at once could read it while
# the other was writing it (seen: FileNotFoundError on a texts/*.svg in the render-ahead process).
# Writing and checking take a lock file in the cache folder; a process that cannot get it within
# LOCK_TIMEOUT (a first MiKTeX run installing packages) goes on unlocked rather than hang.

LOCK_TIMEOUT = 120.0
_held = threading.local()


@contextmanager
def cache_lock(timeout: float = LOCK_TIMEOUT):
    """Hold the cache's lock file (re-entrant within a thread)."""
    if getattr(_held, "depth", 0):
        _held.depth += 1
        try:
            yield
        finally:
            _held.depth -= 1
        return
    folder = cache_dir()
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / ".build.lock", "a+b") as file:
        locked = _lock(file, timeout)
        if not locked:
            log.warning("cache lock busy for %.0f s: building without it", timeout)
        _held.depth = 1
        try:
            yield
        finally:
            _held.depth = 0
            if locked:
                _unlock(file)


def _lock(file, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while True:
        try:
            if sys.platform == "win32":
                import msvcrt

                file.seek(0)
                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.02)


def _unlock(file) -> None:
    if sys.platform == "win32":
        import msvcrt

        file.seek(0)
        msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(file.fileno(), fcntl.LOCK_UN)


def _locked(function):
    def wrapper(*args, **kwargs):
        with cache_lock():
            return function(*args, **kwargs)

    wrapper.__wrapped__ = function
    return wrapper


_tex_files.tex_to_svg_file = _tex_mobject.tex_to_svg_file = _locked(_tex_to_svg_file)
m.Text._text2svg = _locked(m.Text._text2svg)
m.MarkupText._text2svg = _locked(m.MarkupText._text2svg)


# --- mobjects ---------------------------------------------------------------

_SHAPES = {
    "Circle",
    "Ellipse",
    "Square",
    "Rectangle",
    "RoundedRectangle",
    "Triangle",
    "RightTriangle",
    "RegularPolygon",
    "RegularPolygram",
    "Pentagon",
    "Hexagon",
    "Octagon",
    "Nonagon",
    "Decagon",
    "Rhombus",
    "Parallelogram",
    "Trapezoid",
    "Polygon",
    "Star",
    "Cross",
    "Dot",
    "Line",
    "DashedLine",
    "Arrow",
    "DoubleArrow",
    "Vector",
    "CurvedArrow",
    "CurvedDoubleArrow",
    "Arc",
    "ArcBetweenPoints",
    "CubicBezier",
    "Sector",
    "Annulus",
    "AnnularSector",
    "Polyline",
    "Angle",
    "RightAngle",
    "BraceBetweenPoints",
    "Cube",
    "Sphere",
    "Cylinder",
    "Cone",
    "Torus",
    "Prism",
    "Tetrahedron",
    "Octahedron",
    "Dodecahedron",
    "Icosahedron",
}
_COORDINATE_SYSTEMS = {"NumberLine", "NumberPlane", "ComplexPlane", "PolarPlane", "ThreeDAxes"}
_MOBJECT_ALIASES = {
    "Pentagon": m.RegularPolygon,
    "Hexagon": m.RegularPolygon,
    "Octagon": m.RegularPolygon,
    "Nonagon": m.RegularPolygon,
    "Decagon": m.RegularPolygon,
    "Rhombus": m.Polygon,
    "Parallelogram": m.Polygon,
    "Trapezoid": m.Polygon,
    "Polyline": m.VMobject,
}

MOBJECT_TYPES: dict[str, type] = {
    name: _MOBJECT_ALIASES.get(name, getattr(m, name, None))
    for name in sorted(
        _SHAPES | _COORDINATE_SYSTEMS | TEXT_TYPES | MEDIA_TYPES | NUMBER_TYPES | {"Axes", "TracedPath"}
    )
}
MOBJECT_TYPES["Connector"] = m.Line  # drawn frame by frame by the evaluator (ADR 0036)
MOBJECT_TYPES["RightTriangle"] = (
    m.VGroup
)  # an outline and the mark of its right angle (_build_right_triangle)
CHILD_ONLY_TYPES = AXES_OBJECTS  # built with their parent (build_child, ADR 0024, 0030)
GRAPH_SAMPLES = 400  # B37: plenty for smooth functions; very high frequencies are undersampled
GRAPH_BISECTIONS = 30  # where a run leaves the y range or the domain, to 1e-9 of the x span

# graph: a sibling's id; layer: another layer's id (a traced path's target, ADR 0033)
# bool and colour: a Python object's parameters (ADR 0051)
ParamKind = Literal["float", "int", "text", "choice", "point", "path", "graph", "layer", "bool", "colour"]


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
    point_handle: bool = False  # this point-valued parameter is a draggable geometry point

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
    "Pentagon": (),
    "Hexagon": (),
    "Octagon": (),
    "Nonagon": (),
    "Decagon": (),
    "Rhombus": (),
    "Parallelogram": (),
    "Trapezoid": (),
    "Cross": (),
    "Ellipse": (
        Param("width", "float", 2.0, minimum=0.05, maximum=50.0, step=0.1),
        Param("height", "float", 1.0, minimum=0.05, maximum=50.0, step=0.1),
    ),
    "Square": (Param("side_length", "float", 2.0, "Side length", **_SIZE),),
    "Rectangle": (Param("width", "float", 4.0, **_SIZE), Param("height", "float", 2.0, **_SIZE)),
    "RoundedRectangle": (
        Param("width", "float", 4.0, **_SIZE),
        Param("height", "float", 2.0, **_SIZE),
        Param("corner_radius", "float", 0.35, "Corner radius", minimum=0.0, maximum=10.0),
    ),
    "Triangle": (),
    "RightTriangle": (
        Param("angle", "float", 45.0, "Acute angle (degrees)", minimum=15.0, maximum=75.0, step=1.0),
        Param("side_length", "float", 3.0, "Base length", minimum=0.5, maximum=8.0, step=0.1),
    ),
    "Star": (
        Param("n", "int", 5, "Points", minimum=3, maximum=24, step=1),
        Param("outer_radius", "float", 1.0, "Radius", **_SIZE),
    ),
    "RegularPolygon": (Param("n", "int", 6, "Sides", minimum=3, maximum=24, step=1),),
    "RegularPolygram": (
        Param("num_vertices", "int", 5, "Points", minimum=3, maximum=24, step=1),
        Param("density", "int", 2, "Star density", minimum=1, maximum=12, step=1),
        Param("radius", "float", 1.0, **_SIZE),
    ),
    "Polygon": (
        Param("point_1", "point", (-1.0, -1.0), "Vertex 1", point_handle=True),
        Param("point_2", "point", (1.0, -1.0), "Vertex 2", point_handle=True),
        Param("point_3", "point", (0.0, 1.0), "Vertex 3", point_handle=True),
    ),
    "Polyline": (
        Param("point_1", "point", (-1.0, 0.0), "Point 1", point_handle=True),
        Param("point_2", "point", (0.0, 1.0), "Point 2", point_handle=True),
        Param("point_3", "point", (1.0, 0.0), "Point 3", point_handle=True),
    ),
    "Dot": (Param("radius", "float", 0.08, minimum=0.01, maximum=5.0, step=0.01),),
    "Line": (
        Param("start", "point", (-1.0, 0.0), point_handle=True),
        Param("end", "point", (1.0, 0.0), point_handle=True),
    ),
    "Arrow": (
        Param("start", "point", (-1.0, 0.0), point_handle=True),
        Param("end", "point", (1.0, 0.0), point_handle=True),
        Param("buff", "float", 0.25, "Gap at ends", minimum=0.0, maximum=5.0, step=0.05),
    ),
    "DashedLine": (
        Param("start", "point", (-1.0, 0.0), point_handle=True),
        Param("end", "point", (1.0, 0.0), point_handle=True),
        Param("dash_length", "float", 0.05, minimum=0.01, maximum=2.0, step=0.01),
    ),
    "DoubleArrow": (
        Param("start", "point", (-1.0, 0.0), point_handle=True),
        Param("end", "point", (1.0, 0.0), point_handle=True),
        Param("buff", "float", 0.0, "Gap at ends", minimum=0.0, maximum=5.0, step=0.05),
    ),
    "Vector": (
        Param("direction", "point", (1.5, 0.0), "Direction", point_handle=True),
        Param("buff", "float", 0.0, "Gap at origin", minimum=0.0, maximum=5.0, step=0.05),
    ),
    "CurvedArrow": (
        Param("start_point", "point", (-1.0, -0.5), "Start", point_handle=True),
        Param("end_point", "point", (1.0, 0.5), "End", point_handle=True),
    ),
    "CurvedDoubleArrow": (
        Param("start_point", "point", (-1.0, -0.5), "Start", point_handle=True),
        Param("end_point", "point", (1.0, 0.5), "End", point_handle=True),
    ),
    "CubicBezier": (
        Param("point_1", "point", (-2.0, -1.0), "Start", point_handle=True),
        Param("point_2", "point", (-1.0, 1.0), "Control 1", point_handle=True),
        Param("point_3", "point", (1.0, 1.0), "Control 2", point_handle=True),
        Param("point_4", "point", (2.0, -1.0), "End", point_handle=True),
    ),
    "Arc": (
        Param("radius", "float", 1.0, **_SIZE),
        Param("start_angle", "float", 0.0, "Start angle (radians)", minimum=-6.283, maximum=6.283),
        Param("angle", "float", math.pi / 2, "Sweep (radians)", minimum=-6.283, maximum=6.283),
    ),
    "ArcBetweenPoints": (
        Param("start", "point", (-1.0, 0.0), "Start", point_handle=True),
        Param("end", "point", (1.0, 0.0), "End", point_handle=True),
        Param("angle", "float", math.pi / 2, "Bend (radians)", minimum=-6.283, maximum=6.283),
    ),
    "Sector": (
        Param("radius", "float", 1.0, **_SIZE),
        Param("start_angle", "float", 0.0, "Start angle (radians)", minimum=-6.283, maximum=6.283),
        Param("angle", "float", math.pi / 2, "Sweep (radians)", minimum=0.01, maximum=6.283),
    ),
    "Annulus": (
        Param("inner_radius", "float", 0.6, minimum=0.01, maximum=25.0),
        Param("outer_radius", "float", 1.0, minimum=0.02, maximum=50.0),
    ),
    "AnnularSector": (
        Param("inner_radius", "float", 0.5, minimum=0.0, maximum=25.0),
        Param("outer_radius", "float", 1.0, minimum=0.02, maximum=50.0),
        Param("start_angle", "float", 0.0, "Start angle (radians)", minimum=-6.283, maximum=6.283),
        Param("angle", "float", math.pi / 2, "Sweep (radians)", minimum=0.01, maximum=6.283),
    ),
    "Angle": (
        Param("point_a", "point", (1.0, 0.0), "First ray", point_handle=True),
        Param("vertex", "point", (0.0, 0.0), "Vertex", point_handle=True),
        Param("point_b", "point", (0.0, 1.0), "Second ray", point_handle=True),
        Param("radius", "float", 0.5, minimum=0.05, maximum=10.0),
    ),
    "RightAngle": (
        Param("point_a", "point", (1.0, 0.0), "First ray", point_handle=True),
        Param("vertex", "point", (0.0, 0.0), "Vertex", point_handle=True),
        Param("point_b", "point", (0.0, 1.0), "Second ray", point_handle=True),
        Param("length", "float", 0.3, minimum=0.05, maximum=5.0),
    ),
    "BraceBetweenPoints": (
        Param("point_1", "point", (-1.0, 0.0), "Start", point_handle=True),
        Param("point_2", "point", (1.0, 0.0), "End", point_handle=True),
        Param("direction", "point", (0.0, -1.0), "Direction"),
    ),
    "Cube": (Param("side_length", "float", 2.0, "Side length", minimum=0.1, maximum=20.0),),
    "Sphere": (Param("radius", "float", 1.0, **_SIZE),),
    "Cylinder": (
        Param("radius", "float", 1.0, **_SIZE),
        Param("height", "float", 2.0, minimum=0.1, maximum=50.0),
    ),
    "Cone": (
        Param("base_radius", "float", 1.0, "Base radius", **_SIZE),
        Param("height", "float", 1.0, minimum=0.1, maximum=50.0),
    ),
    "Torus": (
        Param("major_radius", "float", 1.5, "Major radius", minimum=0.1, maximum=25.0),
        Param("minor_radius", "float", 0.5, "Tube radius", minimum=0.05, maximum=10.0),
    ),
    "Prism": (
        Param("width", "float", 3.0, minimum=0.1, maximum=50.0),
        Param("depth", "float", 2.0, minimum=0.1, maximum=50.0),
        Param("height", "float", 1.0, minimum=0.1, maximum=50.0),
    ),
    "Tetrahedron": (Param("edge_length", "float", 1.5, "Edge length", minimum=0.1, maximum=20.0),),
    "Octahedron": (Param("edge_length", "float", 1.5, "Edge length", minimum=0.1, maximum=20.0),),
    "Dodecahedron": (Param("edge_length", "float", 1.5, "Edge length", minimum=0.1, maximum=20.0),),
    "Icosahedron": (Param("edge_length", "float", 1.5, "Edge length", minimum=0.1, maximum=20.0),),
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
        Param("grid_x", "choice", "yes", "Vertical grid", choices=("no", "yes")),
        Param("grid_x_step", "float", 1.0, "Vertical spacing", minimum=0.01, maximum=1000.0),
        Param("grid_y", "choice", "yes", "Horizontal grid", choices=("no", "yes")),
        Param("grid_y_step", "float", 1.0, "Horizontal spacing", minimum=0.01, maximum=1000.0),
        Param("grid_colour", "colour", "#64748B", "Grid colour"),
        Param("grid_opacity", "float", 0.35, "Grid opacity", minimum=0.0, maximum=1.0, step=0.05),
        Param("grid_width", "float", 1.0, "Grid line width", minimum=0.1, maximum=5.0, step=0.1),
    ),
    "NumberLine": (
        Param("x_min", "float", -5.0, "From", minimum=-1000.0, maximum=1000.0),
        Param("x_max", "float", 5.0, "To", minimum=-1000.0, maximum=1000.0),
        Param("x_step", "float", 1.0, "Tick step", minimum=0.01, maximum=1000.0),
        Param("length", "float", 10.0, minimum=0.5, maximum=50.0),
    ),
    "NumberPlane": (
        Param("x_min", "float", -7.0, "x from", minimum=-1000.0, maximum=1000.0),
        Param("x_max", "float", 7.0, "x to", minimum=-1000.0, maximum=1000.0),
        Param("x_step", "float", 1.0, "x step", minimum=0.01, maximum=1000.0),
        Param("y_min", "float", -4.0, "y from", minimum=-1000.0, maximum=1000.0),
        Param("y_max", "float", 4.0, "y to", minimum=-1000.0, maximum=1000.0),
        Param("y_step", "float", 1.0, "y step", minimum=0.01, maximum=1000.0),
        Param("x_length", "float", 14.0, "Width", minimum=0.5, maximum=50.0),
        Param("y_length", "float", 8.0, "Height", minimum=0.5, maximum=50.0),
    ),
    "ComplexPlane": (),
    "PolarPlane": (),
    "ThreeDAxes": (),
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
            "Ellipse",
            "Square",
            "Rectangle",
            "RoundedRectangle",
            "Triangle",
            "RightTriangle",
            "RegularPolygon",
            "RegularPolygram",
            "Pentagon",
            "Hexagon",
            "Octagon",
            "Nonagon",
            "Decagon",
            "Rhombus",
            "Parallelogram",
            "Trapezoid",
            "Polygon",
            "Star",
            "Cross",
            "Dot",
            "Sector",
            "Annulus",
            "AnnularSector",
            "Connector",
        ),
    ),
    (
        "Lines & Arrows",
        ("Line", "DashedLine", "Arrow", "DoubleArrow", "Vector", "CurvedArrow", "CurvedDoubleArrow"),
    ),
    (
        "Curves & Annotations",
        ("Arc", "ArcBetweenPoints", "CubicBezier", "Angle", "RightAngle", "BraceBetweenPoints", "Polyline"),
    ),
    (
        "3D Solids",
        (
            "Cube",
            "Sphere",
            "Cylinder",
            "Cone",
            "Torus",
            "Prism",
            "Tetrahedron",
            "Octahedron",
            "Dodecahedron",
            "Icosahedron",
        ),
    ),
    ("Text", ("Text", "MathTex", "Tex", "DecimalNumber")),
    ("Media", ("ImageMobject", "SVGMobject")),
    ("Graphing", ("Axes",)),
    ("Coordinates", ("NumberLine", "NumberPlane", "ComplexPlane", "PolarPlane", "ThreeDAxes")),
    ("Simulation", ("TracedPath",)),
    ("Python", ("Code",)),
]

_REQUIRED = {
    "text",
    "path",
    "code",
    "expression",
    "graph",
    "target",
    "source",
    "direction",
}  # always written to the spec
_REQUIRED |= {
    "num_vertices",
    "start_point",
    "end_point",
    "point_1",
    "point_2",
    "point_3",
    "point_4",
    "inner_radius",
    "outer_radius",
    "corner_radius",
    "buff",
}
_REQUIRED_BY_TYPE = {
    "Arrow": {"start", "end"},
    "DoubleArrow": {"start", "end"},
    "ArcBetweenPoints": {"start", "end"},
    "Torus": {"major_radius", "minor_radius"},
}
LIBRARY_LABELS = {
    "ImageMobject": "Image",
    "SVGMobject": "SVG",
    "TracedPath": "Traced path",
    "DecimalNumber": "Number",
    "RightTriangle": "Right triangle",
    "Pentagon": "Pentagon",
    "Hexagon": "Hexagon",
    "Octagon": "Octagon",
    "Nonagon": "Nonagon",
    "Decagon": "Decagon",
    "Rhombus": "Rhombus",
    "Parallelogram": "Parallelogram",
    "Trapezoid": "Trapezoid",
    "RoundedRectangle": "Rounded rectangle",
    "RegularPolygon": "Regular polygon",
    "RegularPolygram": "Star polygon",
    "Polygon": "Custom polygon",
    "Polyline": "Custom line path",
    "DoubleArrow": "Double arrow",
    "CurvedArrow": "Curved arrow",
    "CurvedDoubleArrow": "Curved double arrow",
    "ArcBetweenPoints": "Arc between points",
    "CubicBezier": "Cubic Bézier curve",
    "RightAngle": "Right-angle marker",
    "BraceBetweenPoints": "Brace",
    "AnnularSector": "Ring sector",
    "Cube": "Cube",
    "Sphere": "Sphere",
    "Cylinder": "Cylinder",
    "Cone": "Cone",
    "Torus": "Torus",
    "Prism": "Prism",
    "Tetrahedron": "Tetrahedron",
    "Octahedron": "Octahedron",
    "Dodecahedron": "Dodecahedron",
    "Icosahedron": "Icosahedron",
    "NumberLine": "Number line",
    "NumberPlane": "Number plane",
    "ComplexPlane": "Complex plane",
    "PolarPlane": "Polar plane",
    "ThreeDAxes": "3D axes",
}
SIMULATION_CHECKPOINT = 30  # a simulation state is kept every this many steps (B46: replays are cheap)


def default_spec(type_name: str, **params: Any) -> Spec:
    """A new object of ``type_name`` as the library creates it."""
    if type_name not in MOBJECT_PARAMS:
        raise ValueError(f"unsupported mobject type {type_name!r}")
    required_names = _REQUIRED | _REQUIRED_BY_TYPE.get(type_name, set())
    required = {p.name: p.default for p in MOBJECT_PARAMS[type_name] if p.name in required_names}
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
    if spec.type in GROUP_TYPES:
        return m.VGroup()  # draws nothing: its children are drawn through it (ADR 0050)
    if spec.type in PYTHON_TYPES:  # the user's own code, once trusted (ADR 0051)
        built = _python_built(spec, signature)
        return (built if isinstance(built, m.Mobject) else _placeholder(2.0)).copy()
    if spec.type in SHAPE_TYPES:  # frozen vector data (ADR 0052)
        return _shape_cached(spec.model_dump_json()).copy()
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
    if isinstance(exc, FileNotFoundError) and (missing := latex_problem()) is not None:
        return missing
    lines = [line for line in str(exc).splitlines() if line.strip()]
    return f"{type(exc).__name__}: {lines[0] if lines else ''}"[:200]


def latex_problem() -> str | None:
    """Why this computer cannot build MathTex or Tex (no LaTeX compiler on PATH), or None."""
    compiler = m.config["tex_template"].tex_compiler
    if shutil.which(compiler) is None:
        return f"LaTeX is not installed ({compiler} was not found): install MiKTeX or TeX Live"
    return None


MISSING = "missing"  # the signature of a file that cannot be found or read


TRUSTED, UNTRUSTED = "trusted", "untrusted"  # the signature of a Python object (ADR 0051)
# What a trusted Python object's signature names besides its own code (ADR 0058): signature ->
# (the project's helper sources, the names of those that may run). A build looks its helpers up here.
_HELPER_SETS: dict[str, tuple[dict[str, str], frozenset[str]]] = {}
_HELPER_SETS_KEPT = 512  # more than the builds kept (``_python_cached``), so a kept build finds its set


def media_signature(
    spec: Spec,
    helper_sources: helpers.Sources | None = None,
    trusted_helpers: frozenset[str] | set[str] | list[str] | None = None,
) -> str | None:
    """What a media object's build depends on besides its spec: its file's modification
    time and size (``MISSING`` when it cannot be stat-ed); for a Python object, whether its
    code may run here (``TRUSTED`` / ``UNTRUSTED``, ADR 0051) and, with the project's helpers
    (``helper_sources``, ADR 0058), their code and which of them may run - ``TRUSTED:<key>``; those
    are the trust store's unless ``trusted_helpers`` names them. ``None`` for other types."""
    if spec.type in PYTHON_TYPES:
        if not python_object.is_trusted(str(spec.params.get("code", ""))):
            return UNTRUSTED
        return _with_helpers(TRUSTED, helper_sources, trusted_helpers)
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
    if spec.type in CODE_TYPES | GROUP_TYPES | SHAPE_TYPES:
        return None
    if spec.type in PYTHON_TYPES:
        problem = python_problem(spec, signature)
        return None if problem is None else str(problem)
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
    mob._studio_origin = np.asarray(mob.get_center()[:2], dtype=float).copy()
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


# --- Python objects (ADR 0051) -------------------------------------------------

_PY_CHECKED: set[str] = set()  # code (hashes) whose determinism was checked in this process
_PY_GLOBALS: dict[str, Any] = {}  # what the code can name: `from manim import *`, m, np, math


def python_params(spec: Spec) -> tuple[Param, ...]:
    """A Python object's parameters as Properties fields (ADR 0051), read from its ``PARAMS``
    without running the code; none while ``PARAMS`` cannot be read."""
    code = str(spec.params.get("code", ""))
    if python_object.params_problem(code) is not None:
        return ()
    out = []
    for p in python_object.read_params(code):
        if p.kind in ("float", "int"):
            low = p.minimum if p.minimum is not None else -1e6
            high = p.maximum if p.maximum is not None else 1e6
            span = high - low if p.minimum is not None and p.maximum is not None else 10.0
            step = 1.0 if p.kind == "int" else 10 ** math.floor(math.log10(span / 100)) if span > 0 else 0.1
            out.append(Param(p.name, p.kind, p.default, minimum=low, maximum=high, step=max(step, 0.001)))
        else:
            out.append(Param(p.name, p.kind, p.default))
    return tuple(out)


def python_problem(spec: Spec, signature: str | None = None) -> CodeProblem | None:
    """Why a Python object is drawn as the placeholder (its code is not trusted, cannot be read,
    raises, runs too long, returns no VMobject or draws differently each time), or None."""
    built = _python_built(spec, signature)
    return built if isinstance(built, CodeProblem) else None


def _python_built(spec: Spec, signature: str | None = None) -> m.Mobject | CodeProblem:
    signature = signature or media_signature(spec)
    if signature != TRUSTED and not str(signature).startswith(f"{TRUSTED}:"):
        return CodeProblem(python_object.NOT_TRUSTED)  # opening a file never runs its code (ADR 0019)
    return _python_cached(spec.model_dump_json(), signature)


def _with_helpers(
    signature: str,
    helper_sources: helpers.Sources | None,
    trusted_helpers: frozenset[str] | set[str] | list[str] | None = None,
) -> str:
    """``signature`` naming the project's helpers too (ADR 0058): unchanged without any, so a project
    without helpers builds exactly as before; else ``<signature>:<key>`` over their code and which
    of them may run, the set kept in ``_HELPER_SETS`` for the build."""
    if not helper_sources:
        return signature
    known = dict(helper_sources)
    if trusted_helpers is None:
        trusted = frozenset(name for name, code in known.items() if python_object.is_trusted(code))
    else:
        trusted = frozenset(trusted_helpers) & known.keys()
    material = json.dumps([helpers.digest(known), sorted(trusted)])
    key = f"{signature}:{hashlib.sha256(material.encode('utf-8')).hexdigest()[:16]}"
    _HELPER_SETS.pop(key, None)  # most recent last
    _HELPER_SETS[key] = (known, trusted)
    while len(_HELPER_SETS) > _HELPER_SETS_KEPT:
        del _HELPER_SETS[next(iter(_HELPER_SETS))]
    return key


def python_helpers(signature: str | None) -> tuple[dict[str, str], frozenset[str]]:
    """The helper sources a Python object's ``signature`` names, and those that may run (ADR 0058)."""
    return _HELPER_SETS.get(signature or "", ({}, frozenset()))


@lru_cache(maxsize=256)
def _python_cached(spec_json: str, signature: str = TRUSTED) -> m.Mobject | CodeProblem:
    """A Python object built by its code, or why it cannot be. The first build of each code is
    done twice: like a plugin, it must be a pure function of its parameters (ADR 0032). The
    project's helpers named by ``signature`` are importable meanwhile, those trusted only (ADR 0058)."""
    spec = Spec.model_validate_json(spec_json)
    code = str(spec.params.get("code", ""))
    problem = python_object.params_problem(code)
    if problem is not None:
        return problem
    values = python_object.call_values(code, dict(spec.params.get("values") or {}))
    sources, trusted = python_helpers(signature)
    try:
        with (
            python_object.time_limit(python_object.TIME_LIMIT),
            helpers.install(sources, trusted=trusted.__contains__),
        ):
            build = _python_function(code)
            mob = build(dict(values))
            if not isinstance(mob, m.VMobject):
                return CodeProblem(
                    f"build(p) must return a Manim VMobject (a shape, a text, a VGroup), "
                    f"not {type(mob).__name__}"
                )
            key = code_hash(code) + signature
            if key not in _PY_CHECKED:
                if not _same_drawing(mob, build(dict(values))):
                    return CodeProblem(
                        "build(p) draws differently each time: it must depend only on p "
                        "(no random numbers without a seed, no clock)"
                    )
                _PY_CHECKED.add(key)
    except python_object.TimeLimit as exc:
        return _problem_at(str(exc), exc, code, sources, "TimeoutError")
    except (Exception, SystemExit) as exc:  # the user's code must never break a frame or the editor
        log.info("Python object failed: %s", exc)
        lines = [line for line in str(exc).splitlines() if line.strip()]
        message = f"{type(exc).__name__}: {lines[0] if lines else ''}".rstrip(": ")[:300]
        return _problem_at(message, exc, code, sources)
    _apply_style(mob, spec.style)  # only what the user set (ADR 0051)
    mob._studio_origin = np.asarray(mob.get_center()[:2], dtype=float).copy()
    mob.move_to(m.ORIGIN)
    return mob


def _problem_at(
    message: str,
    exc: BaseException,
    code: str,
    helper_sources: dict[str, str] | None = None,
    error_type: str = "",
) -> CodeProblem:
    """``message`` at the place ``exc`` was raised - the code's line, or a helper's (ADR 0058) - with
    the exception's type and the traceback of the user's own frames (P13.1)."""
    place = helpers.locate(exc, python_object.FILENAME)
    sources = {python_object.FILENAME: code}
    sources |= {helpers.filename(name): source for name, source in (helper_sources or {}).items()}
    return CodeProblem(
        message,
        place.line,
        error_type or type(exc).__name__,
        place.where,
        user_traceback(exc, sources),
        place.helper_line,
    )


def _python_function(code: str) -> Callable[[dict[str, Any]], Any]:
    """Run the code's top level in a fresh namespace and return its ``build``."""
    if not _PY_GLOBALS:
        exec("from manim import *", _PY_GLOBALS)  # the names the code may use
        _PY_GLOBALS.update({"m": m, "np": np, "math": math, "__builtins__": builtins})
    namespace = {**_PY_GLOBALS, "__name__": "studio_python_object"}
    exec(compile(code, python_object.FILENAME, "exec"), namespace)  # trusted by the user (ADR 0019)
    build = namespace.get("build")
    if not callable(build):
        raise NameError("the code must define build(p), returning the object")
    return build


def python_timed_out(spec: Spec, signature: str | None = None) -> str | None:
    """The message when building ``spec`` (a Python object) was stopped by the time limit."""
    problem = python_problem(spec, signature) if spec.type in PYTHON_TYPES else None
    return str(problem) if problem is not None and python_object.TIMED_OUT in problem.message else None


def forget_python_builds() -> None:
    """Drop cached Python object builds and determinism checks (tests)."""
    _python_cached.cache_clear()
    _PY_CHECKED.clear()


# --- shapes: objects frozen into vector data (ADR 0052) -------------------------

_UL = (-1.0, 1.0, 0.0)  # Manim's default sheen direction
_NO_BACKGROUND = [0.0, 0.0, 0.0, 1.0]  # Manim's default background stroke: black, unseen at width 0


def shape_data(mob: m.Mobject) -> dict[str, Any]:
    """What ``mob`` draws as a shape's params (ADR 0052): every leaf with points, in
    ``family_members_with_points()`` order, with its points and what the Cairo renderer reads to
    draw it (colours, widths, background stroke, sheen, joints, caps). Floats are kept exactly.

    Raises ``ValueError`` (the reason, for the user) when it is not plain vector paths or is too big.
    """
    leaves = mob.family_members_with_points()
    if not leaves:
        raise ValueError("it draws nothing")
    total = 0
    pieces = []
    for leaf in leaves:
        total += len(leaf.points)
        if total > shape.MAX_POINTS:
            raise ValueError(shape.size_problem(total, 0))
        pieces.append(piece_data(leaf))
    data = {"version": shape.VERSION, "shapes": pieces}
    problem = shape.size_problem(total, len(json.dumps(data)))
    if problem is not None:
        raise ValueError(problem)
    return data


def piece_data(leaf: m.Mobject) -> dict[str, Any]:
    """One drawn piece of a shape (ADR 0052): ``leaf``'s own points (not its children's) and what
    the Cairo renderer reads to draw it. The scene importer (ADR 0053) records leaves this way.

    Raises ``ValueError`` (the reason, for the user) when it is not a plain vector path."""
    if not isinstance(leaf, m.VMobject):
        raise ValueError(f"it is not all vector paths (a {type(leaf).__name__})")
    if leaf.get_background_image():
        raise ValueError("it is painted with a background image")
    points = np.asarray(leaf.points, dtype=float)
    if not np.isfinite(points).all():
        raise ValueError("it has points that are not finite numbers")
    piece: dict[str, Any] = {
        "points": (points if points[:, 2].any() else points[:, :2]).tolist(),
        "fill": _rgbas_data(leaf.get_fill_rgbas()),
        "stroke": _rgbas_data(leaf.get_stroke_rgbas()),
        "stroke_width": float(leaf.get_stroke_width()),
    }
    background = _rgbas_data(leaf.get_stroke_rgbas(background=True))
    if background != _NO_BACKGROUND:
        piece["background"] = background
    if leaf.get_stroke_width(background=True):
        piece["background_width"] = float(leaf.get_stroke_width(background=True))
    direction = [float(v) for v in np.asarray(leaf.get_sheen_direction(), dtype=float)]
    if tuple(direction) != _UL:
        piece["sheen_direction"] = direction
    if leaf.get_sheen_factor():
        piece["sheen_factor"] = float(leaf.get_sheen_factor())
    if leaf.joint_type is not m.LineJointType.AUTO:
        piece["joint"] = leaf.joint_type.name
    if leaf.cap_style is not m.CapStyleType.AUTO:
        piece["cap"] = leaf.cap_style.name
    if leaf.z_index:
        piece["z_index"] = float(leaf.z_index)
    if leaf.shade_in_3d:
        piece["shade_in_3d"] = True
    return piece


def _rgbas_data(rgbas: np.ndarray) -> list:
    """One colour as ``[r, g, b, a]``; a gradient as the list of its stops."""
    rows = np.asarray(rgbas, dtype=float).tolist()
    return rows[0] if len(rows) == 1 else rows


def shape_from_data(shapes):
    """A frozen shape from Manim Studio (ADR 0052): one VMobject per piece, from its bezier points
    and the colours and widths it was drawn with, in a VGroup."""
    group = m.VGroup()
    for data in shapes:
        piece = m.VMobject()
        points = np.array(data["points"], dtype=float)
        if points.shape[1] == 2:  # stored flat: z is 0
            points = np.hstack([points, np.zeros((len(points), 1))])
        piece.set_points(points)
        piece.fill_rgbas = np.array(data["fill"], dtype=float).reshape(-1, 4)
        piece.stroke_rgbas = np.array(data["stroke"], dtype=float).reshape(-1, 4)
        background = data.get("background", [0.0, 0.0, 0.0, 1.0])
        piece.background_stroke_rgbas = np.array(background, dtype=float).reshape(-1, 4)
        piece.stroke_width = data["stroke_width"]
        piece.background_stroke_width = data.get("background_width", 0.0)
        piece.sheen_direction = np.array(data.get("sheen_direction", [-1.0, 1.0, 0.0]), dtype=float)
        piece.sheen_factor = data.get("sheen_factor", 0.0)
        piece.joint_type = m.LineJointType[data.get("joint", "AUTO")]
        piece.cap_style = m.CapStyleType[data.get("cap", "AUTO")]
        piece.z_index = data.get("z_index", 0)
        piece.shade_in_3d = data.get("shade_in_3d", False)
        group.add(piece)
    return group


@lru_cache(maxsize=256)
def _shape_cached(spec_json: str) -> m.Mobject:
    spec = Spec.model_validate_json(spec_json)
    mob = shape_from_data(spec.params["shapes"])
    _apply_style(mob, spec.style)  # only what the user set: the frozen colours are the baseline
    mob.move_to(m.ORIGIN)
    return mob


def freeze_data(spec: Spec, signature: str | None = None) -> dict[str, Any]:
    """A shape's params for what ``spec`` draws now (ADR 0052): the built object with its style.

    Raises ``ValueError`` with the reason when what is drawn is not the object - a placeholder
    (a missing file, code not trusted, a failing build, no LaTeX) - or cannot be a shape."""
    if spec.type in plugins.SIMULATIONS:
        raise ValueError("a simulation is drawn step by step, not one object")
    problem = build_problem(spec, signature)
    if problem is not None:
        raise ValueError(f"it is drawn as a placeholder ({problem}): only what is drawn can be frozen")
    try:
        mob = build_mobject(spec, signature)
    except Exception as exc:  # e.g. no LaTeX on this computer
        raise ValueError(
            f"it cannot be built here ({build_failure(exc)}): only what is drawn can be frozen"
        ) from exc
    return shape_data(mob)


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
    spec = Spec.model_validate_json(spec_json)
    if GLYPH_COLOURS in spec.params:  # a coloured copy of the plain build (ADR 0055)
        return colour_glyphs(
            _build_cached(plain_spec(spec).model_dump_json()).copy(), spec.params[GLYPH_COLOURS]
        )
    return _build(spec)


def plain_spec(spec: Spec) -> Spec:
    """``spec`` without its glyph colours (ADR 0055): what Manim builds, before they are applied."""
    if GLYPH_COLOURS not in spec.params:
        return spec
    return spec.model_copy(update={"params": {k: v for k, v in spec.params.items() if k != GLYPH_COLOURS}})


def colour_glyphs(mobject, colours):
    """Glyph colours from Manim Studio (ADR 0055): one entry per drawn glyph, in the order of
    family_members_with_points(); None keeps the glyph's colour, extra entries are ignored."""
    for glyph, colour in zip(mobject.family_members_with_points(), colours, strict=False):
        if colour:
            glyph.set_color(colour)
    return mobject


_build_guard: tuple[Callable[[Spec], bool], Any] | None = None  # (which specs, the lock to hold) - ADR 0065


def guard_builds(slow: Callable[[Spec], bool], lock: Any) -> None:
    """Hold ``lock`` (a context manager shared between processes) while building a spec ``slow`` picks out:
    the processes of one export draw frames side by side and must not compile the same LaTeX at once."""
    global _build_guard
    _build_guard = (slow, lock)


def _param_default(type_name: str, name: str) -> Any:
    return next(param.default for param in MOBJECT_PARAMS[type_name] if param.name == name)


def _params_with_defaults(type_name: str, params: dict[str, Any]) -> dict[str, Any]:
    values = {param.name: params.get(param.name, param.default) for param in MOBJECT_PARAMS[type_name]}
    for param in MOBJECT_PARAMS[type_name]:
        value = values[param.name]
        if param.kind == "point" and len(value) == 2:
            values[param.name] = (*value, 0.0)
    return values


def _build(spec: Spec) -> m.Mobject:
    guard = _build_guard
    if guard is not None and guard[0](spec):
        with guard[1]:
            return _make(spec)
    return _make(spec)


def _make(spec: Spec) -> m.Mobject:
    cls = MOBJECT_TYPES[spec.type]
    params = dict(spec.params)
    for param in MOBJECT_PARAMS.get(spec.type, ()):
        if param.kind == "point" and param.name in params:
            x, y = params[param.name][:2]
            params[param.name] = (x, y, 0.0)  # documents are 2D
    spans = params.pop(parts.SPANS_PARAM, None)
    extra, style = text_style(spec)
    params.update(extra)
    if spec.type in {"Pentagon", "Hexagon", "Octagon", "Nonagon", "Decagon"}:
        sides = {"Pentagon": 5, "Hexagon": 6, "Octagon": 8, "Nonagon": 9, "Decagon": 10}[spec.type]
        mob = m.RegularPolygon(n=sides)
    elif spec.type == "RegularPolygram":
        p = _params_with_defaults(spec.type, params)
        mob = m.RegularPolygram(p["num_vertices"], density=p["density"], radius=p["radius"])
    elif spec.type in {"Rhombus", "Parallelogram", "Trapezoid"}:
        vertices = {
            "Rhombus": ((0.0, 1.0), (1.0, 0.0), (0.0, -1.0), (-1.0, 0.0)),
            "Parallelogram": ((-1.0, -1.0), (0.0, -1.0), (1.0, 1.0), (0.0, 1.0)),
            "Trapezoid": ((-1.0, -1.0), (1.0, -1.0), (0.65, 1.0), (-0.65, 1.0)),
        }[spec.type]
        mob = m.Polygon(*(np.array([x, y, 0.0]) for x, y in vertices))
    elif spec.type in {"Polygon", "Polyline"}:
        p = _params_with_defaults(spec.type, params)
        points = np.array([p[f"point_{i}"] for i in range(1, 4)], dtype=float)
        mob = m.Polygon(*points) if spec.type == "Polygon" else m.VMobject().set_points_as_corners(points)
    elif spec.type == "CubicBezier":
        p = _params_with_defaults(spec.type, params)
        mob = m.CubicBezier(*(np.array(p[f"point_{i}"]) for i in range(1, 5)))
    elif spec.type == "ArcBetweenPoints":
        p = _params_with_defaults(spec.type, params)
        mob = m.ArcBetweenPoints(p["start"], p["end"], angle=p["angle"])
    elif spec.type in {"CurvedArrow", "CurvedDoubleArrow"}:
        p = _params_with_defaults(spec.type, params)
        mob = cls(p["start_point"], p["end_point"])
    elif spec.type == "BraceBetweenPoints":
        p = _params_with_defaults(spec.type, params)
        mob = m.BraceBetweenPoints(p["point_1"], p["point_2"], direction=p["direction"])
    elif spec.type == "Angle":
        p = _params_with_defaults(spec.type, params)
        a, vertex, b = (np.array(p[name], dtype=float) for name in ("point_a", "vertex", "point_b"))
        mob = m.Angle(m.Line(vertex, a), m.Line(vertex, b), radius=p["radius"])
    elif spec.type == "RightAngle":
        p = _params_with_defaults(spec.type, params)
        a, vertex, b = (np.array(p[name], dtype=float) for name in ("point_a", "vertex", "point_b"))
        mob = m.RightAngle(m.Line(vertex, a), m.Line(vertex, b), length=p["length"])
    elif spec.type == "NumberLine":
        p = _params_with_defaults(spec.type, params)
        mob = m.NumberLine(
            x_range=[p["x_min"], p["x_max"], p["x_step"]],
            length=p["length"],
            include_numbers=False,
        )
    elif spec.type == "NumberPlane":
        p = _params_with_defaults(spec.type, params)
        mob = m.NumberPlane(
            x_range=[p["x_min"], p["x_max"], p["x_step"]],
            y_range=[p["y_min"], p["y_max"], p["y_step"]],
            x_length=p["x_length"],
            y_length=p["y_length"],
        )
    elif spec.type == "Prism":
        mob = m.Prism(
            dimensions=[
                params.get("width", 3.0),
                params.get("depth", 2.0),
                params.get("height", 1.0),
            ]
        )
    elif spec.type == "RightTriangle":
        mob = _build_right_triangle(params)
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
    _apply_style(mob, style)
    if spec.type == "Axes":
        _style_axes_grid(mob, spec)
    mob._studio_origin = np.asarray(mob.get_center()[:2], dtype=float).copy()
    mob.move_to(m.ORIGIN)
    return mob


def right_triangle_points(angle: float, side_length: float) -> list[tuple[float, float]]:
    """The corner of the right angle, the end of the base, the top; the base runs along x and the
    acute ``angle`` (degrees) is at the base's end. ``python_export`` writes the same points."""
    height = side_length * math.tan(math.radians(angle))
    return [(0.0, 0.0), (side_length, 0.0), (0.0, height)]


def right_triangle_mark(angle: float, side_length: float) -> list[tuple[float, float]]:
    """The little square in the right angle: the three points of its two inner sides."""
    size = min(side_length, side_length * math.tan(math.radians(angle))) * 0.12
    return [(size, 0.0), (size, size), (0.0, size)]


def _build_right_triangle(params: dict) -> m.Mobject:
    """A right triangle (filled outline) with its right angle marked, centred by the caller."""
    angle = float(params.get("angle", 45.0))
    side = float(params.get("side_length", 3.0))
    corner, end, top = (np.array([x, y, 0.0]) for x, y in right_triangle_points(angle, side))
    a, b, c = (np.array([x, y, 0.0]) for x, y in right_triangle_mark(angle, side))
    return m.VGroup(m.Polygon(corner, end, top), m.Line(a, b), m.Line(b, c))


def _axes_param(spec: Spec, name: str):
    param = next(p for p in MOBJECT_PARAMS["Axes"] if p.name == name)
    return spec.params.get(name, param.default)


def _whole(value: float) -> float | int:
    """Whole numbers as ints, so the axes label 1, 2, 3 rather than 1.0, 2.0, 3.0."""
    return int(value) if float(value).is_integer() else float(value)


def _build_axes(spec: Spec) -> m.Axes:
    """Axes from the editor's ranges, tick steps and independently spaced grid lines."""
    x0, x1 = (_whole(v) for v in _axes_param(spec, "x_range")[:2])
    y0, y1 = (_whole(v) for v in _axes_param(spec, "y_range")[:2])
    axes = m.Axes(
        x_range=[x0, x1, _whole(_axes_param(spec, "x_step"))],
        y_range=[y0, y1, _whole(_axes_param(spec, "y_step"))],
        x_length=_axes_param(spec, "x_length"),
        y_length=_axes_param(spec, "y_length"),
        axis_config={"include_numbers": _axes_param(spec, "numbers") == "yes"},
    )
    grid = m.VGroup()
    if _axes_param(spec, "grid_x") == "yes" and x1 > x0:
        for value in _grid_values(x0, x1, float(_axes_param(spec, "grid_x_step"))):
            if abs(value) > 1e-9:
                grid.add(m.Line(axes.c2p(value, y0), axes.c2p(value, y1)))
    if _axes_param(spec, "grid_y") == "yes" and y1 > y0:
        for value in _grid_values(y0, y1, float(_axes_param(spec, "grid_y_step"))):
            if abs(value) > 1e-9:
                grid.add(m.Line(axes.c2p(x0, value), axes.c2p(x1, value)))
    axes.add_to_back(grid)
    axes._studio_grid_group = grid
    return axes


_MAX_GRID_LINES_PER_AXIS = 1200


def _grid_values(low: float, high: float, step: float) -> list[float]:
    """Grid coordinates at multiples of ``step``; thin extreme densities to keep canvases responsive."""
    if step <= 0 or not math.isfinite(step):
        return []
    first = math.ceil(low / step - 1e-9)
    last = math.floor(high / step + 1e-9)
    count = last - first + 1
    if count <= 0:
        return []
    stride = max(1, math.ceil(count / _MAX_GRID_LINES_PER_AXIS))
    return [index * step for index in range(first, last + 1) if (index - first) % stride == 0 or index == 0]


def _style_axes_grid(axes: m.Axes, spec: Spec) -> None:
    """Keep the user-selected grid appearance separate from the Axes object's general style."""
    grid = getattr(axes, "_studio_grid_group", None)
    if grid is not None:
        grid.set_stroke(
            color=_axes_param(spec, "grid_colour"),
            width=float(_axes_param(spec, "grid_width")),
            opacity=float(_axes_param(spec, "grid_opacity")),
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
    from ..model.expressions import compile_expression

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
    from ..model.expressions import compile_expression

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
    return list(_regions_cached(plain_spec(spec).model_dump_json()))


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


def style_glyphs(glyphs: list[m.Mobject], style: dict[str, Any]) -> None:
    """A part's colours (ADR 0049) on its glyphs, in place: as ``Spec.style`` colours an object."""
    for glyph in glyphs:
        _apply_style(glyph, style)


def glyph_count(spec: Spec) -> int:
    """How many glyphs a Text, MathTex or Tex draws (ADR 0055): the entries ``glyph_colours`` can
    have. Raises like ``build_mobject`` when it cannot be built (no LaTeX for a new formula)."""
    return len(build_mobject(plain_spec(spec)).family_members_with_points())


@dataclass(frozen=True)
class GlyphOutline:
    """One drawn glyph as plain data for a preview (ADR 0055): its closed subpaths, each an
    ``(4k, 2)`` array of cubic bezier points (anchor, handle, handle, anchor, ...) in Manim units
    (y up), and the colour it has without glyph colours."""

    subpaths: tuple[np.ndarray, ...]
    fill: str  # "#rrggbb"
    opacity: float


def glyph_outlines(spec: Spec) -> list[GlyphOutline]:
    """Every drawn glyph of a Text, MathTex or Tex, in ``glyph_colours`` order, as built without
    its glyph colours. Raises like ``build_mobject`` when it cannot be built."""
    out = []
    for leaf in build_mobject(plain_spec(spec)).family_members_with_points():
        subpaths = tuple(np.asarray(path)[:, :2].copy() for path in leaf.get_subpaths() if len(path) >= 4)
        fill = leaf.get_fill_color().to_hex().lower()
        out.append(GlyphOutline(subpaths, fill, float(leaf.get_fill_opacity())))
    return out


_LIGATURES = ("ffi", "ffl", "ff", "fi", "fl")  # Pango draws these letters as one glyph
_TEX_SYMBOLS = {0: "−"}  # the minus sign (first glyph of TeX's symbol font)
_MATH_GREEK = dict(zip(range(11, 32), "αβγδϵζηθικλμνξπρστυϕχ", strict=True))
_TEXT_LIGATURES = dict(zip(range(11, 16), ("ff", "fi", "fl", "ffi", "ffl"), strict=True))
_SVG_SHAPES = ("Path", "SimpleLine", "Rect", "Circle", "Ellipse", "Polygon", "Polyline", "Text")


def glyph_labels(spec: Spec) -> list[str]:
    """What each drawn glyph of a Text, MathTex or Tex shows, in ``glyph_colours`` order (ADR 0055):
    a Text's characters (spaces draw nothing; a ligature is one glyph of several letters); a TeX
    glyph's character as read from its font's character code (letters, digits and signs exactly,
    Greek and a few symbols by the usual Computer Modern positions, "?" otherwise; a rule such
    as a fraction bar is "—"). The numbers 1, 2, ... when the glyphs cannot be matched."""
    mob = build_mobject(plain_spec(spec))
    count = len(mob.family_members_with_points())
    labels = _text_labels(spec, count) if spec.type == "Text" else _tex_labels(mob, spec.type == "Tex")
    return labels if labels is not None and len(labels) == count else [str(i + 1) for i in range(count)]


def _text_labels(spec: Spec, count: int) -> list[str] | None:
    chars = [c for c in str(spec.params.get("text", "")) if not c.isspace()]
    excess, labels, i = len(chars) - count, [], 0
    while i < len(chars):
        rest = "".join(chars[i : i + 3])
        ligature = next((x for x in _LIGATURES if 0 < len(x) - 1 <= excess and rest.startswith(x)), None)
        size = len(ligature) if ligature else 1
        labels.append("".join(chars[i : i + size]))
        excess -= size - 1
        i += size
    return labels if excess == 0 else None


def _tex_labels(mob: m.Mobject, text_mode: bool) -> list[str] | None:
    """Labels from the SVG LaTeX made, walked in the order Manim reads it (``SVGMobject``)."""
    import svgelements as se  # Manim's own SVG reader

    file_name = getattr(mob, "file_name", None)
    if not file_name:
        return None
    try:
        svg = se.SVG.parse(str(file_name))
    except Exception:  # an unreadable file: plain numbers
        return None
    shapes = tuple(getattr(se, name) for name in _SVG_SHAPES)
    labels, stack = [], [svg]
    while stack:
        element = stack.pop()
        if isinstance(element, (se.Group, se.Use)):
            stack.extend(element[::-1])
        if isinstance(element, shapes):
            labels.append(_tex_label(str(element.values.get("id") or ""), element, text_mode))
    return labels


def _tex_label(glyph_id: str, element, text_mode: bool) -> str:
    _, _, code = glyph_id.rpartition("-")  # dvisvgm names a glyph g<font>-<character code>
    if not code.isdigit():
        return "—" if type(element).__name__ in ("Rect", "SimpleLine") else "?"
    number = int(code)
    if 33 <= number <= 126:
        return chr(number)
    table = _TEXT_LIGATURES if text_mode else _MATH_GREEK
    return table.get(number) or _TEX_SYMBOLS.get(number, "?")


def text_style(spec: Spec) -> tuple[dict[str, Any], dict[str, Any]]:
    """``(constructor keywords, style left to apply)``. A Text with coloured pieces (``t2c``) takes
    its fill as ``color=``: a ``set_fill`` afterwards would paint over its pieces (ADR 0049)."""
    style = dict(spec.style)
    if spec.type == "Text" and spec.params.get("t2c") and style.get("fill") is not None:
        return {"color": style.pop("fill")}, style
    return {}, style


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


# --- smart morphs (ADR 0056) ---------------------------------------------------------------------

_RGBAS = ("fill_rgbas", "stroke_rgbas", "background_stroke_rgbas")
_LINEAR = ("stroke_width", "background_stroke_width", "sheen_factor", "sheen_direction")
Exact = list[tuple[np.ndarray | None, np.ndarray | None]]


def smart_pair(source: m.Mobject, target: m.Mobject) -> tuple[m.VGroup, m.VGroup, Exact] | None:
    """Both ends of a morph as groups of pieces aligned by ``core/engine/morph.py``, one drawn piece
    per entry of its plan (same structure, same point counts: Manim's own alignment then
    changes nothing), and each piece's original points at either end (None: it grows or
    shrinks there). None when an end has no outline or something that is not one (an image)."""
    a, b = source.family_members_with_points(), target.family_members_with_points()
    if not a or not b or not all(isinstance(leaf, m.VMobject) for leaf in (*a, *b)):
        return None
    pieces = morph.plan(
        [leaf.points for leaf in a],
        [leaf.points for leaf in b],
        [shape_key(leaf) for leaf in a],
        [shape_key(leaf) for leaf in b],
    )
    if not pieces:
        return None
    starts, ends, exact = m.VGroup(), m.VGroup(), []
    for piece in pieces:
        if piece.source is not None and piece.target is not None:
            start, end = _bare(a[piece.source]), _bare(b[piece.target])
        elif piece.source is None:  # grows and fades in
            end = _bare(b[piece.target])
            start = _faded(end)
        else:  # shrinks and fades out
            start = _bare(a[piece.source])
            end = _faded(start)
        start.points, end.points = piece.start, piece.end
        exact.append(
            (
                a[piece.source].points.copy() if piece.source is not None else None,
                b[piece.target].points.copy() if piece.target is not None else None,
            )
        )
        starts.add(start)
        ends.add(end)
    return starts, ends, exact


def _bare(leaf: m.VMobject) -> m.VMobject:
    """A copy of one drawn piece without its children (they are pieces of their own)."""
    copy = leaf.copy()
    copy.submobjects = []
    return copy


def _faded(leaf: m.VMobject) -> m.VMobject:
    copy = leaf.copy()
    for attr in _RGBAS:
        rgbas = getattr(copy, attr).copy()
        rgbas[:, 3] = 0.0
        setattr(copy, attr, rgbas)
    return copy


class SmartMorph:
    """Mixin for Transform kinds fed by ``smart_pair``: points follow the kind's path; colours
    blend in OKLab weighted by opacity (``morph.blend_rgbas``), widths linearly, both held
    within the ends; alpha 0 and 1 draw each piece's original points and style exactly."""

    exact: Exact | tuple = ()  # set per animation by make_animation
    _colours = None  # every piece's colour rows, stacked once: one blend per frame

    def _stack(self, families: list) -> tuple:
        rows, slices, offset = [], [], 0
        for _, start, end in families:
            for attr in _RGBAS:
                s, e = getattr(start, attr), getattr(end, attr)
                slices.append((offset, len(s)))
                offset += len(s)
                rows.append((s, e))
        starts = np.concatenate([r[0] for r in rows])
        ends = np.concatenate([r[1] for r in rows])
        return starts, ends, morph.srgb_to_oklab(starts[:, :3]), morph.srgb_to_oklab(ends[:, :3]), slices

    def interpolate_mobject(self, alpha: float) -> None:
        families = list(self.get_all_families_zipped())
        if self._colours is None:  # once (begin draws alpha 0 first, after Manim's alignment)
            self._colours = self._stack(families)
        starts, ends, lab0, lab1, slices = self._colours
        subs = [self.get_sub_alpha(alpha, i, len(families)) for i in range(len(families))]
        per_row = np.repeat(np.repeat(subs, len(_RGBAS)), [n for _, n in slices])
        blended = morph.blend_rgbas(starts, ends, per_row, lab0, lab1)  # held within the ends
        for i, (piece, start, end) in enumerate(families):
            sub = subs[i]
            first, last = self.exact[i] if i < len(self.exact) else (None, None)
            if sub == 0.0:
                piece.points = (first if first is not None else start.points).copy()
            elif sub == 1.0:
                piece.points = (last if last is not None else end.points).copy()
            else:
                piece.points = self.path_func(start.points, end.points, sub)
            for k, attr in enumerate(_RGBAS):
                offset, n = slices[i * len(_RGBAS) + k]
                setattr(piece, attr, blended[offset : offset + n].copy())
            held = min(max(sub, 0.0), 1.0)  # colours and widths do not overshoot
            for attr in _LINEAR:
                a0, a1 = getattr(start, attr), getattr(end, attr)
                if held == 1.0:
                    value = a1
                elif held == 0.0:
                    value = a0
                else:
                    value = m.interpolate(a0, a1, held)
                setattr(piece, attr, value.copy() if isinstance(value, np.ndarray) else value)


SMART_CLASSES: dict[str, type[m.Animation]] = {}  # filled below from ANIMATION_CLASSES


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
SMART_CLASSES.update(
    {
        kind: type(f"Smart{ANIMATION_CLASSES[kind].__name__}", (SmartMorph, ANIMATION_CLASSES[kind]), {})
        for kind in SMART_MORPHS
    }
)


def allowed_clip_kinds(mobject_type: str) -> list[str]:
    """The allow-list (ADR 0007): clip kinds verified for this mobject type."""
    if mobject_type in CODE_TYPES | GROUP_TYPES:
        return []  # code layers animate inside their code (ADR 0019); groups have no clips (ADR 0050)
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
        if value is None or param.studio:  # studio: read by make_animation itself (ADR 0056)
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
        smart = (
            smart_pair(mobject, target) if kind in SMART_MORPHS and params.get("match") == "smart" else None
        )
        if smart is not None:  # ADR 0056: the ends aligned by core/engine/morph.py
            source_group, target_group, exact = smart
            anim = SMART_CLASSES[kind](source_group, target_group, **kwargs)
            anim.exact = exact
        else:
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
