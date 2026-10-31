"""Copy, cut, paste and duplicate (P5d, ADR 0038).

What is copied becomes a ``ClipboardData``: a small versioned JSON document the editor
puts on the system clipboard. Pasting it is an ordinary edit (``core.edits``), so it
is one undo step and every cache follows (a pasted layer is kind ``clip``, like
``edits.add_layer``; a sound or a subtitle kind ``timing``).

Layers are copied with their whole subtree (parts, objects on axes). On paste they
get fresh ids; references between copied layers are remapped, references to other
layers are kept when the destination has a layer with that id and the same type
(recorded when copying), and otherwise what needs them is left out and reported:

=================  ===========================  ===================================
reference          inside the copy              outside and missing (or taken)
=================  ===========================  ===================================
``parent_id``      remapped                     the paste is refused
morph ``to_layer`` remapped                     the clip is left out
motion ``path``    remapped                     the clip is left out
``pin`` target     remapped                     the label is unpinned (ADR 0075)
graph / trace /    remapped                     the layer is not pasted
connector targets
=================  ===========================  ===================================

An object copied out of a group (ADR 0050) is pasted into that group when it is in the
destination, otherwise on its own.

A copy keeps the original's visible span: a morph target copied without its source
gets an explicit lifetime start, a copy losing its morph an explicit end.

Pure: no Qt, no Manim.
"""

from __future__ import annotations

import json
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, model_validator

from ..model.schema import (
    CONNECTOR_TYPES,
    GRAPH_PARAMS,
    GROUP_TYPE,
    TRACE_TYPES,
    AudioClip,
    Clip,
    Cue,
    Layer,
    Project,
)
from . import edits
from .edits import Edit

MIME_TYPE = "application/x-manim-studio+json"
FORMAT = "manim-studio-clipboard"
VERSION = 1
NOTHING = "The clipboard has nothing Manim Studio can paste"
ClipboardKind = Literal["layers", "clip", "audio", "cue"]


class ClipboardError(ValueError):
    """Why something cannot be copied or pasted, in words for the status bar."""


# -- the clipboard document -------------------------------------------------------------------


class LayersPayload(BaseModel):
    layers: list[Layer]  # each copied object followed by its subtree, in project order
    outside: dict[str, str] = Field(default_factory=dict)  # referenced, not copied: id -> type


class ClipPayload(BaseModel):
    clip: Clip


class AudioPayload(BaseModel):
    sound: AudioClip


class CuePayload(BaseModel):
    cue: Cue


_PAYLOADS: dict[str, type[BaseModel]] = {
    "layers": LayersPayload,
    "clip": ClipPayload,
    "audio": AudioPayload,
    "cue": CuePayload,
}


class ClipboardData(BaseModel):
    format: Literal["manim-studio-clipboard"] = FORMAT
    version: int = VERSION
    kind: ClipboardKind
    payload: LayersPayload | ClipPayload | AudioPayload | CuePayload

    @model_validator(mode="before")
    @classmethod
    def _payload_of_its_kind(cls, data: Any) -> Any:
        if isinstance(data, dict) and isinstance(data.get("payload"), dict) and data.get("kind") in _PAYLOADS:
            data = {**data, "payload": _PAYLOADS[data["kind"]].model_validate(data["payload"])}
        return data

    @model_validator(mode="after")
    def _kind_matches(self) -> ClipboardData:
        if not isinstance(self.payload, _PAYLOADS[self.kind]):
            raise ValueError(f"the payload is not a {self.kind} payload")
        return self


def to_json(data: ClipboardData) -> str:
    return data.model_dump_json(by_alias=True)


def from_json(text: str) -> ClipboardData:
    """The clipboard document in ``text`` (validated), or ``ClipboardError``."""
    try:
        raw = json.loads(text)
    except (TypeError, ValueError):
        raise ClipboardError(NOTHING) from None
    if not isinstance(raw, dict) or raw.get("format") != FORMAT:
        raise ClipboardError(NOTHING)
    if raw.get("version") != VERSION:
        raise ClipboardError("The clipboard was copied by a newer Manim Studio")
    try:
        return ClipboardData.model_validate(raw)
    except ValidationError:
        raise ClipboardError(NOTHING) from None


