"""Presets, themes and templates (ADR 0039): library items stored as JSON.

A **preset** is a bundle of clips and keys applied to one layer at the playhead;
a **theme** recolours layers and the background; a **template** is a group of
layers inserted at the playhead. Built-ins ship in ``manim_studio/library/``,
the user's own in a user folder (``MANIM_STUDIO_LIBRARY``, default
``~/.manim-studio/library``). A file that cannot be read, or that was written
by a newer version, is skipped with a message, as plugins are (ADR 0032).

Applying returns ordinary ``core.edits`` edits: one validated snapshot, one undo
step, nothing the exports need to know about.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, PositiveFloat, ValidationError, field_validator, model_validator

from . import edits
from .edits import Edit, EditError
from .schema import (
    CLIP_KIND_INFO,
    CONNECTOR_TYPES,
    NUMBER_TYPES,
    PYTHON_TYPES,
    TEXT_TYPES,
    TRACE_TYPES,
    Easing,
    Layer,
    Project,
    TrackName,
    Vec2,
    clip_params,
    keyable_props,
)

FORMAT = "manim-studio-library"
VERSION = 1
BUILTIN_FOLDER = Path(__file__).resolve().parent.parent / "library"
DEFAULT_USER_FOLDER = Path.home() / ".manim-studio" / "library"
Category = Literal["entrance", "emphasis", "exit", "motion"]
CATEGORIES: tuple[Category, ...] = ("entrance", "emphasis", "exit", "motion")


def _colour(value: str) -> str:
    ok = isinstance(value, str) and len(value) in (4, 7) and value.startswith("#")
    if not ok or any(c not in "0123456789abcdefABCDEF" for c in value[1:]):
        raise ValueError(f"{value!r} is not a colour like #ffcc00")
    return value


class PresetClip(BaseModel):
    """A clip of a preset: the first of ``kinds`` the layer accepts, ``offset`` s after the playhead."""

    kinds: list[str] = Field(min_length=1)
    offset: float = Field(default=0.0, ge=0)
    duration: PositiveFloat
    ease: Easing | None = None
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("kinds")
    @classmethod
    def _known(cls, kinds: list[str]) -> list[str]:
        for kind in kinds:
            info = CLIP_KIND_INFO.get(kind)
            if info is None:
                raise ValueError(f"unknown clip kind {kind!r}")
            if info.category in ("morph", "motion"):  # they need another layer: not a preset's
                raise ValueError(f"{kind} needs another layer and cannot be in a preset")
        return kinds


class PresetKey(BaseModel):
    """A key ``dt`` s after the playhead: a position offset, a scale factor, a rotation delta in
    degrees, or an opacity, relative to the layer's transform when the preset is applied."""

    dt: float = Field(ge=0)
    value: float | Vec2
    ease: Easing = Field(default_factory=Easing)


class Preset(BaseModel):
    kind: Literal["preset"] = "preset"
    name: str = Field(min_length=1)
    category: Category
    description: str = ""
    clips: list[PresetClip] = Field(default_factory=list)
    keys: dict[TrackName, list[PresetKey]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _something(self) -> Preset:
        if not self.clips and not any(self.keys.values()):
            raise ValueError(f"preset {self.name!r} has no clips and no keys")
        for prop, track in self.keys.items():
            for key in track:
                if (prop == "position") != isinstance(key.value, tuple):
                    raise ValueError(f"preset {self.name!r}: {prop} keys must be {_shape(prop)}")
        return self


def _shape(prop: str) -> str:
    return "[x, y] offsets" if prop == "position" else "numbers"


class Theme(BaseModel):
    kind: Literal["theme"] = "theme"
    name: str = Field(min_length=1)
    description: str = ""
    background: str
    text: str
    shape: str
    accent: str

    @field_validator("background", "text", "shape", "accent")
    @classmethod
    def _colours(cls, value: str) -> str:
        return _colour(value)


class Template(BaseModel):
    """A group of layers whose times start at 0, inserted at the playhead (P5e.2)."""

    kind: Literal["template"] = "template"
    name: str = Field(min_length=1)
    description: str = ""
    layers: list[Layer] = Field(min_length=1)

    @model_validator(mode="after")
    def _a_valid_fragment(self) -> Template:
        Project(layers=self.layers)  # references inside it, parts, objects on axes (raises)
        return self


Item = Preset | Theme | Template
_KINDS: dict[str, type[BaseModel]] = {"preset": Preset, "theme": Theme, "template": Template}


# -- loading ---------------------------------------------------------------------------------------


@dataclass
class Library:
    presets: list[Preset] = field(default_factory=list)
    themes: list[Theme] = field(default_factory=list)
    templates: list[Template] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)  # files skipped, and why

    def presets_in(self, category: Category) -> list[Preset]:
        return [p for p in self.presets if p.category == category]

    def add(self, item: Item) -> None:
        """Add ``item``, replacing one of the same kind and name (the user's wins over a built-in)."""
        items = {"preset": self.presets, "theme": self.themes, "template": self.templates}[item.kind]
        items[:] = [x for x in items if x.name != item.name] + [item]


