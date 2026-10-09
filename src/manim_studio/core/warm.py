"""Which edits must wait for the build worker (ADR 0015) — pure, no Manim.

Text-bearing objects (Text, Tex, MathTex) are slow to build the first time and
fast afterwards because Manim caches them on disk (B17). The build worker warms
that cache in another process; an edit is committed once every text object it
would build is warm, so the editor's own build is a cache hit.

A *warm key* identifies a disk-cache entry: the spec's type and params minus
the params measured not to change the entry (B19). Unmeasured params are part
of the key, so a new param errs on the side of waiting, never of freezing.
"""

from __future__ import annotations

import json

from .schema import TEXT_TYPES, Project, Spec

CACHE_NEUTRAL_PARAMS = frozenset({"font_size", "color"})  # B19: same cache entry


def warm_key(spec: Spec) -> str | None:
    """The disk-cache identity of a text-bearing spec, or None if it builds fast."""
    if spec.type not in TEXT_TYPES:
        return None
    params = {k: v for k, v in spec.params.items() if k not in CACHE_NEUTRAL_PARAMS}
    return json.dumps({"type": spec.type, "params": params}, sort_keys=True)


def key_spec(key: str) -> Spec:
    """A spec that builds exactly the cache entry ``key`` stands for (what the worker builds)."""
    return Spec.model_validate_json(key)


def needs_warm(old: Project, new: Project, warmed: set[str] | frozenset[str]) -> set[str]:
    """Keys of text objects that ``new`` adds or changes and that are not yet warm."""
    old_specs = {layer.id: layer.spec for layer in old.layers}
    keys = set()
    for layer in new.layers:
        if old_specs.get(layer.id) == layer.spec:
            continue
        key = warm_key(layer.spec)
        if key is not None and key not in warmed:
            keys.add(key)
    return keys
