"""Project document model: the single source of truth (ADR 0002).

A project is a list of layers. Each layer builds one Manim mobject from a spec,
owns one lane of non-overlapping animation clips (ADR 0004), and keyframe tracks
for its layer transform (position, scale, rotation, opacity).

This module is pure data and must not import Manim: it is used to validate
documents in tools that never render. The table of clip kinds lives here for
that reason; ``core/adapter.py`` maps each kind to its Manim class.
"""

from __future__ import annotations

import itertools
import math
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import (
    BaseModel,
    Field,
    PositiveFloat,
    PositiveInt,
    field_validator,
    model_serializer,
    model_validator,
)

SCHEMA_VERSION = 1
LABEL_CHARS = 32  # a text layer named by its words shows at most this many (GP)
TEXT_TYPES = frozenset({"Text", "MathTex", "Tex"})  # slow first build, cached on disk by Manim (ADR 0015)
GLYPH_COLOURS = "glyph_colours"  # a text's param: one colour (or None) per drawn glyph (ADR 0055)
RASTER_TYPES = frozenset({"ImageMobject"})  # no paths: vector-only clip kinds are refused
MEDIA_TYPES = frozenset({"ImageMobject", "SVGMobject"})  # built from a file on disk (ADR 0027)
CODE_TYPES = frozenset({"Code"})  # user Manim code, rendered to a frame cache (ADR 0019)
PYTHON_TYPES = frozenset({"Python"})  # an object built by the user's code: PARAMS + build(p) (ADR 0051)
SHAPE_TYPE = "Shape"  # an object frozen into plain vector data: points and colours (ADR 0052)
SHAPE_TYPES = frozenset({SHAPE_TYPE})
TRACE_TYPES = frozenset({"TracedPath"})  # draws where another layer has been, frame by frame (ADR 0033)
CONNECTOR_TYPES = frozenset(
    {"Connector"}
)  # a line or arrow between two layers, redrawn every frame (ADR 0036)
NUMBER_TYPES = frozenset({"DecimalNumber"})  # a number that clips count (ADR 0036)
PART_PARENT_TYPES = frozenset({"MathTex", "Tex"})  # roots that can hold part layers (ADR 0012)
AXES_OBJECTS = frozenset({"Graph", "Point", "Area", "RiemannRectangles", "AxisLabels", "GraphLabel"})
CHILD_TYPES: dict[str, frozenset[str]] = {"Axes": AXES_OBJECTS}  # child objects (ADR 0024, 0030)
LOCKED_TYPES = AXES_OBJECTS  # follow their parent exactly: only opacity is their own
# Params naming a sibling Graph (ADR 0030): (name, required).
GRAPH_PARAMS: dict[str, tuple[tuple[str, bool], ...]] = {
    "Area": (("graph", True), ("bounded_graph", False)),
    "RiemannRectangles": (("graph", True),),
    "GraphLabel": (("graph", True),),
}
NOT_PATHS = frozenset({"AxisLabels", "GraphLabel"})  # text glyphs make no useful path (ADR 0030)
# A group (ADR 0050): a root that draws nothing; its transform carries its children (parent_id = it).
GROUP_TYPE = "Group"
GROUP_TYPES = frozenset({GROUP_TYPE})
_NOT_A_PATH = (
    CODE_TYPES | RASTER_TYPES | NOT_PATHS | TRACE_TYPES | CONNECTOR_TYPES | GROUP_TYPES
)  # motion paths (ADR 0025)
_WORLD_DRAWN = TRACE_TYPES | CONNECTOR_TYPES  # drawn in world units: not inside a group (ADR 0050)
GROUPS_ONE_OBJECT = "groups are evaluated as one object"  # why the readable export falls back

Vec2 = tuple[float, float]
ClipCategory = Literal["content", "emphasis", "motion", "morph"]


@dataclass(frozen=True)
class ClipKindInfo:
    category: ClipCategory
    introducer: bool = False  # the layer becomes visible at the clip start
    remover: bool = False  # the layer disappears at the clip end
    vector_only: bool = False  # needs a VMobject (not allowed on images)
    overlay: bool = False  # draws something besides the object: both are shown (ADR 0022)
    only_types: frozenset[str] | None = None  # the object types it works on; None = any

    @property
    def clamps_alpha(self) -> bool:
        """Content and emphasis clips cannot overshoot their end state (ADR 0007)."""
        return self.category != "morph"


CLIP_KIND_INFO: dict[str, ClipKindInfo] = {
    "Create": ClipKindInfo("content", introducer=True, vector_only=True),
    "Uncreate": ClipKindInfo("content", remover=True, vector_only=True),
    "Write": ClipKindInfo("content", introducer=True, vector_only=True),
    "Unwrite": ClipKindInfo("content", remover=True, vector_only=True),
    "DrawBorderThenFill": ClipKindInfo("content", introducer=True, vector_only=True),
    "FadeIn": ClipKindInfo("content", introducer=True),
    "FadeOut": ClipKindInfo("content", remover=True),
    "GrowFromCenter": ClipKindInfo("content", introducer=True),
    "SpinInFromNothing": ClipKindInfo("content", introducer=True),
    "GrowFromEdge": ClipKindInfo("content", introducer=True),
    "SpiralIn": ClipKindInfo("content", introducer=True, vector_only=True),
    "AddTextLetterByLetter": ClipKindInfo("content", introducer=True, only_types=frozenset({"Text"})),
    "RemoveTextLetterByLetter": ClipKindInfo("content", remover=True, only_types=frozenset({"Text"})),
    "ShrinkToCenter": ClipKindInfo("content", remover=True),
    "Indicate": ClipKindInfo("emphasis"),
    "Wiggle": ClipKindInfo("emphasis", vector_only=True),
    "ApplyWave": ClipKindInfo("emphasis", vector_only=True),
    "Circumscribe": ClipKindInfo("emphasis", overlay=True),
    "Flash": ClipKindInfo("emphasis", overlay=True),
    "FocusOn": ClipKindInfo("emphasis", overlay=True),
    "MoveAlongPath": ClipKindInfo("motion"),  # along another layer's shape, roots only (ADR 0025)
    "ChangeDecimalToValue": ClipKindInfo("emphasis", only_types=NUMBER_TYPES),  # counts (ADR 0036)
    "Transform": ClipKindInfo("morph"),
    "ClockwiseTransform": ClipKindInfo("morph"),
    "CounterclockwiseTransform": ClipKindInfo("morph"),
    "FadeTransform": ClipKindInfo("morph"),
    "FadeTransformPieces": ClipKindInfo("morph"),
    "TransformMatchingShapes": ClipKindInfo("morph"),
    "TransformMatchingTex": ClipKindInfo("morph", only_types=PART_PARENT_TYPES),  # both ends TeX (ADR 0020)
}

