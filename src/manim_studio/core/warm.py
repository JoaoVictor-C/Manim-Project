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

from .. import plugins
from .parts import build_spec
from .schema import TEXT_TYPES, Project, Spec

LABELS = {"AxisLabels": ("x_label", "y_label"), "GraphLabel": ("label",)}  # TeX on axes (ADR 0030)

CACHE_NEUTRAL_PARAMS = frozenset({"font_size", "color"})  # B19: same cache entry


def warm_key(spec: Spec) -> str | None:
    """The disk-cache identity of a text-bearing spec, or None if it builds fast."""
    numbered_axes = spec.type == "Axes" and spec.params.get("numbers") == "yes"  # LaTeX digits (B37)
    plugin = plugins.TYPES.get(spec.type)
    if plugin is not None and plugin.slow:  # unmeasured: every param is part of the key (ADR 0032)
        return json.dumps({"type": spec.type, "params": spec.params}, sort_keys=True)
    if spec.type not in TEXT_TYPES and not numbered_axes:
        return None
    params = {k: v for k, v in spec.params.items() if k not in CACHE_NEUTRAL_PARAMS}
    return json.dumps({"type": spec.type, "params": params}, sort_keys=True)


def warm_keys(spec: Spec) -> set[str]:
    """Every disk-cache entry building ``spec`` reads: its own, or its labels' TeX (ADR 0030)."""
    if spec.type in LABELS:
        texts = (str(spec.params.get(name) or "") for name in LABELS[spec.type])
        return {warm_key(Spec(type="MathTex", params={"text": t})) for t in texts if t.strip()}
    key = warm_key(spec)
    return {key} if key is not None else set()


def key_spec(key: str) -> Spec:
    """A spec that builds exactly the cache entry ``key`` stands for (what the worker builds)."""
    return Spec.model_validate_json(key)


def needs_warm(old: Project, new: Project, warmed: set[str] | frozenset[str]) -> set[str]:
    """Keys of text objects that ``new`` adds or changes and that are not yet warm.

    Objects are compared by what they are built from: a root's spec plus its
    parts' marker spans (ADR 0012), so adding a part warms the new build.
    """
    old_specs = {root.id: build_spec(old, root.id) for root in old.roots()}
    old_specs |= {x.id: x.spec for x in old.layers if x.is_child and not x.is_part}
    built = [(root.id, build_spec(new, root.id)) for root in new.roots()]
    built += [(x.id, x.spec) for x in new.layers if x.is_child and not x.is_part]  # labels on axes
    keys = set()
    for layer_id, spec in built:
        if old_specs.get(layer_id) == spec:
            continue
        keys |= {key for key in warm_keys(spec) if key not in warmed}
    return keys