def user_folder() -> Path:
    value = os.environ.get("MANIM_STUDIO_LIBRARY")
    return Path(value) if value else DEFAULT_USER_FOLDER


def item_from_json(data: dict[str, Any]) -> Item:
    """A library item from its file's JSON (``ValueError`` saying why it cannot be used)."""
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ValueError("not a Manim Studio library file")
    version = data.get("version")
    if not isinstance(version, int) or version > VERSION:
        raise ValueError(f"written by a newer Manim Studio (version {version})")
    kind = data.get("kind")
    if kind not in _KINDS:
        raise ValueError(f"unknown kind {kind!r}")
    body = {k: v for k, v in data.items() if k not in ("format", "version")}
    try:
        return _KINDS[kind].model_validate(body)
    except ValidationError as exc:
        error = exc.errors()[0]
        where = ".".join(str(p) for p in error["loc"])
        raise ValueError(f"{where}: {error['msg']}" if where else error["msg"]) from None


def item_to_json(item: Item) -> dict[str, Any]:
    return {
        "format": FORMAT,
        "version": VERSION,
        **item.model_dump(mode="json", by_alias=True, exclude_none=True),
    }


def load_library(folders: list[Path] | None = None) -> Library:
    """Every item in ``folders`` (built-ins, then the user's), later ones replacing earlier ones
    of the same kind and name; files that cannot be used are listed in ``problems``."""
    library = Library()
    for folder in folders if folders is not None else [BUILTIN_FOLDER, user_folder()]:
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.json")):
            try:
                library.add(item_from_json(json.loads(path.read_text(encoding="utf-8"))))
            except (OSError, ValueError) as exc:  # JSONDecodeError is a ValueError
                library.problems.append(f"{path.name}: {exc}")
    return library


def save_item(item: Item, folder: Path | None = None) -> Path:
    """Write ``item`` to the user folder (a file named after it); returns the path."""
    folder = folder or user_folder()
    folder.mkdir(parents=True, exist_ok=True)
    stem = "".join(c if c.isalnum() or c in " -_" else "_" for c in item.name).strip() or item.kind
    path = folder / f"{item.kind}-{stem}.json"
    path.write_text(json.dumps(item_to_json(item), indent=1), encoding="utf-8")
    return path


# -- presets -----------------------------------------------------------------------------------------