ClipParamKind = Literal["direction", "color", "float", "choice", "layer"]
DIRECTIONS = ("UP", "DOWN", "LEFT", "RIGHT")  # Manim's names; a vector is accepted too


@dataclass(frozen=True)
class ClipParam:
    """A clip parameter the editor exposes and the random-access harness samples (ADR 0022)."""

    name: str  # the Manim keyword argument
    label: str
    kind: ClipParamKind
    default: Any = None  # None: not passed (Manim's own default, e.g. no shift)
    minimum: float | None = None
    maximum: float | None = None
    step: float = 0.1
    choices: tuple[str, ...] = ()
    studio: bool = False  # read by the editor itself, never passed to Manim (ADR 0056)
    tooltip: str = ""

    def check(self, value: Any) -> str | None:
        """Why ``value`` is not acceptable, or None."""
        if self.kind == "direction":
            if value in DIRECTIONS:
                return None
            numbers = isinstance(value, (list, tuple)) and len(value) in (2, 3)
            if numbers and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value):
                return None
            return f"a direction ({', '.join(DIRECTIONS)}) or an [x, y] vector"
        if self.kind == "color":
            return None if is_colour(value) else "a colour like #ffcc00"
        if self.kind == "float":
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                low = self.minimum if self.minimum is not None else -math.inf
                high = self.maximum if self.maximum is not None else math.inf
                if low <= value <= high:
                    return None
            return f"a number from {self.minimum:g} to {self.maximum:g}"
        if self.kind == "layer":  # another layer's id; the project checks it exists (ADR 0025)
            return None if isinstance(value, str) and value else "a layer id"
        if value in self.choices:
            return None
        return f"one of {', '.join(self.choices)}"


_YELLOW = "#FFFF00"  # Manim's YELLOW: the default of its indications
# ADR 0056: how a morph pairs the pieces and points of its two ends. Absent = classic (Manim's own
# Transform, what every older project draws); smart = core/morph.py.
MORPH_MATCHES = ("classic", "smart")
MATCH = ClipParam(
    "match",
    "Matching",
    "choice",
    default="classic",
    choices=MORPH_MATCHES,
    studio=True,
    tooltip=(
        "How the two shapes are paired while they morph.\n"
        "Classic: Manim's own Transform (points and pieces paired in order).\n"
        "Smart: pieces paired by place and shape, holes with holes, outlines started where they "
        "travel least, colours blended evenly - fewer twisted or tangled in-between frames."
    ),
)
SMART_MORPHS = frozenset({"Transform", "ClockwiseTransform", "CounterclockwiseTransform"})
SMART_MORPH = "smart morph matching is computed by the editor"  # why the readable export falls back


def new_clip_params(kind: str) -> dict[str, Any]:
    """The params a clip the editor creates starts with: smart matching for the morphs that
    offer it (ADR 0056, B73). A clip without the param - every older file, scene imports - stays
    classic."""
    return {MATCH.name: "smart"} if kind in SMART_MORPHS else {}


CLIP_PARAMS: dict[str, tuple[ClipParam, ...]] = {
    **{kind: (MATCH,) for kind in sorted(SMART_MORPHS)},
    "FadeIn": (ClipParam("shift", "Moving", "direction"),),
    "FadeOut": (ClipParam("shift", "Moving", "direction"),),
    "GrowFromEdge": (ClipParam("edge", "From edge", "direction", default="DOWN"),),
    "Indicate": (
        ClipParam("color", "Colour", "color", default=_YELLOW),
        ClipParam("scale_factor", "Scale", "float", default=1.2, minimum=1.0, maximum=3.0, step=0.05),
    ),
    "Circumscribe": (
        ClipParam("shape", "Shape", "choice", default="rectangle", choices=("rectangle", "circle")),
        ClipParam("color", "Colour", "color", default=_YELLOW),
    ),
    "Flash": (ClipParam("color", "Colour", "color", default=_YELLOW),),
    "FocusOn": (ClipParam("color", "Colour", "color", default="#888888"),),
    "ChangeDecimalToValue": (
        ClipParam("target_number", "To value", "float", default=1.0, minimum=-1e12, maximum=1e12, step=0.1),
    ),
    "MoveAlongPath": (
        ClipParam("path", "Path", "layer"),
        # ADR 0029: turn with the path, by its change of direction since the clip's start
        ClipParam("rotate", "Turn", "choice", default="no", choices=("no", "along")),
    ),
}


def clip_params(kind: str) -> tuple[ClipParam, ...]:
    return CLIP_PARAMS.get(kind, ())