@dataclass(frozen=True)
class Pasted:
    """A paste: the edit, the id of what to select (a layer, clip, sound or subtitle) and
    what was left out, for the status bar."""

    edit: Edit
    selected: str
    notes: tuple[str, ...] = ()


# -- copying -----------------------------------------------------------------------------------


def copy_layers(project: Project, layer_ids: Iterable[str]) -> ClipboardData:
    """The layers with their subtrees. Parts cannot be copied: they are a span of their
    equation's TeX (ADR 0012)."""
    picked = list(layer_ids)
    for layer_id in picked:
        layer = _layer(project, layer_id)
        if layer.is_part:
            raise ClipboardError(f"{_label(layer)} is a part of its equation: copy the equation instead")
    if not picked:
        raise ClipboardError("Select a layer to copy")
    family = set(picked)
    for layer_id in picked:
        family |= {d.id for d in project.descendants(layer_id)}
    layers = [layer for layer in project.layers if layer.id in family]
    sources = project.morph_sources()
    copied = []
    for layer in layers:
        morph_in = sources.get(layer.id)
        if morph_in is not None and layer.lifetime.in_ is None and not _clip_in(layers, morph_in):
            # It appears when the morph into it ends (ADR 0005): keep that without the morph.
            lifetime = layer.lifetime.model_copy(update={"in_": morph_in.end})
            layer = layer.model_copy(update={"lifetime": lifetime})
        copied.append(layer)
    by_id = {layer.id: layer for layer in project.layers}
    outside = {
        ref: _type_of(by_id[ref])
        for layer in layers
        for ref in _references(layer)
        if ref not in family and ref in by_id
    }
    return ClipboardData(kind="layers", payload=LayersPayload(layers=copied, outside=outside))


def copy_clip(project: Project, layer_id: str, clip_id: str) -> ClipboardData:
    layer = _layer(project, layer_id)
    clip = next((c for c in layer.clips if c.id == clip_id), None)
    if clip is None:
        raise ClipboardError(f"{_label(layer)} has no clip {clip_id!r}")
    return ClipboardData(kind="clip", payload=ClipPayload(clip=clip))


def copy_audio(project: Project, audio_id: str) -> ClipboardData:
    sound = next((c for c in project.audio if c.id == audio_id), None)
    if sound is None:
        raise ClipboardError(f"There is no sound {audio_id!r}")
    return ClipboardData(kind="audio", payload=AudioPayload(sound=sound))


def copy_cue(project: Project, cue_id: str) -> ClipboardData:
    cue = next((c for c in project.subtitles if c.id == cue_id), None)
    if cue is None:
        raise ClipboardError(f"There is no subtitle {cue_id!r}")
    return ClipboardData(kind="cue", payload=CuePayload(cue=cue))


# -- pasting layers ------------------------------------------------------------------------------