def apply_preset(project: Project, layer_id: str, preset: Preset, t: float) -> Edit:
    """``preset`` on layer ``layer_id`` starting at ``t`` (on the frame grid), whole or not at all:
    ``EditError`` says why it cannot be applied (ADR 0039)."""
    from . import adapter  # the clip allow-list (imports Manim)
    from .evaluator import layer_transform  # how tracks are sampled lives with the evaluator

    try:
        layer = project.layer(layer_id)
    except KeyError:
        raise EditError(f"no layer {layer_id!r}") from None
    fps = project.canvas.fps
    t = max(0.0, round(t * fps) / fps)
    type_name = (layer.spec or project.root_of(layer_id).spec).type
    what = _describe(project, layer)
    allowed = set(adapter.allowed_clip_kinds(type_name))
    chosen = []
    for clip in preset.clips:
        kind = next((k for k in clip.kinds if k in allowed), None)
        if kind is None:
            raise EditError(f"{preset.name} cannot be used on {what}")
        chosen.append((kind, clip))
    for prop, track in preset.keys.items():
        if track and prop not in keyable_props(layer):
            raise EditError(f"{preset.name} cannot be used on {what}: only its opacity can change")
    end = max(
        [t + c.offset + c.duration for c in preset.clips]
        + [t + k.dt for tr in preset.keys.values() for k in tr]
    )
    if end > project.canvas.duration + 1e-9:
        raise EditError(
            f"{preset.name} needs until {end:g} s; the scene ends at {project.canvas.duration:g} s"
        )

    result = project
    try:
        for kind, clip in chosen:
            names = {p.name for p in clip_params(kind)}  # a fallback kind gets only the params it knows
            params = {k: v for k, v in clip.params.items() if k in names}
            start = round((t + clip.offset) * fps) / fps
            result = edits.add_clip(
                result, layer_id, kind, start, clip.duration, ease=clip.ease, params=params
            ).project
        current = layer_transform(layer, t)
        for prop, track in preset.keys.items():
            if not track:
                continue
            now = getattr(current, prop)
            values = [_absolute(prop, key.value, now) for key in track]
            earlier = [k for k in layer.tracks.get(prop, []) if k.t < t - 0.5 / fps]
            if not earlier and t >= 1 / fps and values[0] != now:  # keep the past as it was
                result = edits.set_key(result, layer_id, prop, t - 1 / fps, now).project
            for key, value in zip(track, values, strict=True):
                at = round((t + key.dt) * fps) / fps  # on the frame grid, as set_key puts it
                result = edits.set_key(result, layer_id, prop, at, value).project
                result = edits.set_key_ease(result, layer_id, at, key.ease, [prop]).project
    except ValidationError as exc:
        reason = exc.errors()[0]["msg"].removeprefix("Value error, ")
        raise EditError(f"{preset.name} does not fit at {t:g} s: {reason}") from None
    kind, layer_ids = edits.classify(project, result)
    return Edit(result, kind, layer_ids)


def _absolute(prop: str, value: float | Vec2, now: Any) -> float | Vec2:
    if prop == "position":
        return (now[0] + value[0], now[1] + value[1])
    if prop == "scale":
        return now * value
    if prop == "rotation":
        return now + value
    return value  # opacity


def _describe(project: Project, layer: Layer) -> str:
    if layer.is_part:
        return "a part"
    labels = {"ImageMobject": "an image", "SVGMobject": "an SVG drawing", "Code": "a code layer"}
    if layer.spec.type in labels:
        return labels[layer.spec.type]
    if layer.locked:
        return f"a {layer.spec.type.lower()} on axes"
    return f"a {layer.spec.type}"


def preset_from_layer(layer: Layer, name: str, category: Category) -> Preset:
    """A preset repeating ``layer``'s clips (no morphs or paths) and keys, from the earliest one;
    keys become relative to the first key of their track (ADR 0039)."""
    clips = [c for c in layer.clips if c.info.category not in ("morph", "motion")]
    times = [c.start for c in clips] + [k.t for track in layer.tracks.values() for k in track]
    if not times:
        raise EditError("the layer has no clips or keys to save")
    origin = min(times)
    keys: dict[str, list[PresetKey]] = {}
    for prop, track in layer.tracks.items():
        if not track:
            continue
        first = track[0].value
        keys[prop] = [
            PresetKey(dt=k.t - origin, value=_relative(prop, k.value, first), ease=k.ease) for k in track
        ]
    return Preset(
        name=name,
        category=category,
        clips=[
            PresetClip(
                kinds=[c.kind], offset=c.start - origin, duration=c.duration, ease=c.ease, params=c.params
            )
            for c in clips
        ],
        keys=keys,
    )


def _relative(prop: str, value: float | Vec2, first: float | Vec2) -> float | Vec2:
    if prop == "position":
        return (value[0] - first[0], value[1] - first[1])
    if prop == "scale":
        return value / first if first else 1.0
    if prop == "rotation":
        return value - first
    return value


# -- themes -------------------------------------------------------------------------------------------

_TEXTS = TEXT_TYPES | NUMBER_TYPES | {"AxisLabels", "GraphLabel"}
_LINES = {"Graph"} | CONNECTOR_TYPES | TRACE_TYPES  # drawn in the accent colour
_MARKS = {"Point", "Area", "RiemannRectangles"}  # filled shapes on axes, in the accent
_SHAPES = {"Circle", "Square", "Rectangle", "Triangle", "RightTriangle", "Star", "Dot", "Line", "Arrow"}
_SHAPES |= PYTHON_TYPES  # coloured like a shape; its Style can be reset to the code's colours (ADR 0051)


