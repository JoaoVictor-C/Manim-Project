"""TransformMatchingTex between equations (P2e, ADR 0020)."""

from __future__ import annotations

import random

import manim as m
import pytest
from pydantic import ValidationError

from manim_studio.core import adapter, edits
from manim_studio.core.evaluator import Evaluator
from manim_studio.core.schema import Canvas, Clip, Layer, PartKey, Project, Spec, Transform2D
from manim_studio.render.cairo_export import make_camera, render_frame
from support import TOLERANCE, max_diff

pytestmark = pytest.mark.latex

CANVAS = Canvas(width_px=320, height_px=180, fps=10, duration=3.0)
EQ1, EQ2 = r"a^2 + b^2 = c^2", r"a^2 = c^2 - b^2"
TERMS1 = {"a^2": (0, 1), "b^2": (3, 4), "c^2": (6, 7)}  # glyph indices (B28)
TERMS2 = {"a^2": (0, 1), "c^2": (3, 4), "b^2": (6, 7)}


def morph(kind: str = "TransformMatchingTex", start: float = 1.0) -> Clip:
    return Clip(id="m", kind=kind, start=start, duration=1.0, to_layer="two")


def project(*, parts: bool = True, kind: str = "TransformMatchingTex", extra_parts=()) -> Project:
    one = Layer(
        id="one",
        spec=Spec(type="MathTex", params={"text": EQ1}),
        base=Transform2D(position=(0, 1)),
        clips=[morph(kind)],
    )
    two = Layer(id="two", spec=Spec(type="MathTex", params={"text": EQ2}), base=Transform2D(position=(0, -1)))
    layers = [one, two]
    if parts:
        layers += [Layer(id=f"one-{k}", parent_id="one", part=PartKey(tex=k)) for k in TERMS1]
        layers += [Layer(id=f"two-{k}", parent_id="two", part=PartKey(tex=k)) for k in TERMS2]
    return Project(canvas=CANVAS, layers=[*layers, *extra_parts])


def groups(mob: m.Mobject, terms: dict[str, tuple[int, ...]], with_parts: bool):
    leaves = mob.family_members_with_points()
    if not with_parts:
        return [(None, mob)]
    taken = {i for idx in terms.values() for i in idx}
    rest = [(None, m.VGroup(*(leaf for i, leaf in enumerate(leaves) if i not in taken)))]
    return rest + [(tex, m.VGroup(*(leaves[i] for i in idx))) for tex, idx in terms.items()]


def reference(alpha: float, with_parts: bool) -> m.Mobject:
    one = adapter.build_mobject(Spec(type="MathTex", params={"text": EQ1})).shift(m.UP)
    two = adapter.build_mobject(Spec(type="MathTex", params={"text": EQ2})).shift(m.DOWN)
    source, target = adapter.keyed_pieces(groups(one, TERMS1, with_parts), groups(two, TERMS2, with_parts))
    anim = adapter.make_animation("TransformMatchingTex", source, None, {}, target)
    anim.begin()
    anim.interpolate(alpha)
    return anim.mobject


def render(mobs) -> object:
    return render_frame(make_camera(CANVAS), mobs)


# -- keys ------------------------------------------------------------------------------------


def test_parts_match_by_tex_and_other_glyphs_by_shape() -> None:
    one = adapter.build_mobject(Spec(type="MathTex", params={"text": EQ1}))
    two = adapter.build_mobject(Spec(type="MathTex", params={"text": EQ2}))
    source, target = adapter.keyed_pieces(groups(one, TERMS1, True), groups(two, TERMS2, True))
    keys = lambda vg: {piece.match_key for piece in vg}  # noqa: E731
    common = keys(source) & keys(target)
    assert {"tex:a^2", "tex:b^2", "tex:c^2"} <= common
    assert len([k for k in common if k.startswith("shape:")]) == 1  # "="
    assert len(keys(source) - keys(target)) == 1 and len(keys(target) - keys(source)) == 1  # "+" out, "-" in


