"""Document edits (ADR 0013, ADR 0014).

Edits never mutate a ``Project``. Each function returns an ``Edit``: a new,
fully validated snapshot that shares unchanged layers with the old one, plus the
edit *kind* that tells the evaluator which caches to drop:

======== ========================================== ==============================
kind     what changed                               evaluator drops
======== ========================================== ==============================
timing   clip start/duration (lane order unchanged), nothing (morphs re-begin only
         lifetime, name                             if their baked transforms move)
transform base transform or keyframe tracks          nothing (same rule for morphs)
clip     clip kind/params/ease, added/removed/       the layer's clip caches and
         reordered clips                            its morph partners'
spec     the object itself                          as ``clip`` + the built object
======== ========================================== ==============================

The kind is computed by comparing the two snapshots, so callers cannot get it
wrong. This module has no Qt dependency (coding standards rule 1).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .schema import Clip, Layer, Project

EditKind = Literal["timing", "transform", "clip", "spec"]
_SEVERITY: dict[EditKind, int] = {"timing": 0, "transform": 1, "clip": 2, "spec": 3}
_TIMING_FIELDS = {"start", "duration"}


class EditError(ValueError):
    """An edit referred to something that does not exist."""


@dataclass(frozen=True)
class Edit:
    project: Project
    kind: EditKind
    layer_ids: frozenset[str]


# -- edit functions -------------------------------------------------------------


def update_clip(project: Project, layer_id: str, clip_id: str, **fields: Any) -> Edit:
    """Change fields of one clip (validated; raises ``ValidationError`` if invalid)."""
    layer = _layer(project, layer_id)
    if not any(c.id == clip_id for c in layer.clips):
        raise EditError(f"layer {layer_id!r} has no clip {clip_id!r}")
    clips = [
        {**c.model_dump(by_alias=True), **fields} if c.id == clip_id else c.model_dump(by_alias=True)
        for c in layer.clips
    ]
    return _replace_layer(project, layer_id, {"clips": clips})


def move_clip(project: Project, layer_id: str, clip_id: str, start: float) -> Edit:
    return update_clip(project, layer_id, clip_id, start=start)


def trim_clip(
    project: Project, layer_id: str, clip_id: str, start: float | None = None, end: float | None = None
) -> Edit:
    """Move one or both edges of a clip; the other edge stays where it is."""
    clip = _clip(project, layer_id, clip_id)
    new_start = clip.start if start is None else start
    new_end = clip.end if end is None else end
    return update_clip(project, layer_id, clip_id, start=new_start, duration=new_end - new_start)


def update_layer(project: Project, layer_id: str, **fields: Any) -> Edit:
    """Change top-level fields of a layer (``base``, ``tracks``, ``spec``, ``lifetime``, ...)."""
    _layer(project, layer_id)
    return _replace_layer(project, layer_id, fields)


# -- classification -------------------------------------------------------------


def classify(old: Project, new: Project) -> tuple[EditKind, frozenset[str]]:
    """The most severe edit kind between two snapshots, and the layers it touches.

    Morph partners of touched layers are included, so observers (lifetime bands,
    morph caches) refresh both ends.
    """
    old_layers = {layer.id: layer for layer in old.layers}
    new_layers = {layer.id: layer for layer in new.layers}
    kind: EditKind = "timing"
    touched: set[str] = set()
    for layer_id in old_layers.keys() | new_layers.keys():
        a, b = old_layers.get(layer_id), new_layers.get(layer_id)
        layer_kind = "clip" if a is None or b is None else _layer_kind(a, b)
        if layer_kind is None:
            continue
        touched.add(layer_id)
        if _SEVERITY[layer_kind] > _SEVERITY[kind]:
            kind = layer_kind
    return kind, frozenset(touched | _morph_partners(old, touched) | _morph_partners(new, touched))


def _layer_kind(a: Layer, b: Layer) -> EditKind | None:
    if a == b:
        return None
    if a.spec != b.spec:
        return "spec"
    if [c.id for c in a.clips] != [c.id for c in b.clips]:
        return "clip"  # added, removed or reordered: predecessors changed
    timing = False
    for ca, cb in zip(a.clips, b.clips, strict=True):
        if ca == cb:
            continue
        changed = {name for name in Clip.model_fields if getattr(ca, name) != getattr(cb, name)}
        if changed - _TIMING_FIELDS:
            return "clip"
        timing = True
    if a.base != b.base or a.tracks != b.tracks:
        return "transform"
    return "timing" if timing or a.lifetime != b.lifetime or a.name != b.name else None


def _morph_partners(project: Project, layer_ids: set[str]) -> set[str]:
    partners = set()
    for layer in project.layers:
        for clip in layer.clips:
            if clip.to_layer and (layer.id in layer_ids or clip.to_layer in layer_ids):
                partners |= {layer.id, clip.to_layer}
    return partners


# -- helpers --------------------------------------------------------------------


def _layer(project: Project, layer_id: str) -> Layer:
    try:
        return project.layer(layer_id)
    except KeyError:
        raise EditError(f"no layer {layer_id!r}") from None


def _clip(project: Project, layer_id: str, clip_id: str) -> Clip:
    for clip in _layer(project, layer_id).clips:
        if clip.id == clip_id:
            return clip
    raise EditError(f"layer {layer_id!r} has no clip {clip_id!r}")


def _replace_layer(project: Project, layer_id: str, fields: dict[str, Any]) -> Edit:
    old_layer = project.layer(layer_id)
    # Rebuilt from data so the layer's validators run; model_copy(update=) would skip them.
    data = {**old_layer.model_dump(by_alias=True), **_dump(fields)}
    new_layer = Layer.model_validate(data)
    layers = [new_layer if layer.id == layer_id else layer for layer in project.layers]
    # Unchanged layers are reused as-is; the project-level validator still runs.
    new_project = Project.model_validate(
        {"schema_version": project.schema_version, "canvas": project.canvas, "layers": layers}
    )
    kind, layer_ids = classify(project, new_project)
    return Edit(new_project, kind, layer_ids)


def _dump(fields: dict[str, Any]) -> dict[str, Any]:
    return {k: v.model_dump(by_alias=True) if hasattr(v, "model_dump") else v for k, v in fields.items()}