def themed_style(type_name: str, style: dict[str, Any], theme: Theme) -> dict[str, Any] | None:
    """``style`` recoloured by ``theme`` for an object of ``type_name``; None when the theme leaves
    it alone (images, SVG drawings, code, plugin objects)."""
    if type_name in _TEXTS:
        return {**style, "fill": theme.text}
    if type_name in _LINES:
        return {**style, "stroke": theme.accent}
    if type_name in _MARKS:
        return {**style, "fill": theme.accent, "stroke": theme.accent}
    if type_name == "Axes":
        return {**style, "stroke": theme.text}
    if type_name in _SHAPES:
        return {**style, "fill": theme.shape, "stroke": theme.shape}
    return None


def apply_theme(project: Project, theme: Theme, layer_ids: set[str] | None = None) -> Edit:
    """``theme`` on the objects ``layer_ids`` (with what is under them), or on every layer and the
    background when None; one edit (ADR 0039)."""
    targets = None
    if layer_ids is not None:
        targets = set()
        for layer_id in layer_ids:
            root = project.root_of(layer_id)
            targets |= {root.id} | {d.id for d in project.descendants(root.id)}
    layers = []
    for layer in project.layers:
        style = None
        if layer.spec is not None and (targets is None or layer.id in targets):
            style = themed_style(layer.spec.type, layer.spec.style, theme)
        if style is not None and style != layer.spec.style:
            layer = layer.model_copy(update={"spec": layer.spec.model_copy(update={"style": style})})
        layers.append(layer)
    canvas = project.canvas
    if layer_ids is None:
        canvas = canvas.model_copy(update={"background": theme.background})
    result = edits._rebuilt(project, layers=layers, canvas=canvas)
    kind, changed = edits.classify(project, result)
    return Edit(result, kind, changed)


# -- templates (P5e.2) ----------------------------------------------------------------------------------


def _shifted(layers: list[Layer], dt: float) -> list[Layer]:
    """``layers`` with every time (clip starts, keys, explicit lifetimes) moved by ``dt``."""
    out = []
    for layer in layers:
        data = layer.model_dump(by_alias=True)
        for clip in data["clips"]:
            clip["start"] = round(clip["start"] + dt, 9)
        for track in data["tracks"].values():
            for key in track:
                key["t"] = round(key["t"] + dt, 9)
        for end in ("in", "out"):
            if data["lifetime"][end] is not None:
                data["lifetime"][end] = round(data["lifetime"][end] + dt, 9)
        out.append(Layer.model_validate(data))
    return out


def _times(layers: list[Layer]) -> list[float]:
    times = [t for x in layers for c in x.clips for t in (c.start, c.end)]
    times += [k.t for x in layers for track in x.tracks.values() for k in track]
    times += [t for x in layers for t in (x.lifetime.in_, x.lifetime.out) if t is not None]
    return times


def template_from(project: Project, root_id: str, name: str) -> Template:
    """The object ``root_id`` with everything under it as a template, its times from 0; refused
    when it refers to a layer outside it (a template must stand on its own)."""
    from . import clipboard  # (imports edits, like this module)

    root = project.root_of(root_id)
    payload = clipboard.copy_layers(project, [root.id]).payload
    if payload.outside:
        names = ", ".join(sorted(payload.outside))
        raise EditError(
            f"{root.name or root.id} refers to layers outside it ({names}): it cannot be a template"
        )
    start = min([t for t in _times(payload.layers) if t >= 0], default=0.0)
    return Template(name=name, layers=_shifted(payload.layers, -start))


def insert_template(project: Project, template: Template, t: float, above: str | None = None):
    """``template``'s layers with their times from ``t`` and fresh ids, through the clipboard
    (ADR 0038): a ``clipboard.Pasted`` (the edit, the first layer to select, notes)."""
    from . import clipboard

    fps = project.canvas.fps
    t = max(0.0, round(t * fps) / fps)
    layers = _shifted(template.layers, t)
    end = max(_times(layers), default=t)
    if end > project.canvas.duration + 1e-9:
        raise EditError(
            f"{template.name} needs until {end:g} s; the scene ends at {project.canvas.duration:g} s"
        )
    try:
        return clipboard.paste_layers(project, clipboard.LayersPayload(layers=layers), above=above)
    except clipboard.ClipboardError as exc:
        raise EditError(str(exc)) from None