def test_a_part_without_a_counterpart_dissolves_into_glyphs() -> None:
    one = adapter.build_mobject(Spec(type="MathTex", params={"text": EQ1}))
    two = adapter.build_mobject(Spec(type="MathTex", params={"text": EQ1}))
    lhs = [
        (None, m.VGroup(*one.family_members_with_points()[5:])),
        ("a^2 + b^2", m.VGroup(*one.family_members_with_points()[:5])),
    ]
    split = [(None, two)]
    source, target = adapter.keyed_pieces(lhs, split)
    assert all(piece.match_key.startswith("shape:") for piece in source)  # nothing kept as a whole part
    assert {p.match_key for p in source} == {p.match_key for p in target}  # every glyph finds its shape


# -- schema ----------------------------------------------------------------------------------


def test_morph_rules_on_part_trees() -> None:
    project()  # morph between two objects with parts: allowed now
    with pytest.raises(ValidationError, match="a part cannot morph"):
        p = project()
        bad = p.layer("one-b^2").model_copy(update={"clips": [morph()]})
        Project(canvas=CANVAS, layers=[x if x.id != "one-b^2" else bad for x in p.layers])
    late = Layer(
        id="late",
        parent_id="one",
        part=PartKey(tex="="),
        clips=[Clip(id="i", kind="Indicate", start=2.5, duration=0.3)],
    )
    with pytest.raises(ValidationError, match="starts after 'one' begins morphing"):
        project(extra_parts=[late])
    with pytest.raises(ValidationError, match="TransformMatchingTex needs MathTex or Tex, not Square"):
        Layer(
            id="sq",
            spec=Spec(type="Square"),
            clips=[Clip(id="x", kind="TransformMatchingTex", start=0, duration=1, to_layer="t")],
        )
    assert "TransformMatchingTex" in adapter.allowed_clip_kinds("MathTex")
    assert "TransformMatchingTex" not in adapter.allowed_clip_kinds("Square")


# -- evaluation ------------------------------------------------------------------------------


@pytest.mark.parametrize("with_parts", [True, False])
def test_frames_match_hand_built_manim(with_parts: bool) -> None:
    evaluator = Evaluator(project(parts=with_parts))
    for t in (1.25, 1.5, 1.8):
        assert max_diff(render(evaluator.frame(t)), render([reference(t - 1.0, with_parts)])) <= TOLERANCE, t


def test_the_morph_takes_over_the_tree_and_hands_off_to_the_other() -> None:
    evaluator = Evaluator(project())
    assert [i for i, _ in evaluator.frame_layers(0.5)] == ["one", "one-a^2", "one-b^2", "one-c^2"]
    assert [i for i, _ in evaluator.frame_layers(1.5)] == ["one"]  # drawn as one morph
    assert [i for i, _ in evaluator.frame_layers(2.5)] == ["two", "two-a^2", "two-c^2", "two-b^2"]


def test_random_access_matches_playing_in_order() -> None:
    p = project()
    times = [i / CANVAS.fps for i in range(int(CANVAS.duration * CANVAS.fps))]
    camera = make_camera(CANVAS)
    played = Evaluator(p)
    expected = {t: render_frame(camera, played.frame(t)) for t in times}
    shuffled = times[:]
    random.Random(5).shuffle(shuffled)
    scrubbed = Evaluator(p)
    for t in shuffled:
        assert max_diff(render_frame(camera, scrubbed.frame(t)), expected[t]) <= TOLERANCE, t


def test_other_morph_kinds_run_between_part_trees() -> None:
    evaluator = Evaluator(project(kind="Transform"))
    [(layer_id, mob)] = evaluator.frame_layers(1.5)
    assert layer_id == "one" and len(mob.family_members_with_points()) > 0


def test_moving_a_part_rebakes_the_morph() -> None:
    p = project()
    evaluator = Evaluator(p)
    first = evaluator.frame(1.5)
    begun = evaluator._active[("one", "m")].anim
    moved = edits.update_layer(p, "one-b^2", base={"position": (2.0, 0.0)})  # a transform edit: caches kept
    evaluator.apply(moved)
    assert moved.kind == "transform"
    evaluator.frame(1.5)
    assert evaluator._active[("one", "m")].anim is not begun  # its source end changed
    assert max_diff(render(evaluator.frame(1.5)), render(Evaluator(moved.project).frame(1.5))) <= TOLERANCE
    assert first  # (buffers are reused: compare renders, not objects)