def paste_layers(project: Project, payload: LayersPayload, above: str | None = None) -> Pasted:
    """Insert copies of the payload's layers right above ``above``'s object (on top when
    ``above`` is None or missing); the first copied object is selected."""
    copied = {layer.id: layer for layer in payload.layers}
    present = {layer.id: layer for layer in project.layers}

    def kept_outside(ref: str) -> bool:  # the same layer, as far as we can tell
        return ref in present and ref in payload.outside and _type_of(present[ref]) == payload.outside[ref]

    notes: list[str] = []
    skipped: set[str] = set()
    for layer in payload.layers:  # what is left out has no children: traces, connectors, areas...
        missing = [ref for ref in _drawn_from(layer) if ref not in copied and not kept_outside(ref)]
        if missing:
            skipped.add(layer.id)
            notes.append(f"{_label(layer)} was not pasted: {_what_it_needs(layer)} is not in this project")
    tops = [layer for layer in payload.layers if layer.parent_id not in copied]
    if not tops or all(top.id in skipped for top in tops):
        raise ClipboardError(notes[0] if notes else NOTHING)
    for top in tops:
        if payload.outside.get(top.parent_id or "") == GROUP_TYPE:
            continue  # in its group if it is here, else on its own (ADR 0050)
        if top.parent_id is not None and not kept_outside(top.parent_id):
            owner = payload.outside.get(top.parent_id, "")
            where = "its axes are" if owner == "Axes" else "the object it belongs to is"
            raise ClipboardError(f"{_label(top)} was not pasted: {where} not in this project")

    taken = {layer.id for layer in project.layers} | {c.id for c in project.audio}
    taken |= {c.id for c in project.subtitles}
    mapping: dict[str, str] = {}
    for layer in payload.layers:
        if layer.id not in skipped:
            mapping[layer.id] = edits._free_id(_type_of(layer), taken)
            taken.add(mapping[layer.id])

    def resolve(ref: str) -> str | None:  # the copy's id, the same outside layer, or None
        if ref in mapping:
            return mapping[ref]
        return ref if kept_outside(ref) else None  # (a left-out copied layer is never "outside")

    targeted = set(project.morph_sources())
    names = {layer.name for layer in project.layers}
    new_layers: list[Layer] = []
    for layer in payload.layers:
        if layer.id in skipped:
            continue
        data = layer.model_dump(by_alias=True)
        data["id"] = mapping[layer.id]
        if layer.parent_id is not None:
            data["parent_id"] = resolve(layer.parent_id)
        params = data["spec"]["params"] if data["spec"] else {}
        for name in _reference_params(layer):
            if params.get(name):
                params[name] = resolve(params[name])
        clips = []
        for clip in data["clips"]:
            if clip["to_layer"]:
                target = resolve(clip["to_layer"])
                if target is None or target in targeted:  # a layer is the target of one morph only
                    notes.append(
                        f"{_label(layer)}: its {clip['kind']} clip was left out (nothing to turn into)"
                    )
                    if data["lifetime"]["out"] is None:
                        data["lifetime"]["out"] = clip["start"] + clip["duration"]  # it still disappears
                    continue
                clip["to_layer"] = target
            if clip["params"].get("path"):
                path = resolve(clip["params"]["path"])
                if path is None:
                    notes.append(
                        f"{_label(layer)}: its {clip['kind']} clip was left out (its path is missing)"
                    )
                    continue
                clip["params"]["path"] = path
            clips.append(clip)
        data["clips"] = clips
        if layer.pin is not None:  # onto the copied target, the same one, or unpinned (ADR 0075)
            target = resolve(layer.pin.target)
            if target is None:
                notes.append(
                    f"{_label(layer)} was unpinned: the layer it was pinned to is not in this project"
                )
                data["pin"] = None
            else:
                data["pin"]["target"] = target
        if layer.parent_id not in copied and layer.name:
            data["name"] = _free_name(layer.name, names)
            names.add(data["name"])
        new_layers.append(Layer.model_validate(data))

    layers = list(project.layers)
    roots = [layer for layer in new_layers if layer.parent_id is None]
    roots = [x for root in roots for x in _family(root, new_layers)]
    anchor = present.get(above) if above else None
    at = len(layers) if anchor is None else _block_end(project, project.root_of(anchor.id).id)
    layers[at:at] = roots
    for top in new_layers:
        if top.parent_id is not None and top.parent_id in present:  # onto its axes, after their objects
            at = _block_end_in(layers, top.parent_id)
            layers[at:at] = _family(top, new_layers)
    try:
        edit = edits._replace_layers(project, layers)
    except ValidationError as error:
        raise ClipboardError(f"Cannot paste here: {_reason(error)}") from None
    first = next(top for top in tops if top.id not in skipped)
    return Pasted(edit, mapping[first.id], tuple(notes))