class Canvas(BaseModel):
    width_px: PositiveInt = 1280
    height_px: PositiveInt = 720
    fps: PositiveInt = 30
    background: str = "#000000"
    frame_height: PositiveFloat = 8.0  # Manim units; frame_width follows from the aspect ratio
    duration: PositiveFloat = 5.0
    grow_with_content: bool = True  # the length grows to cover what an edit places past the end (P7.1)

    @property
    def frame_width(self) -> float:
        return self.frame_height * self.width_px / self.height_px


class Easing(BaseModel):
    """Either a named Manim rate function or a CSS-style cubic bezier."""

    name: str | None = "smooth"
    bezier: tuple[float, float, float, float] | None = None

    @field_validator("bezier")
    @classmethod
    def _x_in_unit_interval(cls, value):
        if value is not None and not (0 <= value[0] <= 1 and 0 <= value[2] <= 1):
            raise ValueError("cubic-bezier x1 and x2 must be within [0, 1]")
        return value


class Keyframe(BaseModel):
    t: float
    value: float | Vec2
    ease: Easing = Field(default_factory=Easing)
    # Position keys only (ADR 0026): offsets of the path's handles, relative to the value.
    in_tangent: Vec2 | None = None
    out_tangent: Vec2 | None = None

    @model_serializer(mode="wrap")
    def _omit_absent_tangents(self, handler):
        data = handler(self)
        for name in ("in_tangent", "out_tangent"):
            if data.get(name) is None:
                data.pop(name, None)  # files without curved paths save as before
        return data

    @property
    def curved(self) -> bool:
        return self.in_tangent is not None or self.out_tangent is not None


class Spec(BaseModel):
    type: str
    params: dict[str, Any] = Field(default_factory=dict)
    style: dict[str, Any] = Field(default_factory=dict)


class Clip(BaseModel):
    id: str
    kind: str
    start: float = Field(ge=0)
    duration: PositiveFloat
    ease: Easing | None = None  # None keeps the animation's own default (e.g. Indicate)
    params: dict[str, Any] = Field(default_factory=dict)
    to_layer: str | None = None  # morph clips only

    @property
    def end(self) -> float:
        return self.start + self.duration

    @property
    def info(self) -> ClipKindInfo:
        return CLIP_KIND_INFO[self.kind]

    @model_validator(mode="after")
    def _known_kind_and_target(self) -> Clip:
        if self.kind not in CLIP_KIND_INFO:
            raise ValueError(f"unknown clip kind {self.kind!r}; known: {', '.join(CLIP_KIND_INFO)}")
        is_morph = self.info.category == "morph"
        if is_morph and not self.to_layer:
            raise ValueError(f"clip {self.id!r}: {self.kind} needs to_layer (the layer it turns into)")
        if not is_morph and self.to_layer:
            raise ValueError(f"clip {self.id!r}: to_layer is only valid on morph clips")
        for param in clip_params(self.kind):  # registered params; other keys pass through (ADR 0022)
            if param.name in self.params and (problem := param.check(self.params[param.name])):
                raise ValueError(f"clip {self.id!r}: {self.kind} {param.name} must be {problem}")
        return self


class Transform2D(BaseModel):
    position: Vec2 = (0.0, 0.0)
    scale: float = 1.0
    rotation: float = 0.0  # degrees, counter-clockwise
    opacity: float = Field(default=1.0, ge=0, le=1)
    # The pivot of rotating and scaling, in local units (ADR 0021): base only, never keyed.
    anchor: Vec2 = (0.0, 0.0)

    @model_serializer(mode="wrap")
    def _omit_default_anchor(self, handler):
        data = handler(self)
        if tuple(self.anchor) == (0.0, 0.0):
            data.pop("anchor", None)  # files without anchors save as before
        return data


class Lifetime(BaseModel):
    in_: float | None = Field(default=None, alias="in")
    out: float | None = None

    model_config = {"populate_by_name": True}


TrackName = Literal["position", "scale", "rotation", "opacity"]
TRACK_NAMES: tuple[TrackName, ...] = ("position", "scale", "rotation", "opacity")


class PartKey(BaseModel):
    """The ``occurrence``-th match of ``tex`` in the parent's text (``core/parts.py``)."""

    tex: str = Field(min_length=1)
    occurrence: int = Field(default=0, ge=0)


PART_STYLE_COLOURS = ("fill", "stroke")  # a part's colours (ADR 0049), as Spec.style names them
PART_STYLE_NUMBERS = {"fill_opacity": (0.0, 1.0), "stroke_opacity": (0.0, 1.0), "stroke_width": (0.0, 50.0)}


def is_colour(value: Any) -> bool:
    """``#rgb`` or ``#rrggbb``: what the colour fields write."""
    return (
        isinstance(value, str)
        and len(value) in (4, 7)
        and value.startswith("#")
        and all(c in "0123456789abcdefABCDEF" for c in value[1:])
    )


def _style_problem(style: dict[str, Any]) -> str | None:
    """Why a part's ``style`` is not acceptable, or None (ADR 0049)."""
    for key, value in style.items():
        if key in PART_STYLE_COLOURS:
            if not is_colour(value):
                return f"{key} must be a colour like #ff0000, not {value!r}"
        elif key in PART_STYLE_NUMBERS:
            low, high = PART_STYLE_NUMBERS[key]
            number = isinstance(value, (int, float)) and not isinstance(value, bool)
            if not number or not low <= value <= high:
                return f"{key} must be a number from {low:g} to {high:g}"
        else:
            known = ", ".join((*PART_STYLE_COLOURS, *PART_STYLE_NUMBERS))
            return f"unknown style key {key!r} (known: {known})"
    return None


