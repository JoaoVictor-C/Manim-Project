"""Colouring part of an equation (U5, ADR 0049): a part layer's ``style``.

The contract is Manim's own: a coloured part draws like ``eq[0][3:5].set_color(RED)`` on the plain
equation before anything plays, so a clip that changes colour (Indicate) goes from the part's colour
to its own and back, as it does in a Manim script.
"""

from __future__ import annotations

import manim as m
import pytest
from pydantic import ValidationError
from tests.support import TOLERANCE, max_diff

from manim_studio.core import adapter, edits, frame_cache
from manim_studio.core.evaluator import Evaluator
from manim_studio.core.schema import Canvas, Clip, Layer, PartKey, Project, Spec
from manim_studio.render.cairo_export import make_camera, render_frame

CANVAS = Canvas(width_px=320, height_px=180, fps=15, duration=4.0)
TEXT = r"a^2 + b^2 = c^2"  # the formula of test_part_layers: Manim's cache is warm
PLAIN = Spec(type="MathTex", params={"text": TEXT})
A, B, C = (0, 1), (3, 4), (6, 7)  # glyphs of a^2, b^2, c^2 (B28)
RED, GREEN = "#ff0000", "#00ff00"  # content: the colours the user picks


def part(layer_id: str, tex: str, parent: str = "eq", **fields) -> Layer:
    return Layer(id=layer_id, parent_id=parent, part=PartKey(tex=tex), **fields)


def project(*parts: Layer, root_clips=()) -> Project:
    root = Layer(id="eq", spec=PLAIN, clips=list(root_clips))
    return Project(canvas=CANVAS, layers=[root, *parts])


def coloured(**colours) -> m.Mobject:
    """The plain equation with glyphs coloured as a Manim script would: ``eq[0][i].set_color(c)``."""
    eq = adapter.build_mobject(PLAIN)
    leaves = eq.family_members_with_points()
    for indices, colour in colours.values():
        m.VGroup(*(leaves[i] for i in indices)).set_color(colour)
    return eq


def assert_renders(evaluator: Evaluator, t: float, expected: list[m.Mobject]) -> None:
    camera = make_camera(CANVAS)
    diff = max_diff(render_frame(camera, evaluator.frame(t)), render_frame(camera, expected))
    assert diff <= TOLERANCE, f"t={t}: differs by {diff}"


def differs(evaluator: Evaluator, t: float, expected: list[m.Mobject]) -> bool:
    camera = make_camera(CANVAS)
    return max_diff(render_frame(camera, evaluator.frame(t)), render_frame(camera, expected)) > TOLERANCE


# -- the document --------------------------------------------------------------------------------


def test_style_is_only_valid_on_part_layers_and_checks_its_values() -> None:
    assert part("b", "b^2", style={"fill": RED}).style == {"fill": RED}
    with pytest.raises(ValidationError, match="only part layers have a style"):
        Layer(id="c", spec=Spec(type="Circle"), style={"fill": RED})
    with pytest.raises(ValidationError, match="fill must be a colour"):
        part("b", "b^2", style={"fill": "red"})
    with pytest.raises(ValidationError, match="unknown style key"):
        part("b", "b^2", style={"colour": RED})
    with pytest.raises(ValidationError, match="fill_opacity must be"):
        part("b", "b^2", style={"fill_opacity": 2})


def test_a_part_without_a_style_saves_as_before_and_a_style_round_trips() -> None:
    plain = project(part("b", "b^2"))
    assert "style" not in plain.model_dump(by_alias=True)["layers"][1]  # old files unchanged
    styled = project(part("b", "b^2", style={"fill": RED, "stroke": GREEN}))
    data = styled.model_dump_json(by_alias=True)
    assert Project.model_validate_json(data) == styled
    assert Project.model_validate_json(data).layer("b").style == {"fill": RED, "stroke": GREEN}


def test_set_part_style_merges_removes_and_is_a_spec_edit_of_the_whole_object() -> None:
    p = project(part("b", "b^2"))
    edit = edits.set_part_style(p, "b", fill=RED)
    assert edit.project.layer("b").style == {"fill": RED}
    assert p.layer("b").style == {}  # pure
    assert edit.kind == "spec" and "b" in edit.layer_ids
    both = edits.set_part_style(edit.project, "b", stroke=GREEN)
    assert both.project.layer("b").style == {"fill": RED, "stroke": GREEN}
    cleared = edits.set_part_style(both.project, "b", fill=None, stroke=None)
    assert cleared.project.layer("b").style == {}
    with pytest.raises(edits.EditError, match="not a part"):
        edits.set_part_style(p, "eq", fill=RED)
    with pytest.raises(ValidationError):
        edits.set_part_style(p, "b", fill="nope")
    # The frame cache redraws the whole object while it is alive (ADR 0028).
    assert frame_cache.changed_layers(p, edit.project) == {"eq", "b"}