def duplicate_layers(project: Project, layer_ids: Iterable[str]) -> Pasted:
    """Copies right above the (last) original, without the system clipboard."""
    layer_ids = list(layer_ids)
    data = copy_layers(project, layer_ids)
    return paste_layers(project, data.payload, above=layer_ids[-1])


# -- pasting clips, sounds and subtitles ---------------------------------------------------------


def paste_clip(
    project: Project,
    payload: ClipPayload,
    layer_id: str,
    start: float,
    allowed: Collection[str] | None = None,
) -> Pasted:
    """The clip on ``layer_id`` from ``start`` with its own length; ``allowed`` is the layer's
    allow-list (``adapter.allowed_clip_kinds``, ADR 0007), when the caller has it."""
    try:
        layer = project.layer(layer_id)
    except KeyError:
        raise ClipboardError(f"There is no layer {layer_id!r} to paste on") from None
    clip = payload.clip
    if allowed is not None and clip.kind not in allowed:
        raise ClipboardError(f"A {clip.kind} clip cannot go on {_label(layer)}")
    ids = {x.id for x in project.layers}
    if clip.to_layer and clip.to_layer not in ids:
        raise ClipboardError(
            f"Cannot paste the {clip.kind} clip: the layer it turns into is not in this project"
        )
    path = clip.params.get("path")
    if path and path not in ids:
        raise ClipboardError(f"Cannot paste the {clip.kind} clip: its path is not in this project")
    if start + clip.duration > project.canvas.duration + 1e-9:
        raise ClipboardError(f"No room for the {clip.kind} clip there: it would run past the end")
    clip_id = edits.new_clip_id(layer, clip.kind)
    try:
        edit = edits.add_clip(
            project,
            layer_id,
            clip.kind,
            start,
            clip.duration,
            to_layer=clip.to_layer,
            ease=clip.ease,
            clip_id=clip_id,
            params=clip.params,
        )
    except ValidationError as error:
        reason = _reason(error)
        if "overlap" in reason or "comes after" in reason:
            raise ClipboardError(f"No room for the {clip.kind} clip there") from None
        raise ClipboardError(f"Cannot paste the {clip.kind} clip there: {reason}") from None
    return Pasted(edit, clip_id)


def duplicate_clip(
    project: Project, layer_id: str, clip_id: str, allowed: Collection[str] | None = None
) -> Pasted:
    """A copy of the clip right after it, on the same layer."""
    data = copy_clip(project, layer_id, clip_id)
    return paste_clip(project, data.payload, layer_id, data.payload.clip.end, allowed)


def paste_audio(project: Project, payload: AudioPayload, start: float) -> Pasted:
    """The sound from ``start`` with its trim, gain and fades (sounds may overlap: they mix)."""
    sound = payload.sound
    added = edits.add_audio(project, sound.path, max(0.0, start), sound.duration, name=sound.name)
    new_id = added.project.audio[-1].id
    edit = edits.update_audio(
        added.project,
        new_id,
        offset=sound.offset,
        gain=sound.gain,
        fade_in=sound.fade_in,
        fade_out=sound.fade_out,
    )
    return Pasted(edit, new_id)


def duplicate_audio(project: Project, audio_id: str) -> Pasted:
    data = copy_audio(project, audio_id)
    return paste_audio(project, data.payload, data.payload.sound.end)


def paste_cue(project: Project, payload: CuePayload, start: float) -> Pasted:
    """The subtitle from ``start`` with its length, if it overlaps no other (one lane, ADR 0035)."""
    cue = payload.cue
    end = start + (cue.end - cue.start)
    if any(start < other.end - 1e-9 and other.start < end - 1e-9 for other in project.subtitles):
        raise ClipboardError("No room for the subtitle there: it would overlap another one")
    edit = edits.add_cue(project, start, end, cue.text)
    new_id = next(c.id for c in edit.project.subtitles if c.id not in {x.id for x in project.subtitles})
    return Pasted(edit, new_id)


