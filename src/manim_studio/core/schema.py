"""Project document model: the single source of truth.

A project is a list of layers. Each layer builds one Manim mobject from a spec,
owns one lane of non-overlapping animation clips, and keyframe tracks for its
layer transform (position, scale, rotation, opacity). See DESIGN.md.
"""

from __future__ import annotations

import itertools
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

SCHEMA_VERSION = 1

Vec2 = tuple[float, float]


class Canvas(BaseModel):
    width_px: int = 1280
    height_px: int = 720
    fps: int = 30
    background: str = "#000000"
    frame_height: float = 8.0  # Manim units; frame_width follows from the aspect ratio
    duration: float = 5.0

    @property
    def frame_width(self) -> float:
        return self.frame_height * self.width_px / self.height_px


class Easing(BaseModel):
    """Either a named Manim rate function or a CSS-style cubic bezier."""

    name: str | None = "smooth"
    bezier: tuple[float, float, float, float] | None = None


class Keyframe(BaseModel):
    t: float
    value: float | Vec2
    ease: Easing = Field(default_factory=Easing)


class Spec(BaseModel):
    type: str
    params: dict[str, Any] = Field(default_factory=dict)
    style: dict[str, Any] = Field(default_factory=dict)


ClipCategory = Literal["content", "emphasis", "morph"]


class Clip(BaseModel):
    id: str
    kind: str
    start: float
    duration: float
    ease: Easing | None = None  # None keeps the animation's own default (e.g. Indicate)
    params: dict[str, Any] = Field(default_factory=dict)
    to_layer: str | None = None  # morph clips only

    @property
    def end(self) -> float:
        return self.start + self.duration


class Transform2D(BaseModel):
    position: Vec2 = (0.0, 0.0)
    scale: float = 1.0
    rotation: float = 0.0  # degrees, counter-clockwise
    opacity: float = 1.0


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
    def _clips_do_not_overlap(self) -> Layer:
        ordered = sorted(self.clips, key=lambda c: c.start)
        for a, b in itertools.pairwise(ordered):
            if b.start < a.end - 1e-9:
                raise ValueError(f"layer {self.id!r}: clips {a.id!r} and {b.id!r} overlap")
        self.clips = ordered
        for track in self.tracks.values():
            track.sort(key=lambda k: k.t)
        return self


class Project(BaseModel):
    schema_version: int = SCHEMA_VERSION
    canvas: Canvas = Field(default_factory=Canvas)
    layers: list[Layer] = Field(default_factory=list)  # first = back, last = front

    def layer(self, layer_id: str) -> Layer:
        for layer in self.layers:
            if layer.id == layer_id:
                return layer
        raise KeyError(layer_id)
