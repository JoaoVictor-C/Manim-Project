"""Which edits must wait for the build worker (ADR 0015) — pure, no Manim.

Text-bearing objects (Text, Tex, MathTex) are slow to build the first time and
fast afterwards because Manim caches them on disk (B17). The build worker warms
that cache in another process; an edit is committed once every text object it
would build is warm, so the editor's own build is a cache hit.

A *warm key* identifies a disk-cache entry: the spec's type and params minus
the params measured not to change the entry (B19). Unmeasured params are part
of the key, so a new param errs on the side of waiting, never of freezing.

A Python object's new code (ADR 0051) is built first by the worker too - with its parameters'
defaults, so its key is the code alone: an endless loop then stops the worker, which is killed
and restarted, not the editor; the edit is dropped with the reason. Only trusted code is sent.
"""

from __future__ import annotations

import json

from ... import plugins
from ..code import helpers, python_object
from ..model.parts import build_spec
from ..model.schema import GLYPH_COLOURS, NUMBER_TYPES, PYTHON_TYPES, TEXT_TYPES, Project, Spec

LABELS = {"AxisLabels": ("x_label", "y_label"), "GraphLabel": ("label",)}  # TeX on axes (ADR 0030)

# B19: same cache entry. Glyph colours (ADR 0055) are never given to Manim: they colour a copy
# of the built object, so changing them builds nothing new.
CACHE_NEUTRAL_PARAMS = frozenset({"font_size", "color", GLYPH_COLOURS})


def warm_key(spec: Spec, helper_sources: helpers.Sources | None = None) -> str | None:
    """The disk-cache identity of a text-bearing spec, or None if it builds fast.

    A Python object's key carries the project's helpers (ADR 0058) when there are any: their
    sources and the names of those trusted, which the worker serves while it builds."""
    if spec.type in PYTHON_TYPES:  # new code is run in the worker first (ADR 0051)
        code = str(spec.params.get("code", ""))
        if not python_object.is_trusted(code):
            return None  # never run there: the editor shows the placeholder
        key: dict = {"type": spec.type, "params": {"code": code}}
        if helper_sources:
            key["helpers"] = dict(helper_sources)
            key["trusted_helpers"] = sorted(
                n for n, c in helper_sources.items() if python_object.is_trusted(c)
            )
        return json.dumps(key, sort_keys=True)
    if spec.type in NUMBER_TYPES:  # every glyph a count can show (ADR 0036)
        return json.dumps({"type": spec.type, "params": number_glyphs(spec)}, sort_keys=True)
    numbered_axes = spec.type == "Axes" and spec.params.get("numbers") == "yes"  # LaTeX digits (B37)
    plugin = plugins.TYPES.get(spec.type)
    if plugin is not None and plugin.slow:  # unmeasured: every param is part of the key (ADR 0032)
        return json.dumps({"type": spec.type, "params": spec.params}, sort_keys=True)
    if spec.type not in TEXT_TYPES and not numbered_axes:
        return None
    params = {k: v for k, v in spec.params.items() if k not in CACHE_NEUTRAL_PARAMS}
    return json.dumps({"type": spec.type, "params": params}, sort_keys=True)


def number_glyphs(spec: Spec) -> dict:
    """A Number whose text holds every digit, the separators, its sign and its unit: building it
    compiles each glyph (one LaTeX file per character, B49) that the number can change to."""
    sign = spec.params.get("include_sign") == "yes"
    params = {"number": 1234567890.5 if sign else -1234567890.5, "num_decimal_places": 1}
    if sign:
        params["include_sign"] = "yes"
    if spec.params.get("unit"):
        params["unit"] = spec.params["unit"]
    return params


def warm_keys(spec: Spec, helper_sources: helpers.Sources | None = None) -> set[str]:
    """Every disk-cache entry building ``spec`` reads: its own, or its labels' TeX (ADR 0030)."""
    if spec.type in LABELS:
        texts = (str(spec.params.get(name) or "") for name in LABELS[spec.type])
        return {warm_key(Spec(type="MathTex", params={"text": t})) for t in texts if t.strip()}
    key = warm_key(spec, helper_sources)
    return {key} if key is not None else set()


def key_spec(key: str) -> Spec:
    """A spec that builds exactly the cache entry ``key`` stands for (what the worker builds; a
    Python object's helpers ride beside it in the key, ``key_helpers``)."""
    return Spec.model_validate_json(key)


def key_helpers(key: str) -> tuple[dict[str, str], list[str]]:
    """The helper sources and trusted helper names a warm key carries (ADR 0058), or none."""
    data = json.loads(key)
    return dict(data.get("helpers") or {}), list(data.get("trusted_helpers") or [])


def needs_warm(old: Project, new: Project, warmed: set[str] | frozenset[str]) -> set[str]:
    """Keys of text objects that ``new`` adds or changes and that are not yet warm.

    Objects are compared by what they are built from: a root's spec plus its
    parts' marker spans (ADR 0012), so adding a part warms the new build.
    """
    old_specs = {root.id: build_spec(old, root.id) for root in old.roots()}
    old_specs |= {x.id: x.spec for x in old.layers if x.is_child and not x.is_part}
    built = [(root.id, build_spec(new, root.id)) for root in new.roots()]
    built += [(x.id, x.spec) for x in new.layers if x.is_child and not x.is_part]  # labels on axes
    sources = helpers.sources(new)
    rerun = helpers.code_changed(old, new)  # a helper's new code runs in every Python object (ADR 0058)
    keys = set()
    for layer_id, spec in built:
        if old_specs.get(layer_id) == spec and not (rerun and spec.type in PYTHON_TYPES):
            continue
        keys |= {key for key in warm_keys(spec, sources) if key not in warmed}
    return keys
