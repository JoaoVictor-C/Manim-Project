"""Editable animation recipes (ADR 0080): a sequence's animation, reused on other layers.

A ``library.Recipe`` is made from a sequence (ADR 0079): each layer of the sequence becomes a *role*
(``RecipeSlot``) holding that layer's clips and keys from its own start, ``offset`` s after the
sequence's start. It is saved with the user's presets and applied to other layers as a **new sequence**
named after it (``Sequence.recipe`` names it too), so it can then be moved, retimed, duplicated or
dissolved like any sequence - and keeps its parameters:

* ``length`` - how long the whole lasts: each layer's part is stretched by one factor, the delays kept;
* ``stagger`` - the delay between consecutive layers' starts (None: the roles' own offsets);
* the order of the target layers - the first layer takes the first role, and so on.

A one-role recipe repeats over any number of layers; a recipe of several roles needs exactly that many.
``reparameterise_sequence`` (in ``sequences``) changes length and stagger afterwards.

No Qt; Manim only through ``library.apply_preset`` (the clip allow-list).
"""

from __future__ import annotations

import math

from ..model.scene_length import grow_to_fit
from ..model.schema import Project
from . import edits, library, sequences
from .edits import Edit, EditError
from .library import PresetClip, PresetKey, Recipe, RecipeSlot

EPS = 1e-9


def make_recipe(project: Project, sequence_id: str, name: str, description: str = "") -> Recipe:
    """A recipe of the sequence's clips and keys, one role per layer in the order they start. Refused
    when a clip needs another layer (a morph, a move along a path)."""
    from ..engine.evaluator import layer_transform  # how tracks are sampled lives with the evaluator

    seq = sequences.sequence(project, sequence_id)
    name = str(name).strip()
    if not name:
        raise EditError("a recipe needs a name")
    start, end = sequences.span(project, seq)
    slots: list[RecipeSlot] = []
    for layer_id in sequences.member_layers(project, seq):
        layer = edits._layer(project, layer_id)
        origin, _ = sequences.layer_span(project, seq, layer_id)
        ids = {ref.clip for ref in seq.clips if ref.layer == layer_id}
        clips = []
        for clip in layer.clips:
            if clip.id not in ids:
                continue
            if clip.info.category in ("morph", "motion"):
                raise EditError(f"{clip.kind} on {layer.label} needs another layer: a recipe cannot hold it")
            clips.append(
                PresetClip(
                    kinds=[clip.kind],
                    offset=clip.start - origin,
                    duration=clip.duration,
                    ease=clip.ease,
                    params=clip.params,
                )
            )
        now = layer_transform(layer, origin)
        half = 0.5 / project.canvas.fps
        keys: dict[str, list[PresetKey]] = {}
        for ref in sorted((r for r in seq.keys if r.layer == layer_id), key=lambda r: r.t):
            key = next(k for k in layer.tracks[ref.track] if abs(k.t - ref.t) < half)
            value = library._relative(ref.track, key.value, getattr(now, ref.track))
            keys.setdefault(ref.track, []).append(PresetKey(dt=key.t - origin, value=value, ease=key.ease))
        slots.append(RecipeSlot(offset=origin - start, clips=clips, keys=keys))
    stagger = sequences.stagger_of(project, seq) if len(slots) > 1 else None
    roles = f"{len(slots)} layer{'s' if len(slots) > 1 else ''}"
    return Recipe(
        name=name,
        description=description or f"From {seq.name}: {roles}, {end - start:g} s",
        slots=slots,
        stagger=stagger,
    )


