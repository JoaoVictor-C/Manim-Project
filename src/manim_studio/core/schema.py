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
CODE_TYPES = frozenset({"Code"})  # user Manim code, rendered to a frame cache (ADR 0019)

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
    "TransformMatchingTex": ClipKindInfo("morph"),  # MathTex/Tex only (ADR 0020)
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
PART_PARENT_TYPES = frozenset({"MathTex", "Tex"})  # roots that can hold part layers (ADR 0012)


class PartKey(BaseModel):
    """The ``occurrence``-th match of ``tex`` in the parent's text (``core/parts.py``)."""

    tex: str = Field(min_length=1)
    occurrence: int = Field(default=0, ge=0)


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

    @property
    def is_part(self) -> bool:
        return self.parent_id is not None

    @model_validator(mode="after")
    def _lane_rules(self) -> Layer:
        if self.parent_id is None and (self.spec is None or self.part is not None):
            raise ValueError(f"layer {self.id!r}: a layer without a parent needs a spec and no part key")
        if self.parent_id is not None and (self.part is None or self.spec is not None):
            raise ValueError(f"layer {self.id!r}: a part layer needs a part key and no spec")
        ids = [c.id for c in self.clips]
        if len(set(ids)) != len(ids):
            raise ValueError(
                f"layer {self.id!r}: duplicate clip ids {sorted({i for i in ids if ids.count(i) > 1})}"
            )
        if self.spec is not None and self.spec.type in CODE_TYPES and self.clips:
            raise ValueError(f"layer {self.id!r}: code layers have no clips (animate inside the code)")
        if self.spec is not None and self.spec.type in RASTER_TYPES:
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
        self._tree_rules()
        targeted: dict[str, str] = {}
        for layer in self.layers:
            for clip in layer.clips:
                if not clip.to_layer:
                    continue
                if clip.to_layer not in ids:
                    raise ValueError(
                        f"clip {clip.id!r} on layer {layer.id!r}: to_layer {clip.to_layer!r} is missing"
                    )
                target = next(other for other in self.layers if other.id == clip.to_layer)
                if target.spec is not None and target.spec.type in CODE_TYPES:
                    raise ValueError(f"clip {clip.id!r}: a layer cannot morph into a code layer")
                if clip.to_layer == layer.id:
                    raise ValueError(f"clip {clip.id!r}: a layer cannot morph into itself")
                if clip.to_layer in targeted:
                    raise ValueError(
                        f"layer {clip.to_layer!r} is the target of two morphs "
                        f"({targeted[clip.to_layer]!r} and {layer.id!r})"
                    )
                targeted[clip.to_layer] = layer.id
        return self

    def _tree_rules(self) -> None:
        """ADR 0012: parts hang under MathTex/Tex roots; no clip overlaps an ancestor's clip."""
        by_id = {layer.id: layer for layer in self.layers}
        for layer in self.layers:
            if layer.parent_id is None:
                continue
            if layer.parent_id not in by_id:
                raise ValueError(f"layer {layer.id!r}: parent {layer.parent_id!r} is missing")
            seen, node = {layer.id}, by_id[layer.parent_id]
            while node.parent_id is not None:
                if node.id in seen:
                    raise ValueError(f"layer {layer.id!r}: its parents form a cycle")
                seen.add(node.id)
                node = by_id[node.parent_id]
            if node.spec.type not in PART_PARENT_TYPES:
                raise ValueError(
                    f"layer {layer.id!r}: parts are only supported on MathTex and Tex, not {node.spec.type}"
                )
        for layer in self.layers:
            for clip in layer.clips:
                if clip.to_layer and layer.parent_id is not None:
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
            while node.parent_id is not None:
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

    def morph_sources(self) -> dict[str, Clip]:
        """target layer id -> the morph clip that hands off to it (ADR 0005)."""
        return {clip.to_layer: clip for layer in self.layers for clip in layer.clips if clip.to_layer}

    def lifetime(self, layer_id: str) -> tuple[float, float]:
        """When a layer is visible; a part's lifetime is clamped to its parent's (ADR 0012)."""
        layer = self.layer(layer_id)
        start, end = infer_lifetime(layer, self.morph_sources().get(layer_id))
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