def test_colour_part_adds_the_part_or_reuses_it_in_one_edit() -> None:
    p = project()
    edit = edits.colour_part(p, "eq", "b^2", 0, fill=RED)
    (made,) = edit.project.children("eq")
    assert (made.part.tex, made.part.occurrence, made.style) == ("b^2", 0, {"fill": RED})
    again = edits.colour_part(edit.project, "eq", "b^2", 0, fill=GREEN)
    assert [x.id for x in again.project.children("eq")] == [made.id]
    assert again.project.layer(made.id).style == {"fill": GREEN}
    with pytest.raises(edits.EditError, match="not in the text"):
        edits.colour_part(p, "eq", "z", 0, fill=RED)


# -- drawing -------------------------------------------------------------------------------------


@pytest.mark.latex
def test_a_coloured_part_draws_its_glyphs_like_set_color_in_manim() -> None:
    evaluator = Evaluator(project(part("b", "b^2", style={"fill": RED})))
    assert_renders(evaluator, 0.5, [coloured(b=(B, RED))])
    assert differs(evaluator, 0.5, [adapter.build_mobject(PLAIN)])
    assert adapter.build_mobject(PLAIN).family_members_with_points()[3].get_fill_color().to_hex() != RED


@pytest.mark.latex
def test_an_inner_part_colour_wins_over_its_parents() -> None:
    outer = part("lhs", "a^2 + b^2", style={"fill": RED})
    inner = part("b", "b^2", parent="lhs", style={"fill": GREEN})
    evaluator = Evaluator(project(outer, inner))
    assert_renders(evaluator, 0.5, [coloured(lhs=((0, 1, 2, 3, 4), RED), b=(B, GREEN))])


@pytest.mark.latex
def test_indicate_on_a_coloured_part_goes_to_its_colour_and_back_as_in_manim() -> None:
    indicate = Clip(id="i", kind="Indicate", start=1.0, duration=1.0)
    evaluator = Evaluator(project(part("b", "b^2", style={"fill": RED}, clips=[indicate])))
    for alpha in (0.25, 0.5):
        eq = coloured(b=(B, RED))
        leaves = eq.family_members_with_points()
        anim = adapter.make_animation("Indicate", m.VGroup(*(leaves[i] for i in B)), None, {})
        anim.begin()
        anim.interpolate(alpha)
        assert_renders(evaluator, 1.0 + alpha, [eq])  # the clip's yellow wins while it plays
    assert_renders(evaluator, 2.5, [coloured(b=(B, RED))])  # and the part's colour is back


@pytest.mark.latex
def test_a_whole_object_clip_keeps_the_part_colour() -> None:
    fade = Clip(id="f", kind="FadeIn", start=0.0, duration=1.0)
    evaluator = Evaluator(project(part("b", "b^2", style={"fill": RED}), root_clips=[fade]))
    eq = coloured(b=(B, RED))
    anim = adapter.make_animation("FadeIn", eq, None, {})
    anim.begin()
    anim.interpolate(0.5)
    assert_renders(evaluator, 0.5, [anim.mobject])


@pytest.mark.latex
def test_a_colour_edit_redraws_and_never_touches_the_build_cache() -> None:
    p = project(part("b", "b^2"))
    evaluator = Evaluator(p)
    assert_renders(evaluator, 0.5, [adapter.build_mobject(PLAIN)])
    misses = adapter._build_cached.cache_info().misses
    red = edits.set_part_style(p, "b", fill=RED)
    evaluator.apply(red)
    assert_renders(evaluator, 0.5, [coloured(b=(B, RED))])
    green = edits.set_part_style(red.project, "b", fill=GREEN)
    evaluator.apply(green)
    assert_renders(evaluator, 0.5, [coloured(b=(B, GREEN))])
    assert adapter._build_cached.cache_info().misses == misses  # same build: no LaTeX run
    evaluator.apply(edits.set_part_style(green.project, "b", fill=None))
    assert_renders(evaluator, 0.5, [adapter.build_mobject(PLAIN)])


@pytest.mark.latex
def test_an_orphaned_coloured_part_colours_nothing() -> None:
    p = project(part("b", "b^2", style={"fill": RED}))
    other = Spec(type="MathTex", params={"text": r"e^{i\pi}+1=0"})  # tests.support.MATH: warm
    retyped = edits.update_layer(p, "eq", spec=other)
    evaluator = Evaluator(retyped.project)
    assert_renders(evaluator, 0.5, [adapter.build_mobject(other)])