def duplicate_cue(project: Project, cue_id: str) -> Pasted:
    data = copy_cue(project, cue_id)
    return paste_cue(project, data.payload, data.payload.cue.end)


# -- helpers --------------------------------------------------------------------------------------


def _layer(project: Project, layer_id: str) -> Layer:
    try:
        return project.layer(layer_id)
    except KeyError:
        raise ClipboardError(f"There is no layer {layer_id!r}") from None


def _label(layer: Layer) -> str:
    return layer.name or (layer.spec.type if layer.spec else layer.id)


def _type_of(layer: Layer) -> str:
    """What the layer is, for fresh ids (``<type>-<n>``) and for matching outside references."""
    return layer.spec.type if layer.spec is not None else "part"


def _clip_in(layers: list[Layer], clip: Clip) -> bool:
    return any(c is clip for layer in layers for c in layer.clips)


def _reference_params(layer: Layer) -> list[str]:
    """Spec params naming another layer: a graph (ADR 0030), a trace's or connector's targets."""
    if layer.spec is None:
        return []
    names = [name for name, _required in GRAPH_PARAMS.get(layer.spec.type, ())]
    if layer.spec.type in TRACE_TYPES:
        names.append("target")
    if layer.spec.type in CONNECTOR_TYPES:
        names += ["source", "target"]
    return names


def _drawn_from(layer: Layer) -> list[str]:
    """The layers this layer cannot be drawn without (its spec's references)."""
    params = layer.spec.params if layer.spec is not None else {}
    return [params[name] for name in _reference_params(layer) if params.get(name)]


def _references(layer: Layer) -> list[str]:
    """Every layer id ``layer`` refers to."""
    refs = [layer.parent_id] if layer.parent_id else []
    refs += _drawn_from(layer)
    if layer.pin is not None:  # ADR 0075
        refs.append(layer.pin.target)
    for clip in layer.clips:
        refs += [ref for ref in (clip.to_layer, clip.params.get("path")) if ref]
    return refs


def _what_it_needs(layer: Layer) -> str:
    if layer.spec is not None and layer.spec.type in TRACE_TYPES:
        return "the layer it follows"
    if layer.spec is not None and layer.spec.type in CONNECTOR_TYPES:
        return "a layer it joins"
    return "its graph"


def _free_name(name: str, names: set[str]) -> str:
    if name not in names:
        return name
    candidate, n = f"{name} copy", 2
    while candidate in names:
        candidate, n = f"{name} copy {n}", n + 1
    return candidate


def _family(top: Layer, layers: list[Layer]) -> list[Layer]:
    """``top`` and its descendants among ``layers``, in list order."""
    ids = {top.id}
    out = []
    for layer in layers:
        if layer.id in ids or layer.parent_id in ids:
            ids.add(layer.id)
            out.append(layer)
    return out


def _block_end(project: Project, root_id: str) -> int:
    """The index after ``root_id`` and its descendants in ``project.layers``."""
    family = {root_id} | {d.id for d in project.descendants(root_id)}
    return max(i for i, layer in enumerate(project.layers) if layer.id in family) + 1


def _block_end_in(layers: list[Layer], root_id: str) -> int:
    """The index after ``root_id`` and everything under it in a plain list of layers."""
    parents = {layer.id: layer.parent_id for layer in layers}

    def inside(layer_id: str | None) -> bool:
        while layer_id is not None:
            if layer_id == root_id:
                return True
            layer_id = parents.get(layer_id)
        return False

    return max(i for i, layer in enumerate(layers) if inside(layer.id)) + 1


def _reason(error: ValidationError) -> str:
    """The first validation message, without pydantic's prefix."""
    message = str(error.errors()[0].get("msg", error))
    return message.removeprefix("Value error, ")
