"""Adapter registry (ADR 0003, 0007): Manim mapping matches the schema's kind table."""

from __future__ import annotations

import manim as m
import pytest

from manim_studio.core import adapter
from manim_studio.core.schema import CLIP_KIND_INFO, Easing, Spec


def test_every_kind_has_a_manim_class_and_vice_versa() -> None:
    assert set(adapter.ANIMATION_CLASSES) == set(CLIP_KIND_INFO)
    for cls in adapter.ANIMATION_CLASSES.values():
        assert issubclass(cls, m.Animation)


@pytest.mark.parametrize("type_name", sorted(set(adapter.MOBJECT_TYPES) - {"ImageMobject", "MathTex", "Tex"}))
def test_every_vector_type_builds_centred(type_name: str) -> None:
    params = {"text": "Ab"} if type_name == "Text" else {}
    mob = adapter.build_mobject(Spec(type=type_name, params=params))
    assert abs(mob.get_center()).max() < 1e-6


@pytest.mark.latex
@pytest.mark.parametrize("type_name", ["MathTex", "Tex"])
def test_tex_types_build(type_name: str) -> None:
    mob = adapter.build_mobject(
        Spec(type=type_name, params={"text": r"x^2" if type_name == "MathTex" else "Hi"})
    )
    assert len(mob.family_members_with_points()) > 0


def test_an_unknown_type_draws_a_placeholder_and_says_why() -> None:
    """A type no installed plugin provides must not break a frame (ADR 0032)."""
    spec = Spec(type="Teapot")
    assert isinstance(adapter.build_mobject(spec), m.DashedVMobject)
    assert adapter.build_problem(spec) == "no installed plugin provides Teapot"


def test_build_returns_independent_copies() -> None:
    spec = Spec(type="Square", style={"fill": "#ff0000", "fill_opacity": 1})
    a = adapter.build_mobject(spec)
    a.shift([3, 0, 0])
    a.set_fill(opacity=0.1)
    b = adapter.build_mobject(spec)
    assert abs(b.get_center()).max() < 1e-6
    assert b.get_fill_opacity() == pytest.approx(1.0)


def test_style_is_applied() -> None:
    mob = adapter.build_mobject(Spec(type="Circle", style={"stroke": "#00ff00", "stroke_width": 9}))
    assert mob.get_stroke_width() == 9
    assert mob.get_stroke_color().to_hex().lower() == "#00ff00"


def test_unknown_rate_function_raises() -> None:
    with pytest.raises(ValueError, match="unknown rate function"):
        adapter.rate_func(Easing(name="wobble"))


@pytest.mark.parametrize("kind", [k for k, v in CLIP_KIND_INFO.items() if v.clamps_alpha])
def test_content_and_emphasis_clips_clamp_overshoot(kind: str) -> None:
    """ADR 0007: an overshooting curve must not push Create/Write/... past their end."""
    overshoot = Easing(bezier=(0.3, 1.8, 0.6, -0.8))
    path = adapter.build_mobject(Spec(type="Circle")) if CLIP_KIND_INFO[kind].category == "motion" else None
    anim = adapter.make_animation(kind, adapter.build_mobject(Spec(type="Square")), overshoot, {}, path)
    samples = [anim.rate_func(i / 100) for i in range(101)]
    assert min(samples) >= 0.0
    assert max(samples) <= 1.0


def test_morph_clips_may_overshoot() -> None:
    overshoot = Easing(bezier=(0.3, 1.8, 0.6, 1.0))
    anim = adapter.make_animation(
        "Transform",
        adapter.build_mobject(Spec(type="Square")),
        overshoot,
        {},
        adapter.build_mobject(Spec(type="Circle")),
    )
    assert max(anim.rate_func(i / 100) for i in range(101)) > 1.0


def test_wiggle_pivot_is_pinned_to_start_centre() -> None:
    """docs/deviations.md: Wiggle pivots around the clip's starting centre."""
    mob = adapter.build_mobject(Spec(type="Text", params={"text": "Hi"}))
    mob.shift([1, 2, 0])
    anim = adapter.make_animation("Wiggle", mob, None, {})
    assert list(anim.scale_about_point) == pytest.approx([1, 2, 0], abs=1e-6)
    assert list(anim.rotate_about_point) == pytest.approx([1, 2, 0], abs=1e-6)


@pytest.mark.latex
def test_a_truncated_cached_latex_render_is_compiled_again() -> None:
    """A process killed while writing <hash>.svg must not poison that formula (ADR 0007 patch)."""
    import uuid

    from manim.mobject.text import tex_mobject
    from manim.utils import tex_file_writing

    assert tex_mobject.tex_to_svg_file is tex_file_writing.tex_to_svg_file  # MathTex uses the patch
    expression = rf"\sqrt{{{uuid.uuid4().int % 10**9}}}"
    svg = tex_file_writing.tex_to_svg_file(expression, "align*")
    data = svg.read_bytes()
    svg.write_bytes(data[: len(data) // 2])  # what a kill during dvisvgm leaves behind
    again = tex_file_writing.tex_to_svg_file(expression, "align*")
    assert again == svg
    rebuilt = svg.read_bytes()  # compiled again (dvisvgm output is not byte-stable across runs)
    assert rebuilt.rstrip().endswith(b"</svg>") and len(rebuilt) > len(data) * 0.9
