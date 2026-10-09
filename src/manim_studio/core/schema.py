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
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field, PositiveFloat, PositiveInt, field_validator, model_validator

SCHEMA_VERSION = 1
TEXT_TYPES = frozenset({"Text", "MathTex", "Tex"})  # slow first build, cached on disk by Manim (ADR 0015)
RASTER_TYPES = frozenset({"ImageMobject"})  # no paths: vector-only clip kinds are refused

Vec2 = tuple[float, float]
ClipCategory = Literal["content", "emphasis", "morph"]


@dataclass(frozen=True)
class ClipKindInfo:
    category: ClipCategory
    introducer: bool = False  # the layer becomes visible at the clip start
    remover: bool = False  # the layer disappears at the clip end
    vector_only: bool = False  # needs a VMobject (not allowed on images)

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
    "ShrinkToCenter": ClipKindInfo("content", remover=True),
    "Indicate": ClipKindInfo("emphasis"),
    "Wiggle": ClipKindInfo("emphasis", vector_only=True),
    "ApplyWave": ClipKindInfo("emphasis", vector_only=True),
    "Transform": ClipKindInfo("morph"),
    "FadeTransform": ClipKindInfo("morph"),
    "TransformMatchingShapes": ClipKindInfo("morph"),
}


class Canvas(BaseModel):
    width_px: PositiveInt = 1280
    height_px: PositiveInt = 720
    fps: PositiveInt = 30
    background: str = "#000000"
    frame_height: PositiveFloat = 8.0  # Manim units; frame_width follows from the aspect ratio
    duration: PositiveFloat = 5.0

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
        return self


class Transform2D(BaseModel):
    position: Vec2 = (0.0, 0.0)
    scale: float = 1.0
    rotation: float = 0.0  # degrees, counter-clockwise
    opacity: float = Field(default=1.0, ge=0, le=1)


class Lifetime(BaseModel):
    in_: float | None = Field(default=None, alias="in")
    out: float | None = None

    model_config = {"populate_by_name": True}


TrackName = Literal["position", "scale", "rotation", "opacity"]


class Layer(BaseModel):
    id: str
    name: str = ""
    spec: Spec
    base: Transform2D = Field(default_factory=Transform2D)
    lifetime: Lifetime = Field(default_factory=Lifetime)
    tracks: dict[TrackName, list[Keyframe]] = Field(default_factory=dict)
    clips: list[Clip] = Field(default_factory=list)

    @model_validator(mode="after")
    def _lane_rules(self) -> Layer:
        ids = [c.id for c in self.clips]
        if len(set(ids)) != len(ids):
            raise ValueError(
                f"layer {self.id!r}: duplicate clip ids {sorted({i for i in ids if ids.count(i) > 1})}"
            )
        if self.spec.type in RASTER_TYPES:
            for clip in self.clips:
                if clip.info.vector_only:
                    raise ValueError(
                        f"layer {self.id!r}: {clip.kind} needs a vector object, not {self.spec.type}"
                    )
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


class Project(BaseModel):
    schema_version: int = SCHEMA_VERSION
    canvas: Canvas = Field(default_factory=Canvas)
    layers: list[Layer] = Field(default_factory=list)  # first = back, last = front

    @model_validator(mode="after")
    def _references(self) -> Project:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version {self.schema_version} (expected {SCHEMA_VERSION})")
        ids = [layer.id for layer in self.layers]
        duplicates = {i for i in ids if ids.count(i) > 1}
        if duplicates:
            raise ValueError(f"duplicate layer ids: {sorted(duplicates)}")
        targeted: dict[str, str] = {}
        for layer in self.layers:
            for clip in layer.clips:
                if not clip.to_layer:
                    continue
                if clip.to_layer not in ids:
                    raise ValueError(
                        f"clip {clip.id!r} on layer {layer.id!r}: to_layer {clip.to_layer!r} is missing"
                    )
                if clip.to_layer == layer.id:
                    raise ValueError(f"clip {clip.id!r}: a layer cannot morph into itself")
                if clip.to_layer in targeted:
                    raise ValueError(
                        f"layer {clip.to_layer!r} is the target of two morphs "
                        f"({targeted[clip.to_layer]!r} and {layer.id!r})"
                    )
                targeted[clip.to_layer] = layer.id
        return self

    def morph_sources(self) -> dict[str, Clip]:
        """target layer id -> the morph clip that hands off to it (ADR 0005)."""
        return {clip.to_layer: clip for layer in self.layers for clip in layer.clips if clip.to_layer}

    def lifetime(self, layer_id: str) -> tuple[float, float]:
        return infer_lifetime(self.layer(layer_id), self.morph_sources().get(layer_id))

    def layer(self, layer_id: str) -> Layer:
        for layer in self.layers:
            if layer.id == layer_id:
                return layer
        raise KeyError(layer_id)


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