def _t2c_problem(t2c: Any) -> str | None:
    """Why a Text's ``t2c`` (substring -> colour, Manim's own parameter) is not acceptable."""
    if not isinstance(t2c, dict):
        return "t2c must map pieces of the text to colours"
    for piece, colour in t2c.items():
        if not isinstance(piece, str) or not piece:
            return "a coloured piece of text cannot be empty"
        if not is_colour(colour):
            return f"the colour of {piece!r} must be like #ff0000, not {colour!r}"
    return None


class Layer(BaseModel):
    id: str
    name: str = ""
    spec: Spec | None = None  # roots only; a part draws glyphs of its root (ADR 0012)
    parent_id: str | None = None
    part: PartKey | None = None
    base: Transform2D = Field(default_factory=Transform2D)
    lifetime: Lifetime = Field(default_factory=Lifetime)
    tracks: dict[TrackName, list[Keyframe]] = Field(default_factory=dict)
    clips: list[Clip] = Field(default_factory=list)
    # Parts only (ADR 0049): the colours of the part's glyphs, the keys Spec.style uses.
    style: dict[str, Any] = Field(default_factory=dict)

    @model_serializer(mode="wrap")
    def _omit_empty_style(self, handler):
        data = handler(self)
        if not self.style:
            data.pop("style", None)  # files without coloured parts save as before
        return data

    @property
    def is_part(self) -> bool:
        """A span of its root's glyphs (ADR 0012)."""
        return self.part is not None

    @property
    def is_child(self) -> bool:
        """Has a parent: a part, or a child object such as a graph (ADR 0024)."""
        return self.parent_id is not None

    @property
    def is_group(self) -> bool:
        """A group (ADR 0050): draws nothing; its transform carries its children."""
        return self.spec is not None and self.spec.type in GROUP_TYPES

    @property
    def locked(self) -> bool:
        """Follows its parent exactly (a graph on its axes): only opacity is its own."""
        return self.spec is not None and self.spec.type in LOCKED_TYPES

    @property
    def label(self) -> str:
        """How views name it: its name, else a text's own words (GP: "The Pythagorean theorem",
        not "text-1"), else its id. Never saved; renaming sets ``name``."""
        if self.name:
            return self.name
        if self.spec is not None and self.spec.type in TEXT_TYPES:
            words = " ".join(str(self.spec.params.get("text", "")).split())
            if words:
                return words if len(words) <= LABEL_CHARS else words[: LABEL_CHARS - 1] + "…"
        if self.part is not None:
            return self.part.tex
        return self.id

    @model_validator(mode="after")
    def _lane_rules(self) -> Layer:
        if self.parent_id is None and (self.spec is None or self.part is not None):
            raise ValueError(f"layer {self.id!r}: a layer without a parent needs a spec and no part key")
        if self.parent_id is not None and (self.part is None) == (self.spec is None):
            raise ValueError(
                f"layer {self.id!r}: a child layer needs a part key (a part) or its own spec (an object)"
            )
        if self.is_group and self.parent_id is not None:
            raise ValueError(f"layer {self.id!r}: a group cannot be inside another group (not yet)")
        if self.is_group and self.clips:
            raise ValueError(
                f"layer {self.id!r}: a group has no clips (not yet): put the clips on its objects"
            )
        if self.style and not self.is_part:
            raise ValueError(f"layer {self.id!r}: only part layers have a style (an object has spec.style)")
        if self.style and (problem := _style_problem(self.style)):
            raise ValueError(f"layer {self.id!r}: {problem}")
        text = self.spec is not None and self.spec.type == "Text" and "t2c" in self.spec.params
        if text and (problem := _t2c_problem(self.spec.params["t2c"])):
            raise ValueError(f"layer {self.id!r}: {problem}")
        if self.spec is not None and GLYPH_COLOURS in self.spec.params:  # ADR 0055
            from .glyph_colours import problem as glyph_problem

            if self.spec.type not in TEXT_TYPES:
                raise ValueError(f"layer {self.id!r}: only Text, MathTex and Tex have glyph colours")
            if problem := glyph_problem(self.spec.params[GLYPH_COLOURS]):
                raise ValueError(f"layer {self.id!r}: {problem}")
        if self.locked:
            _check_locked(self)
        for name, track in self.tracks.items():
            if name != "position" and any(key.curved for key in track):
                raise ValueError(f"layer {self.id!r}: only position keys can have path tangents")
        if self.spec is not None and self.spec.type in PYTHON_TYPES:
            from .python_object import spec_problem  # reads PARAMS without running the code

            problem = spec_problem(self.spec.params)
            if problem:
                raise ValueError(f"layer {self.id!r}: {problem}")
        if self.spec is not None and self.spec.type in SHAPE_TYPES:
            from .shape import spec_problem as shape_problem  # numpy, no Manim

            problem = shape_problem(self.spec.params)
            if problem:
                raise ValueError(f"layer {self.id!r}: {problem}")
        if self.spec is not None and self.spec.type == "Graph":
            from .expressions import check  # numpy, no Manim

            problem = check(self.spec.params.get("expression", ""))
            if problem:
                raise ValueError(f"layer {self.id!r}: graph expression: {problem}")
        ids = [c.id for c in self.clips]
        if len(set(ids)) != len(ids):
            raise ValueError(
                f"layer {self.id!r}: duplicate clip ids {sorted({i for i in ids if ids.count(i) > 1})}"
            )
        if self.spec is not None and self.spec.type in CODE_TYPES and self.clips:
            raise ValueError(f"layer {self.id!r}: code layers have no clips (animate inside the code)")
        if self.spec is not None and self.spec.type in TRACE_TYPES and self.clips:
            raise ValueError(f"layer {self.id!r}: a traced path has no clips (it draws where its target was)")
        if self.spec is not None and self.spec.type in CONNECTOR_TYPES and self.clips:
            raise ValueError(f"layer {self.id!r}: a connector has no clips (fade it with opacity keys)")
        if self.spec is not None:
            for clip in self.clips:
                if clip.info.vector_only and self.spec.type in RASTER_TYPES:
                    raise ValueError(
                        f"layer {self.id!r}: {clip.kind} needs a vector object, not {self.spec.type}"
                    )
                _check_only_types(self.id, clip, self.spec.type)
        ordered = sorted(self.clips, key=lambda c: c.start)
        for a, b in itertools.pairwise(ordered):
            if b.start < a.end - 1e-9:
                raise ValueError(f"layer {self.id!r}: clips {a.id!r} and {b.id!r} overlap")
            if a.info.category == "morph":
                # ADR 0005: a morph hands the layer off; nothing can follow it.
                raise ValueError(f"layer {self.id!r}: clip {b.id!r} comes after morph clip {a.id!r}")
        self.clips = ordered
        for track in self.tracks.values():
            track.sort(key=lambda k: k.t)
        return self


