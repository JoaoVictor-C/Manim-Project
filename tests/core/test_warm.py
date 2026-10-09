"""Warm keys and the warm gate (ADR 0015) — pure, no worker."""

from __future__ import annotations

from manim_studio.core import edits
from manim_studio.core.schema import Layer, Project, Spec
from manim_studio.core.warm import key_spec, needs_warm, warm_key
from support import CANVAS

MATH = Spec(type="MathTex", params={"text": "x^2"})


def project(*specs: Spec) -> Project:
    return Project(canvas=CANVAS, layers=[Layer(id=f"l{i}", spec=s) for i, s in enumerate(specs)])


def test_only_text_types_have_keys() -> None:
    assert warm_key(Spec(type="Circle", params={"radius": 2})) is None
    assert warm_key(Spec(type="ImageMobject", params={"path": "a.png"})) is None
    assert warm_key(MATH) is not None


def test_measured_cache_neutral_params_and_style_do_not_change_the_key() -> None:
    """B19: font_size, color and style reuse the disk-cache entry."""
    key = warm_key(MATH)
    assert warm_key(MATH.model_copy(update={"params": {"text": "x^2", "font_size": 72}})) == key
    assert warm_key(MATH.model_copy(update={"params": {"text": "x^2", "color": "#ff0000"}})) == key
    assert warm_key(MATH.model_copy(update={"style": {"fill": "#00ff00"}})) == key


def test_text_font_and_unmeasured_params_change_the_key() -> None:
    text = Spec(type="Text", params={"text": "Hi"})
    assert warm_key(text.model_copy(update={"params": {"text": "Hi", "font": "Consolas"}})) != warm_key(text)
    assert warm_key(text.model_copy(update={"params": {"text": "Hi", "weight": "BOLD"}})) != warm_key(text)
    assert warm_key(Spec(type="Tex", params={"text": "x^2"})) != warm_key(MATH)


def test_key_is_canonical_and_round_trips_to_a_spec() -> None:
    a = Spec(type="Text", params={"text": "Hi", "font": "Arial"})
    b = Spec(type="Text", params={"font": "Arial", "text": "Hi"})
    assert warm_key(a) == warm_key(b)
    assert key_spec(warm_key(a)) == a


def test_needs_warm_reports_added_and_changed_text_only() -> None:
    old = project(Spec(type="Square"), MATH)
    assert needs_warm(old, old, set()) == set()
    added = edits.add_layer(old, Spec(type="Text", params={"text": "new"})).project
    assert needs_warm(old, added, set()) == {warm_key(added.layers[-1].spec)}
    changed = edits.update_layer(old, "l1", spec=Spec(type="MathTex", params={"text": "y"})).project
    assert needs_warm(old, changed, set()) == {warm_key(changed.layer("l1").spec)}
    assert needs_warm(old, edits.add_layer(old, Spec(type="Circle")).project, set()) == set()


def test_needs_warm_skips_warm_keys_and_cache_neutral_changes() -> None:
    old = project(MATH)
    resized = edits.update_layer(
        old, "l0", spec=Spec(type="MathTex", params={"text": "x^2", "font_size": 96})
    )
    assert needs_warm(old, resized.project, set()) == {warm_key(MATH)}  # changed spec, same entry
    assert needs_warm(old, resized.project, {warm_key(MATH)}) == set()