def apply_recipe(
    project: Project,
    recipe: Recipe,
    layer_ids: list[str],
    at: float,
    length: float | None = None,
    stagger: float | None = None,
) -> Edit:
    """``recipe`` on ``layer_ids`` (in role order) from ``at`` (on the frame grid), as a new sequence named
    after it: one ``Edit``, whole or not at all. ``length`` and ``stagger`` default to the recipe's own;
    the scene grows to hold it when it grows with its content. ``EditError`` says why it cannot."""
    layer_ids = list(layer_ids)
    if not layer_ids:
        raise EditError("select the layers to animate")
    if len(set(layer_ids)) != len(layer_ids):
        raise EditError("a layer is chosen twice")
    count = len(recipe.slots)
    if count == 1:
        slots = recipe.slots * len(layer_ids)
    elif len(layer_ids) != count:
        raise EditError(
            f"{recipe.name} animates {count} layers: select {count} (in the order of its roles), "
            f"not {len(layer_ids)}"
        )
    else:
        slots = list(recipe.slots)
    if at < 0:
        raise EditError("a recipe cannot start before 0 s")
    for layer_id in layer_ids:
        edits._layer(project, layer_id)
    fps = project.canvas.fps
    at = round(at * fps) / fps
    stagger = recipe.stagger if stagger is None else stagger
    if stagger is not None and stagger < 0:
        raise EditError("the delay between layers cannot be below 0 s")
    if stagger is not None:
        offsets = [i * stagger for i in range(len(slots))]
    else:
        offsets = [s.offset for s in slots] if count > 1 else [0.0] * len(slots)
    length = recipe.length if length is None else length
    try:
        factor = 1.0 if length is None else sequences.fit_factor(offsets, [s.length for s in slots], length)
    except EditError as exc:
        raise EditError(f"{recipe.name}: {exc}") from None

    needed = max(at + o + s.length * factor for o, s in zip(offsets, slots, strict=True))
    canvas = project.canvas
    result = project
    if canvas.grow_with_content and needed > canvas.duration + EPS:  # room first; trimmed back below
        roomy = math.ceil(needed * fps - 1e-6) / fps + 1 / fps
        result = project.model_copy(update={"canvas": canvas.model_copy(update={"duration": roomy})})
    clips: list[tuple[str, str]] = []
    keys: list[tuple[str, str, float]] = []
    for layer_id, slot, offset in zip(layer_ids, slots, offsets, strict=True):
        preset = _scaled(recipe.name, slot, factor, fps)
        t = max(0.0, round((at + offset) * fps) / fps)
        before = {c.id for c in result.layer(layer_id).clips}
        try:
            result = library.apply_preset(result, layer_id, preset, t).project
        except EditError as exc:
            raise EditError(f"{result.layer(layer_id).label}: {exc}") from None
        clips += [(layer_id, c.id) for c in result.layer(layer_id).clips if c.id not in before]
        for prop, track in preset.keys.items():
            keys += [(layer_id, prop, round((t + k.dt) * fps) / fps) for k in track]
    if result.canvas.duration != canvas.duration:
        result = grow_to_fit(result.model_copy(update={"canvas": canvas}))
    members = sequences.Members(tuple(clips), tuple(keys))
    result = sequences.make_sequence(result, recipe.name, members, recipe=recipe.name).project
    return Edit(result, *edits.classify(project, result))


def recipe_parameters(project: Project, sequence_id: str) -> tuple[float, float | None]:
    """A sequence's length and its delay between layers (None when the delays differ)."""
    seq = sequences.sequence(project, sequence_id)
    start, end = sequences.span(project, seq)
    return end - start, sequences.stagger_of(project, seq)


def _scaled(name: str, slot: RecipeSlot, factor: float, fps: float) -> library.Preset:
    """The role as a preset, its times stretched by ``factor``; refused when two keys of one property
    would fall on one frame."""
    keys: dict[str, list[PresetKey]] = {}
    for prop, track in slot.keys.items():
        scaled = [k.model_copy(update={"dt": k.dt * factor}) for k in track]
        frames = [round(k.dt * fps) for k in scaled]
        if len(frames) != len(set(frames)):
            raise EditError(f"{name}: two {prop} keys would fall on one frame at that length; make it longer")
        keys[prop] = scaled
    clips = [
        c.model_copy(update={"offset": c.offset * factor, "duration": c.duration * factor})
        for c in slot.clips
    ]
    return library.Preset(name=name, category="motion", clips=clips, keys=keys)