def keyable_props(layer: Layer) -> tuple[TrackName, ...]:
    """Transform properties the layer may key (ADR 0024: a locked child keys opacity only)."""
    return ("opacity",) if layer.locked else TRACK_NAMES


def _check_locked(layer: Layer) -> None:
    base = layer.base
    own = (
        base.position != (0.0, 0.0) or base.scale != 1.0 or base.rotation != 0.0 or base.anchor != (0.0, 0.0)
    )
    if own or set(layer.tracks) - {"opacity"}:
        raise ValueError(
            f"layer {layer.id!r}: a {layer.spec.type} follows its parent - only its opacity can change"
        )


def _check_only_types(layer_id: str, clip: Clip, mobject_type: str) -> None:
    only = clip.info.only_types
    if only is not None and mobject_type not in only:
        raise ValueError(
            f"layer {layer_id!r}: {clip.kind} needs {' or '.join(sorted(only))}, not {mobject_type}"
        )


class AudioClip(BaseModel):
    """A sound on the timeline (ADR 0034): ``duration`` seconds of the file from ``offset``,
    starting at ``start``, with a gain in dB and linear fades in and out."""

    id: str
    name: str = ""
    path: str
    start: float = Field(default=0.0, ge=0)
    offset: float = Field(default=0.0, ge=0)  # seconds of the file skipped (trimmed start)
    duration: PositiveFloat
    gain: float = 0.0  # dB
    fade_in: float = Field(default=0.0, ge=0)
    fade_out: float = Field(default=0.0, ge=0)

    @property
    def end(self) -> float:
        return self.start + self.duration

    @model_validator(mode="after")
    def _fades_fit(self) -> AudioClip:
        if self.fade_in + self.fade_out > self.duration + 1e-9:
            raise ValueError(f"audio {self.id!r}: the fades are longer than the sound")
        return self


class Cue(BaseModel):
    """A subtitle (ADR 0035): ``text`` shown from ``start`` until ``end``."""

    id: str
    start: float = Field(ge=0)
    end: float
    text: str = ""

    @model_validator(mode="after")
    def _ends_after_start(self) -> Cue:
        if self.end <= self.start:
            raise ValueError(f"subtitle {self.id!r} must end after it starts")
        return self


class Marker(BaseModel):
    """A named moment on the ruler (ADR 0037): it changes no frame, drags snap to it."""

    id: str
    t: float = Field(ge=0)
    name: str = ""
    colour: str = "#f59e0b"


class SubtitleStyle(BaseModel):
    """How every subtitle looks (ADR 0035)."""

    font_size: PositiveFloat = 26.0
    y: float = -3.52  # the centre of the subtitle, in scene units
    colour: str = "#f8fafc"
    band: bool = True  # a box behind the text
    band_colour: str = "#020617"
    band_opacity: float = Field(default=0.72, ge=0, le=1)
    fade: float = Field(default=0.15, ge=0)  # seconds in and out
    burn_in: bool = True  # drawn into the frames (an .srt is written either way)
    max_width: PositiveFloat = 12.5  # scene units; longer lines wrap, then shrink to fit


CAMERA_FIELDS = ("phi", "theta", "gamma")


class Camera(BaseModel):
    """The view the scene is drawn from (ADR 0048): Manim's ``ThreeDCamera`` angles, in degrees.

    The default is today's flat 2D view (Manim's own default orientation). While the camera is
    the default, frames are drawn by the 2D camera exactly as before; any other camera draws the
    same flat scene (everything lies on the z = 0 plane) seen from that angle.
    """

    phi: float = Field(default=0.0, ge=0, le=180)  # tilt off the z axis: 0 looks straight down it
    theta: float = Field(default=-90.0, ge=-180, le=180)  # turn about the z axis
    gamma: float = Field(default=0.0, ge=-180, le=180)  # roll about the line of sight

    model_config = {"extra": "forbid"}

    @property
    def is_default(self) -> bool:
        return (self.phi, self.theta, self.gamma) == (0.0, -90.0, 0.0)


class Project(BaseModel):
    schema_version: int = SCHEMA_VERSION
    canvas: Canvas = Field(default_factory=Canvas)
    layers: list[Layer] = Field(default_factory=list)  # first = back, last = front
    audio: list[AudioClip] = Field(default_factory=list)  # mixed together (ADR 0034)
    subtitles: list[Cue] = Field(default_factory=list)  # one lane, in time order (ADR 0035)
    subtitle_style: SubtitleStyle = Field(default_factory=SubtitleStyle)
    markers: list[Marker] = Field(default_factory=list)  # in time order, one per frame (ADR 0037)
    camera: Camera = Field(default_factory=Camera)  # the default is the flat 2D view (ADR 0048)

    @model_serializer(mode="wrap")
    def _omit_unused(self, handler):
        data = handler(self)
        if not self.audio:
            data.pop("audio", None)  # files without sound save as before
        if not self.subtitles:
            data.pop("subtitles", None)
        if self.subtitle_style == SubtitleStyle():
            data.pop("subtitle_style", None)
        if not self.markers:
            data.pop("markers", None)
        if self.camera.is_default:
            data.pop("camera", None)  # files without a camera save as before (ADR 0048)
        return data

    @model_validator(mode="after")
    def _references(self) -> Project:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version {self.schema_version} (expected {SCHEMA_VERSION})")
        ids = [layer.id for layer in self.layers] + [clip.id for clip in self.audio]
        ids += [cue.id for cue in self.subtitles] + [marker.id for marker in self.markers]
        duplicates = {i for i, count in Counter(ids).items() if count > 1}  # linear (B53)
        if duplicates:
            raise ValueError(f"duplicate layer ids: {sorted(duplicates)}")
        self.subtitles = sorted(self.subtitles, key=lambda cue: cue.start)
        for a, b in itertools.pairwise(self.subtitles):
            if b.start < a.end - 1e-9:
                raise ValueError(f"subtitles {a.id!r} and {b.id!r} overlap")
        self.markers = sorted(self.markers, key=lambda marker: marker.t)
        for a, b in itertools.pairwise(self.markers):  # one per frame is the editor's rule (ADR 0037)
            if b.t - a.t < 1e-9:
                raise ValueError(f"markers {a.id!r} and {b.id!r} are at the same time")
        self._tree_rules()
        self._path_rules()
        self._graph_refs()
        self._trace_refs()
        self._connector_refs()
        targeted: dict[str, str] = {}
        by_id = {layer.id: layer for layer in self.layers}  # once: a lookup per morph clip stays linear (B53)
        for layer in self.layers:
            for clip in layer.clips:
                if not clip.to_layer:
                    continue
                target = by_id.get(clip.to_layer)
                if target is None:
                    raise ValueError(
                        f"clip {clip.id!r} on layer {layer.id!r}: to_layer {clip.to_layer!r} is missing"
                    )
                if target.spec is not None and target.spec.type in CODE_TYPES | TRACE_TYPES | CONNECTOR_TYPES:
                    what = {"Code": "a code layer", "Connector": "a connector"}.get(
                        target.spec.type, "a traced path"
                    )
                    raise ValueError(f"clip {clip.id!r}: a layer cannot morph into {what}")
                if clip.to_layer == layer.id:
                    raise ValueError(f"clip {clip.id!r}: a layer cannot morph into itself")
                if target.is_group:
                    raise ValueError(f"clip {clip.id!r}: a layer cannot morph into a group")
                if _group_of(by_id, layer) != _group_of(by_id, target):  # ADR 0050
                    raise ValueError(
                        f"clip {clip.id!r}: a morph stays inside its group - {layer.id!r} and "
                        f"{target.id!r} are not in the same group"
                    )
                if clip.to_layer in targeted:
                    raise ValueError(
                        f"layer {clip.to_layer!r} is the target of two morphs "
                        f"({targeted[clip.to_layer]!r} and {layer.id!r})"
                    )
                targeted[clip.to_layer] = layer.id
        return self

    def _path_rules(self) -> None:
        """ADR 0025: motion clips move root objects along another layer's shape."""
        by_id = {layer.id: layer for layer in self.layers}
        for layer in self.layers:
            for clip in layer.clips:
                if clip.info.category != "motion":
                    continue
                if layer.is_child and _group_of(by_id, layer) is None:  # an object in a group travels
                    raise ValueError(f"clip {clip.id!r}: {clip.kind} moves whole objects, not {layer.id!r}")
                path = by_id.get(clip.params.get("path"))
                if path is None:
                    raise ValueError(f"clip {clip.id!r}: {clip.kind} needs a path layer")
                if _within(by_id, path, layer.id) or path.is_part or path.spec.type in _NOT_A_PATH:
                    raise ValueError(f"clip {clip.id!r}: {path.id!r} cannot be its path")

    def _graph_refs(self) -> None:
        """ADR 0030: an area, rectangles or a graph label name a graph on the same axes."""
        by_id = {layer.id: layer for layer in self.layers}
        for layer in self.layers:
            for name, required in GRAPH_PARAMS.get(layer.spec.type if layer.spec else "", ()):
                target = layer.spec.params.get(name) or None
                if target is None and not required:
                    continue
                graph = by_id.get(target)
                if (
                    graph is None
                    or graph.spec is None
                    or graph.spec.type != "Graph"
                    or (graph.parent_id != layer.parent_id)
                ):
                    raise ValueError(
                        f"layer {layer.id!r}: {name} must name a graph on the same axes, not {target!r}"
                    )

    def _trace_refs(self) -> None:
        """ADR 0033: a traced path follows another object - not a trace, not a code layer."""
        by_id = {layer.id: layer for layer in self.layers}
        for layer in self.layers:
            if layer.spec is None or layer.spec.type not in TRACE_TYPES:
                continue
            target_id = layer.spec.params.get("target") or ""
            if not _traceable(layer.id, by_id.get(target_id)):
                what = "is missing" if target_id not in by_id else "cannot be traced"
                raise ValueError(f"layer {layer.id!r}: the traced layer {target_id!r} {what}")

    def traceable_ids(self, trace_id: str) -> list[str]:
        """The layers the traced path ``trace_id`` may follow (ADR 0033), or the connector
        ``trace_id`` may join (ADR 0036): not itself, a trace, a connector or a code layer."""
        return [x.id for x in self.layers if _traceable(trace_id, x)]

    def _connector_refs(self) -> None:
        """ADR 0036: a connector joins two different layers it could trace."""
        by_id = {layer.id: layer for layer in self.layers}
        for layer in self.layers:
            if layer.spec is None or layer.spec.type not in CONNECTOR_TYPES:
                continue
            ends = [layer.spec.params.get(name) or "" for name in ("source", "target")]
            for end in ends:
                if not _traceable(layer.id, by_id.get(end)):
                    what = "is missing" if end not in by_id else "cannot be joined"
                    raise ValueError(f"layer {layer.id!r}: the connected layer {end!r} {what}")
            if ends[0] == ends[1]:
                raise ValueError(f"layer {layer.id!r}: a connector joins two different layers")

    def connectors_of(self, layer_ids: set[str]) -> set[str]:
        """Connectors joining any of ``layer_ids`` (ADR 0036)."""
        return {
            x.id
            for x in self.layers
            if x.spec is not None
            and x.spec.type in CONNECTOR_TYPES
            and {x.spec.params.get("source"), x.spec.params.get("target")} & layer_ids
        }

    def traces_of(self, layer_ids: set[str]) -> set[str]:
        """Traced paths following any of ``layer_ids``."""
        return {
            x.id
            for x in self.layers
            if x.spec is not None and x.spec.type in TRACE_TYPES and x.spec.params.get("target") in layer_ids
        }

    def referenced_graphs(self, layer: Layer, by_id: dict[str, Layer] | None = None) -> dict[str, Spec]:
        """The specs of the graphs ``layer`` is built from (ADR 0030), by id. Callers asking about
        many layers pass the project's ``{id: layer}`` map instead of having one built per call (B53)."""
        if layer.spec is None:
            return {}
        names = [n for n, _ in GRAPH_PARAMS.get(layer.spec.type, ())]
        if not names:
            return {}  # nearly every layer: no lookup table needed
        ids = [layer.spec.params.get(n) for n in names]
        if by_id is None:
            by_id = {other.id: other for other in self.layers}
        return {i: by_id[i].spec for i in ids if i and i in by_id}

    def _tree_rules(self) -> None:
        """ADR 0012: parts hang under MathTex/Tex roots; no clip on a part overlaps an ancestor's
        clip. ADR 0024: child objects hang under a root that accepts their type."""
        by_id = {layer.id: layer for layer in self.layers}
        parents = {layer.parent_id for layer in self.layers}
        for layer in self.layers:
            if layer.parent_id is None:
                if layer.spec.type in LOCKED_TYPES:
                    owners = sorted(t for t, kids in CHILD_TYPES.items() if layer.spec.type in kids)
                    raise ValueError(
                        f"layer {layer.id!r}: a {layer.spec.type} needs a parent ({', '.join(owners)})"
                    )
                continue
            if layer.parent_id not in by_id:
                raise ValueError(f"layer {layer.id!r}: parent {layer.parent_id!r} is missing")
            seen, node = {layer.id}, by_id[layer.parent_id]
            while node.parent_id is not None:
                if node.id in seen:
                    raise ValueError(f"layer {layer.id!r}: its parents form a cycle")
                seen.add(node.id)
                node = by_id[node.parent_id]
            if by_id[layer.parent_id].is_group:  # ADR 0050: v1 groups hold plain objects
                _check_group_member(layer, layer.id in parents)
            elif not layer.is_part:
                parent = by_id[layer.parent_id]
                if parent.spec is None or layer.spec.type not in CHILD_TYPES.get(parent.spec.type, ()):
                    raise ValueError(
                        f"layer {layer.id!r}: a {layer.spec.type} cannot be a child of "
                        f"{parent.spec.type if parent.spec else 'a part'}"
                    )
            elif node.spec.type not in PART_PARENT_TYPES:
                raise ValueError(
                    f"layer {layer.id!r}: parts are only supported on MathTex and Tex, not {node.spec.type}"
                )
        for layer in self.layers:
            if layer.is_part:  # a part animates glyphs of its root's type
                node = layer
                while node.parent_id is not None:
                    node = by_id[node.parent_id]
                for clip in layer.clips:
                    _check_only_types(layer.id, clip, node.spec.type)
            for clip in layer.clips:
                if clip.to_layer and layer.is_part:
                    raise ValueError(
                        f"clip {clip.id!r} on part {layer.id!r}: a part cannot morph; "
                        "morph its object (TransformMatchingTex moves the terms)"
                    )
                if clip.kind == "TransformMatchingTex":
                    target = by_id.get(clip.to_layer)
                    kinds = {layer.spec.type if layer.spec else None, target.spec.type if target else None}
                    if not kinds <= PART_PARENT_TYPES:
                        raise ValueError(
                            f"clip {clip.id!r}: TransformMatchingTex needs MathTex or Tex at both ends"
                        )
            node = layer
            while layer.is_child and node.parent_id is not None:  # members share their object's clips
                node = by_id[node.parent_id]
                for clip in layer.clips:
                    for other in node.clips:
                        if clip.start < other.end - 1e-9 and other.start < clip.end - 1e-9:
                            raise ValueError(
                                f"clip {clip.id!r} on {layer.id!r} overlaps clip {other.id!r} "
                                f"on {node.id!r}, which contains it"
                            )
                        if other.to_layer and clip.start >= other.start - 1e-9:
                            raise ValueError(
                                f"clip {clip.id!r} on {layer.id!r} starts after {node.id!r} begins "
                                f"morphing ({other.id!r}): it would never be seen"
                            )

    def path_layers(self, mover_id: str) -> list[Layer]:
        """Layers ``mover_id`` may travel along (ADR 0025): not itself or its descendants,
        not parts, code, images, traces or connectors."""
        inside = {mover_id} | {d.id for d in self.descendants(mover_id)}
        return [
            layer
            for layer in self.layers
            if layer.id not in inside and not layer.is_part and layer.spec.type not in _NOT_A_PATH
        ]

    def morph_sources(self) -> dict[str, Clip]:
        """target layer id -> the morph clip that hands off to it (ADR 0005)."""
        return {clip.to_layer: clip for layer in self.layers for clip in layer.clips if clip.to_layer}

    def lifetime(self, layer_id: str) -> tuple[float, float]:
        """When a layer is visible; a part's lifetime is clamped to its parent's (ADR 0012)."""
        layer = self.layer(layer_id)
        sources = self.morph_sources()
        if layer.is_group:  # the span of its children (ADR 0050)
            return group_span(layer, (infer_lifetime(c, sources.get(c.id)) for c in self.children(layer_id)))
        start, end = infer_lifetime(layer, sources.get(layer_id))
        if layer.parent_id is not None:
            parent_start, parent_end = self.lifetime(layer.parent_id)
            start, end = max(start, parent_start), min(end, parent_end)
        return start, end

    # -- the layer tree (ADR 0012) ---------------------------------------------

    def children(self, layer_id: str) -> list[Layer]:
        return [layer for layer in self.layers if layer.parent_id == layer_id]

    def descendants(self, layer_id: str) -> list[Layer]:
        """Parts under ``layer_id``, parents before children, siblings in list order."""
        out = []
        for child in self.children(layer_id):
            out.append(child)
            out.extend(self.descendants(child.id))
        return out

    def ancestors(self, layer_id: str) -> list[Layer]:
        """Parent first, root last."""
        out, layer = [], self.layer(layer_id)
        while layer.parent_id is not None:
            layer = self.layer(layer.parent_id)
            out.append(layer)
        return out

    def root_of(self, layer_id: str) -> Layer:
        """The object layer a part belongs to (the layer itself for a root)."""
        layer = self.layer(layer_id)
        return self.ancestors(layer_id)[-1] if layer.parent_id is not None else layer

    def roots(self) -> list[Layer]:
        return [layer for layer in self.layers if layer.parent_id is None]

    def layer(self, layer_id: str) -> Layer:
        for layer in self.layers:
            if layer.id == layer_id:
                return layer
        raise KeyError(layer_id)


def _traceable(own_id: str, other: Layer | None) -> bool:
    """Whether the trace or connector ``own_id`` may follow ``other`` (ADR 0033, 0036): a layer
    that is not itself, a trace, a connector or a code layer."""
    return (
        other is not None
        and other.id != own_id
        and not (other.spec is not None and other.spec.type in TRACE_TYPES | CODE_TYPES | CONNECTOR_TYPES)
    )


def _check_group_member(layer: Layer, has_children: bool) -> None:
    """ADR 0050: a v1 group holds whole plain objects - no parts, no groups, no objects with parts
    or objects on axes, nothing drawn in world units (a traced path, a connector)."""
    if layer.is_part:
        raise ValueError(f"layer {layer.id!r}: a part belongs to its MathTex or Tex, not to a group")
    if layer.spec.type in LOCKED_TYPES:
        raise ValueError(f"layer {layer.id!r}: a {layer.spec.type} belongs to its axes, not to a group")
    if has_children:
        raise ValueError(
            f"layer {layer.id!r}: an object with parts or objects on axes cannot be in a group (not yet)"
        )
    if layer.spec.type in _WORLD_DRAWN:
        what = "a traced path" if layer.spec.type in TRACE_TYPES else "a connector"
        raise ValueError(
            f"layer {layer.id!r}: {what} is drawn where its layers are, so it cannot be in a group"
        )


def _group_of(by_id: dict[str, Layer], layer: Layer) -> str | None:
    """The group ``layer`` is in (ADR 0050), or None."""
    parent = by_id.get(layer.parent_id) if layer.parent_id is not None else None
    return parent.id if parent is not None and parent.is_group else None


def group_span(group: Layer, spans: Iterable[tuple[float, float]]) -> tuple[float, float]:
    """When a group is visible (ADR 0050): its explicit Appears / Disappears, else the span of its
    children's own lifetimes (``spans``: each child's ``infer_lifetime``, not clamped). A group with
    no children is never visible."""
    spans = list(spans)
    start, end = group.lifetime.in_, group.lifetime.out
    if start is None:
        start = min((s for s, _ in spans), default=0.0)
    if end is None:
        end = max((e for _, e in spans), default=0.0)
    return start, end


def _within(by_id: dict[str, Layer], node: Layer, root_id: str) -> bool:
    """Whether ``node`` is ``root_id`` or hangs somewhere under it (parents are known to exist)."""
    while node.id != root_id:
        if node.parent_id is None:
            return False
        node = by_id[node.parent_id]
    return True


def infer_lifetime(layer: Layer, morph_in: Clip | None = None) -> tuple[float, float]:
    """When a layer is visible: ``[start, end)`` in seconds (docs/project-format.md).

    An explicit lifetime wins. Otherwise the layer appears at its first clip if
    that clip is an introducer, or when the morph targeting it (``morph_in``)
    ends, else at 0; it disappears after its first remover or morph clip.
    """
    start, end = layer.lifetime.in_, layer.lifetime.out
    if start is None:
        start = 0.0
        if morph_in is not None:
            start = morph_in.end
        elif layer.clips and layer.clips[0].info.introducer:
            start = layer.clips[0].start
    if end is None:
        end = math.inf
        for clip in layer.clips:
            if clip.info.remover or clip.info.category == "morph":
                end = clip.end
                break
    return start, end
