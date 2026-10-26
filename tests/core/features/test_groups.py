"""Groups (U6, ADR 0050): a root that draws nothing and carries its children by its transform.

The contract: a frame equals what Manim draws when each child is placed by its own transform and
then by the group's (about the group's anchor), its opacity multiplied - the hand-built reference
below. Edits keep what they can: a group transform edit rebuilds nothing.
"""

from __future__ import annotations

import math
import shutil
import uuid

import manim as m
import numpy as np
import pytest
from tests.support import CANVAS, CIRCLE, SQUARE, TOLERANCE, max_diff

from manim_studio.core.editing import clipboard, edits
from manim_studio.core.engine import adapter, frame_cache
from manim_studio.core.engine.evaluator import Evaluator, layer_transform
from manim_studio.core.engine.python_export import readable_problems, to_python
from manim_studio.core.model.layer_index import LayerIndex
from manim_studio.core.model.schema import (
    Clip,
    Keyframe,
    Layer,
    Lifetime,
    PartKey,
    Project,
    Spec,
    Transform2D,
)
from manim_studio.render.cairo_export import make_camera, render_frame

GROUP = Spec(type="Group")
DOT = Spec(type="Dot", params={"radius": 0.3}, style={"fill": "#22c55e", "fill_opacity": 1.0})
G_BASE = Transform2D(position=(1.0, -0.5), scale=0.8, rotation=30.0, anchor=(0.5, 0.25), opacity=0.5)
SQ_BASE = Transform2D(position=(-1.0, 0.0), scale=0.7, rotation=-20.0, anchor=(0.3, 0.0))
CI_BASE = Transform2D(position=(1.5, 0.5), opacity=0.8)


def grouped(
    g_base: Transform2D = G_BASE, *, g_fields=None, sq_fields=None, ci_fields=None, more=()
) -> Project:
    """back, [group: square, circle], front."""
    return Project(
        canvas=CANVAS,
        layers=[
            Layer(id="back", spec=DOT, base=Transform2D(position=(-3.0, 1.5))),
            Layer(id="g", spec=GROUP, base=g_base, **(g_fields or {})),
            Layer(id="sq", parent_id="g", spec=SQUARE, base=SQ_BASE, **(sq_fields or {})),
            Layer(id="ci", parent_id="g", spec=CIRCLE, base=CI_BASE, **(ci_fields or {})),
            Layer(id="front", spec=DOT, base=Transform2D(position=(3.0, -1.5))),
            *more,
        ],
    )


def place(mob: m.Mobject, tr: Transform2D) -> m.Mobject:
    """A layer transform the way a Manim script writes it: scale and turn about the anchor, move."""
    pivot = np.array([*tr.anchor, 0.0])
    mob.scale(tr.scale, about_point=pivot)
    mob.rotate(math.radians(tr.rotation), about_point=pivot)
    mob.shift(np.array([*tr.position, 0.0]))
    return mob


def fade(mob: m.Mobject, fill: float, stroke: float) -> m.Mobject:
    mob.set_fill(opacity=fill)
    mob.set_stroke(opacity=stroke)
    return mob


def reference(g_base: Transform2D = G_BASE, circle: m.Mobject | None = None) -> list[m.Mobject]:
    """The frame of ``grouped()`` built by hand: each child placed by its own transform, then the group's."""
    back = place(adapter.build_mobject(DOT), Transform2D(position=(-3.0, 1.5)))
    square = place(place(adapter.build_mobject(SQUARE), SQ_BASE), g_base)
    fade(square, 0.6 * g_base.opacity, 1.0 * g_base.opacity)  # SQUARE: fill 0.6, stroke 1
    circle = circle if circle is not None else adapter.build_mobject(CIRCLE)
    circle = place(place(circle, CI_BASE), g_base)
    fade(circle, 0.5 * 0.8 * g_base.opacity, 1.0 * 0.8 * g_base.opacity)  # CIRCLE: fill 0.5
    front = place(adapter.build_mobject(DOT), Transform2D(position=(3.0, -1.5)))
    return [back, square, circle, front]


def assert_draws(evaluator: Evaluator, t: float, expected: list[m.Mobject], label: str = "") -> None:
    camera = make_camera(CANVAS)
    diff = max_diff(render_frame(camera, evaluator.frame(t)), render_frame(camera, expected))
    assert diff <= TOLERANCE, f"{label} t={t}: differs by {diff}"


def assert_same_frames(a: Project, b: Project, times=(0.0, 0.25, 0.5, 0.75, 0.95)) -> None:
    camera = make_camera(CANVAS)
    ea, eb = Evaluator(a), Evaluator(b)
    for t in times:
        diff = max_diff(render_frame(camera, ea.frame(t)), render_frame(camera, eb.frame(t)))
        assert diff <= TOLERANCE, f"t={t}: differs by {diff}"


# -- the file format -------------------------------------------------------------------------------


def test_a_group_saves_as_a_spec_without_params() -> None:
    project = grouped()
    data = project.model_dump(by_alias=True)
    assert data["layers"][1]["spec"] == {"type": "Group", "params": {}, "style": {}}
    assert data["layers"][2]["parent_id"] == "g"
    assert Project.model_validate_json(project.model_dump_json(by_alias=True)) == project
    assert project.layer("g").is_group and not project.layer("sq").is_group


@pytest.mark.parametrize(
    ("layers", "message"),
    [
        (
            [{"id": "g", "spec": GROUP, "clips": [{"id": "f", "kind": "FadeIn", "start": 0, "duration": 1}]}],
            "a group has no clips",
        ),
        (
            [Layer(id="g", spec=GROUP), {"id": "h", "parent_id": "g", "spec": GROUP}],
            "cannot be inside another group",
        ),
        (
            [Layer(id="g", spec=GROUP), Layer(id="p", parent_id="g", part=PartKey(tex="a"))],
            "a part belongs to its MathTex or Tex",
        ),
        (
            [
                Layer(id="g", spec=GROUP),
                Layer(id="eq", parent_id="g", spec=Spec(type="MathTex", params={"text": "a+b"})),
                Layer(id="p", parent_id="eq", part=PartKey(tex="a")),
            ],
            "with parts or objects on axes cannot be in a group",
        ),
        (
            [
                Layer(id="g", spec=GROUP),
                Layer(id="axes", parent_id="g", spec=Spec(type="Axes")),
                Layer(id="gr", parent_id="axes", spec=Spec(type="Graph", params={"expression": "x"})),
            ],
            "with parts or objects on axes cannot be in a group",
        ),
        (
            [
                Layer(id="a", spec=DOT),
                Layer(id="b", spec=DOT),
                Layer(id="g", spec=GROUP),
                Layer(
                    id="c",
                    parent_id="g",
                    spec=Spec(type="Connector", params={"source": "a", "target": "b"}),
                ),
            ],
            "a connector is drawn where its layers are",
        ),
        (
            [
                Layer(id="out", spec=DOT),
                Layer(id="g", spec=GROUP),
                Layer(
                    id="sq",
                    parent_id="g",
                    spec=SQUARE,
                    clips=[Clip(id="m", kind="Transform", start=0, duration=1, to_layer="out")],
                ),
            ],
            "a morph stays inside its group",
        ),
        (
            [
                Layer(id="g", spec=GROUP),
                Layer(
                    id="sq",
                    spec=SQUARE,
                    clips=[Clip(id="m", kind="Transform", start=0, duration=1, to_layer="g")],
                ),
            ],
            "cannot morph into a group",
        ),
        (
            [
                Layer(id="g", spec=GROUP),
                Layer(id="in", parent_id="g", spec=DOT),
                Layer(
                    id="sq",
                    spec=SQUARE,
                    clips=[Clip(id="r", kind="MoveAlongPath", start=0, duration=1, params={"path": "g"})],
                ),
            ],
            "cannot be its path",
        ),
    ],
    ids=["clip", "nested", "part", "with-parts", "axes", "connector", "morph-out", "morph-into", "path"],
)
def test_what_a_v1_group_refuses(layers: list[Layer], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        Project(canvas=CANVAS, layers=layers)


def test_a_morph_inside_one_group_and_a_path_clip_in_a_group_are_allowed() -> None:
    morph = Clip(id="m", kind="Transform", start=0.2, duration=0.5, to_layer="ci")
    run = Clip(id="r", kind="MoveAlongPath", start=0, duration=1, params={"path": "back"})
    project = grouped(sq_fields={"clips": [morph]}, ci_fields={"clips": [run]})
    assert project.morph_sources()["ci"].id == "m"


# -- drawing ----------------------------------------------------------------------------------------


def test_children_are_drawn_in_order_where_the_group_is_stacked() -> None:
    assert [owner for owner, _ in Evaluator(grouped()).frame_layers(0.5)] == ["back", "sq", "ci", "front"]


def test_the_group_transform_composes_onto_each_childs_own() -> None:
    evaluator = Evaluator(grouped())
    for t in (0.0, 0.5):
        assert_draws(evaluator, t, reference())


def test_a_childs_clip_plays_inside_the_group() -> None:
    project = grouped(ci_fields={"clips": [Clip(id="c", kind="Create", start=0, duration=1)]})
    evaluator = Evaluator(project)
    for alpha in (0.3, 0.7, 0.45):  # out of order: random access
        anim = adapter.make_animation("Create", adapter.build_mobject(CIRCLE), None, {})
        anim.begin()
        anim.interpolate(alpha)
        assert_draws(evaluator, alpha, reference(circle=anim.mobject.copy()), "Create")


def test_group_keys_move_every_child() -> None:
    track = [Keyframe(t=0.0, value=(0.0, 0.0), ease={"name": "linear"}), Keyframe(t=1.0, value=(2.0, 1.0))]
    project = grouped(g_fields={"tracks": {"position": track}})
    evaluator = Evaluator(project)
    for t in (0.25, 0.6):
        assert_draws(evaluator, t, reference(layer_transform(project.layer("g"), t)), "keyed")


def test_a_group_of_unbuildable_formulas_draws_placeholders(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))  # no LaTeX, as on the user's other computer
    assert shutil.which("latex") is None
    text = rf"x^2 + \text{{{uuid.uuid4().hex[:8]}}}"
    project = Project(
        canvas=CANVAS,
        layers=[
            Layer(id="g", spec=GROUP, base=Transform2D(position=(1.0, 0.0), rotation=15)),
            Layer(id="eq", parent_id="g", spec=Spec(type="MathTex", params={"text": text})),
            Layer(id="c", parent_id="g", spec=CIRCLE),
        ],
    )
    evaluator = Evaluator(project)
    drawn = dict(evaluator.frame_layers(0.5))
    assert drawn["eq"].family_members_with_points() and drawn["c"].family_members_with_points()
    assert "LaTeX is not installed" in evaluator.build_errors()["eq"]
    for layer, index in evaluator.missing_checkpoints():
        evaluator.compute_checkpoint(layer, index)


def test_a_connector_to_a_group_ends_at_its_childrens_box() -> None:
    connector = Layer(
        id="link", spec=Spec(type="Connector", params={"source": "back", "target": "g", "ends": "centres"})
    )
    drawn = dict(Evaluator(grouped(more=[connector])).frame_layers(0.5))
    points = np.vstack([drawn[i].get_all_points()[:, :2] for i in ("sq", "ci")])
    centre = (points.min(axis=0) + points.max(axis=0)) / 2
    start, end = drawn["link"].get_start()[:2], drawn["link"].get_end()[:2]
    aim, line = centre - start, end - start
    assert abs(aim[0] * line[1] - aim[1] * line[0]) < 1e-6 * np.linalg.norm(aim) * np.linalg.norm(line)
    assert np.linalg.norm(centre - end) < 0.3  # toward the box's centre, short of it by its gap


def test_a_traced_path_of_a_group_follows_its_childrens_box() -> None:
    track = [Keyframe(t=0.0, value=(0.0, 0.0), ease={"name": "linear"}), Keyframe(t=1.0, value=(2.0, 0.0))]
    trace = Layer(id="tr", spec=Spec(type="TracedPath", params={"target": "g"}))
    project = grouped(g_fields={"tracks": {"position": track}}, more=[trace])
    evaluator = Evaluator(project)
    drawn = dict(evaluator.frame_layers(0.6))
    points = np.vstack([drawn[i].get_all_points()[:, :2] for i in ("sq", "ci")])
    centre = (points.min(axis=0) + points.max(axis=0)) / 2
    assert drawn["tr"].get_all_points()[-1, :2] == pytest.approx(centre, abs=1e-6)


def test_a_code_layer_in_a_group_is_carried_by_it(tmp_path) -> None:
    from manim_studio.core.code.code_cache import CodeCache

    code = Spec(type="Code", params={"code": "class Dots(Scene): ..."})
    group = Transform2D(position=(1.0, 0.5), scale=0.5, rotation=90.0, opacity=0.5)
    project = Project(
        canvas=CANVAS,
        layers=[
            Layer(id="g", spec=GROUP, base=group),
            Layer(id="code", parent_id="g", spec=code, base=Transform2D(position=(0.5, 0.0))),
        ],
    )
    evaluator = Evaluator(project, CodeCache(tmp_path))
    writer = evaluator.code_cache.writer(evaluator.code_key(project.layer("code")), 320, 180, CANVAS.fps)
    writer.add(np.full((180, 320, 4), 255, dtype=np.uint8))  # opaque: the crop is the whole frame
    writer.finish()
    (frame,) = evaluator.frame(0.0)
    a, b = evaluator.world_affine(project.layer("code"), 0.0)
    assert np.allclose(a, [[0.0, -0.5], [0.5, 0.0]]) and np.allclose(b, [1.0, 0.75])
    assert np.allclose(frame.points[:, :2].mean(axis=0), b)  # the frame is centred where it is carried
    assert frame.opacity == pytest.approx(0.5)


# -- lifetime ---------------------------------------------------------------------------------------


def test_a_groups_lifetime_is_the_span_of_its_children() -> None:
    fade_in = Clip(id="f", kind="FadeIn", start=0.4, duration=0.2)
    project = grouped(sq_fields={"lifetime": Lifetime(in_=0.2, out=0.6)}, ci_fields={"clips": [fade_in]})
    evaluator, index = Evaluator(project), LayerIndex(project)
    for layer_id, expected in (("g", (0.2, math.inf)), ("sq", (0.2, 0.6)), ("ci", (0.4, math.inf))):
        assert project.lifetime(layer_id) == expected
        assert index.lifetime(layer_id) == expected
        assert evaluator.lifetime(project.layer(layer_id)) == expected
    assert [o for o, _ in evaluator.frame_layers(0.1)] == ["back", "front"]


def test_an_explicit_appears_on_the_group_clamps_its_children() -> None:
    project = grouped(
        g_fields={"lifetime": Lifetime(in_=0.5, out=0.8)}, sq_fields={"lifetime": Lifetime(out=0.6)}
    )
    evaluator = Evaluator(project)
    assert evaluator.lifetime(project.layer("sq")) == (0.5, 0.6)
    assert project.lifetime("ci") == LayerIndex(project).lifetime("ci") == (0.5, 0.8)
    assert [o for o, _ in evaluator.frame_layers(0.3)] == ["back", "front"]
    assert [o for o, _ in evaluator.frame_layers(0.7)] == ["back", "ci", "front"]


def test_an_empty_group_is_never_visible() -> None:
    project = Project(canvas=CANVAS, layers=[Layer(id="g", spec=GROUP)])
    assert project.lifetime("g") == (0.0, 0.0)
    assert Evaluator(project).frame_layers(0.0) == []


# -- caches -----------------------------------------------------------------------------------------


def test_a_group_transform_edit_keeps_every_cache_and_moves_every_child() -> None:
    project = grouped(ci_fields={"clips": [Clip(id="i", kind="Indicate", start=0.1, duration=0.3)]})
    evaluator = Evaluator(project)
    evaluator.frame(0.2)
    evaluator.frame(0.6)
    builds = {i: evaluator._base[i] for i in ("sq", "ci")}
    checkpoints = set(evaluator._checkpoints)
    moved = Transform2D(position=(-0.5, 0.5), scale=1.2, rotation=-40.0, anchor=(0.5, 0.25), opacity=0.7)
    edit = edits.update_layer(project, "g", base=moved)
    assert (edit.kind, edit.layer_ids) == ("transform", frozenset({"g"}))
    evaluator.apply(edit)
    assert all(evaluator._base[i] is built for i, built in builds.items())
    assert checkpoints <= set(evaluator._checkpoints)
    assert_draws(evaluator, 0.6, reference(moved), "after the edit")


def test_a_key_edit_on_the_group_moves_every_child() -> None:
    project = grouped()
    evaluator = Evaluator(project)
    before = {o: mob.get_center().copy() for o, mob in evaluator.frame_layers(0.5)}
    edit = edits.set_key(project, "g", "position", 0.5, (G_BASE.position[0] + 1.0, G_BASE.position[1]))
    assert edit.kind == "transform"
    evaluator.apply(edit)
    after = {o: mob.get_center() for o, mob in evaluator.frame_layers(0.5)}
    for owner in ("sq", "ci"):
        assert after[owner] == pytest.approx(before[owner] + np.array([1.0, 0.0, 0.0]), abs=1e-9)
    for owner in ("back", "front"):
        assert after[owner] == pytest.approx(before[owner])


def test_a_clip_edit_on_one_child_keeps_its_siblings_caches() -> None:
    indicate = Clip(id="i", kind="Indicate", start=0.1, duration=0.3)
    project = grouped(sq_fields={"clips": [indicate]}, ci_fields={"clips": [indicate]})
    evaluator = Evaluator(project)
    evaluator.frame(0.2)
    evaluator.frame(0.6)
    kept = {key for key in evaluator._checkpoints if key[0] == "ci"}
    assert kept
    edit = edits.update_clip(project, "sq", "i", kind="Wiggle")
    assert edit.kind == "clip"
    evaluator.apply(edit)
    assert kept <= set(evaluator._checkpoints)  # each child is its own object
    assert not {key for key in evaluator._checkpoints if key[0] == "sq"}


def test_a_morph_inside_a_group_follows_a_group_transform_edit() -> None:
    morph = Clip(id="m", kind="Transform", start=0.2, duration=0.6, to_layer="ci")
    project = grouped(sq_fields={"clips": [morph]})
    evaluator = Evaluator(project)
    evaluator.frame(0.5)  # the morph is begun with both ends baked
    edit = edits.update_layer(project, "g", base=Transform2D(position=(-1.0, 1.0), rotation=50.0))
    evaluator.apply(edit)  # a transform edit keeps caches: the morph must notice its ends moved
    camera = make_camera(CANVAS)
    fresh = Evaluator(edit.project)
    diff = max_diff(render_frame(camera, evaluator.frame(0.5)), render_frame(camera, fresh.frame(0.5)))
    assert diff <= TOLERANCE


def test_a_path_clip_in_a_group_follows_a_group_transform_edit() -> None:
    run = Clip(id="r", kind="MoveAlongPath", start=0.0, duration=1.0, params={"path": "front"})
    project = grouped(ci_fields={"clips": [run]})
    evaluator = Evaluator(project)
    evaluator.frame(0.5)
    evaluator.frame(1.0)  # the run's checkpoint
    edit = edits.update_layer(project, "g", base=Transform2D(position=(-1.0, 1.0), scale=0.5))
    evaluator.apply(edit)
    fresh = Evaluator(edit.project)
    for t in (0.5, 1.0):
        got = dict(evaluator.frame_layers(t))["ci"].get_center()
        assert got == pytest.approx(dict(fresh.frame_layers(t))["ci"].get_center(), abs=1e-9)
    # it rides the path (the dot's outline, from its right) in world units, wherever the group is
    assert dict(fresh.frame_layers(0.999))["ci"].get_center()[:2] == pytest.approx((3.3, -1.5), abs=0.05)


def test_frame_cache_spans_follow_the_children() -> None:
    project = grouped(
        sq_fields={"lifetime": Lifetime(in_=0.2, out=0.6)}, ci_fields={"lifetime": Lifetime(in_=0.4, out=0.9)}
    )
    moved_group = edits.update_layer(project, "g", base=Transform2D(position=(2.0, 0.0))).project
    assert frame_cache.changed_spans(project, moved_group) == [(0.2, 0.9)]
    moved_square = edits.update_layer(project, "sq", base=Transform2D(position=(2.0, 0.0))).project
    assert frame_cache.changed_spans(project, moved_square) == [(0.2, 0.6)]  # not its sibling's


# -- edits ------------------------------------------------------------------------------------------


def loose() -> Project:
    return Project(
        canvas=CANVAS,
        layers=[
            Layer(id="back", spec=DOT, base=Transform2D(position=(-3.0, 1.5))),
            Layer(
                id="sq", spec=SQUARE, base=SQ_BASE, clips=[Clip(id="w", kind="Create", start=0, duration=0.5)]
            ),
            Layer(id="ci", spec=CIRCLE, base=CI_BASE),
            Layer(id="front", spec=DOT, base=Transform2D(position=(3.0, -1.5))),
        ],
    )


def test_grouping_keeps_ids_looks_and_builds() -> None:
    project = loose()
    evaluator = Evaluator(project)
    evaluator.frame(0.3)
    builds = {i: evaluator._base[i] for i in ("sq", "ci")}
    edit = edits.group_layers(project, ["ci", "sq"], name="Shapes")
    new = edit.project
    assert [x.id for x in new.layers] == ["back", "group-1", "sq", "ci", "front"]
    group = new.layer("group-1")
    assert group.is_group and group.name == "Shapes" and group.base == Transform2D()
    assert new.layer("sq").spec == SQUARE and new.layer("sq").clips == project.layer("sq").clips
    assert {x.parent_id for x in new.layers if x.id in ("sq", "ci")} == {"group-1"}
    evaluator.apply(edit)
    assert all(evaluator._base[i] is built for i, built in builds.items())  # nothing rebuilt
    assert_same_frames(project, new)


def test_moving_an_object_into_or_out_of_a_group_is_a_transform_edit() -> None:
    project = grouped()
    into = edits.update_layer(project, "front", parent_id="g")
    assert edits.classify(project, into.project) == ("transform", frozenset({"front"}))
    out = edits.update_layer(project, "sq", parent_id=None)
    assert edits.classify(project, out.project) == ("transform", frozenset({"sq"}))


def test_grouping_brings_the_objects_to_the_front_most_one() -> None:
    edit = edits.group_layers(loose(), ["back", "ci"])
    assert [x.id for x in edit.project.layers] == ["sq", "group-1", "back", "ci", "front"]


@pytest.mark.parametrize(
    ("ids", "message"),
    [
        ([], "select the objects"),
        (["g"], "groups cannot be put in a group"),
        (["sq"], "group whole objects"),
        (["missing"], "no layer"),
    ],
)
def test_grouping_refuses_what_v1_cannot_hold(ids, message) -> None:
    with pytest.raises(edits.EditError, match=message):
        edits.group_layers(grouped(), ids)


def test_grouping_refuses_objects_with_parts_and_world_drawn_layers() -> None:
    project = Project(
        canvas=CANVAS,
        layers=[
            Layer(id="eq", spec=Spec(type="MathTex", params={"text": "a+b"})),
            Layer(id="p", parent_id="eq", part=PartKey(tex="a")),
            Layer(id="a", spec=DOT),
            Layer(id="c", spec=Spec(type="Connector", params={"source": "a", "target": "eq"})),
        ],
    )
    with pytest.raises(edits.EditError, match="has parts or objects on axes"):
        edits.group_layers(project, ["eq"])
    with pytest.raises(edits.EditError, match=r"cannot group: .*connector"):
        edits.group_layers(project, ["a", "c"])


def test_ungrouping_bakes_the_group_transform_into_each_child() -> None:
    curved = [
        Keyframe(t=0.0, value=(-1.0, 0.0), out_tangent=(0.5, 1.0)),
        Keyframe(t=0.8, value=(0.5, -0.5), in_tangent=(-0.5, 0.5)),
    ]
    sq_tracks = {
        "position": curved,
        "scale": [Keyframe(t=0.1, value=0.5), Keyframe(t=0.9, value=1.2)],
        "rotation": [Keyframe(t=0.2, value=0.0), Keyframe(t=0.7, value=90.0)],
        "opacity": [Keyframe(t=0.0, value=1.0), Keyframe(t=1.0, value=0.4)],
    }
    project = grouped(
        sq_fields={"tracks": sq_tracks, "clips": [Clip(id="i", kind="Indicate", start=0.3, duration=0.4)]}
    )
    edit = edits.ungroup(project, "g")
    new = edit.project
    assert [x.id for x in new.layers] == ["back", "sq", "ci", "front"]
    assert all(x.parent_id is None for x in new.layers)
    assert new.layer("sq").base.anchor == SQ_BASE.anchor  # its own pivot is kept
    assert_same_frames(project, new, times=(0.0, 0.15, 0.4, 0.55, 0.85))


def test_ungrouping_keeps_the_groups_appears_and_disappears() -> None:
    project = grouped(
        g_fields={"lifetime": Lifetime(in_=0.3, out=0.7)}, ci_fields={"lifetime": Lifetime(in_=0.5)}
    )
    new = edits.ungroup(project, "g").project
    assert new.lifetime("sq") == (0.3, 0.7)
    assert new.lifetime("ci") == (0.5, 0.7)
    assert new.layer("ci").lifetime.in_ == 0.5  # later than the group's: its own is kept


def test_ungrouping_a_keyed_group_asks_to_bake_the_keys_first() -> None:
    track = [Keyframe(t=0.0, value=1.0), Keyframe(t=1.0, value=2.0)]
    with pytest.raises(edits.EditError, match="bake the keys first"):
        edits.ungroup(grouped(g_fields={"tracks": {"scale": track}}), "g")
    with pytest.raises(edits.EditError, match="not a group"):
        edits.ungroup(grouped(), "sq")


def test_deleting_a_group_deletes_its_children_and_an_emptied_group_goes_too() -> None:
    project = grouped()
    assert [x.id for x in edits.remove_layer(project, "g").project.layers] == ["back", "front"]
    assert [x.id for x in edits.remove_layers(project, ["sq", "ci"]).project.layers] == ["back", "front"]
    assert [x.id for x in edits.remove_layer(project, "sq").project.layers] == ["back", "g", "ci", "front"]


def test_duplicating_a_group_copies_its_children_with_new_ids() -> None:
    project = grouped()
    pasted = clipboard.duplicate_layers(project, ["g"])
    new = pasted.edit.project
    copy = new.layer(pasted.selected)
    assert copy.is_group and copy.id not in {x.id for x in project.layers}
    kids = new.children(copy.id)
    assert [k.spec for k in kids] == [SQUARE, CIRCLE]
    assert not {k.id for k in kids} & {x.id for x in project.layers}
    assert [x.id for x in new.children("g")] == ["sq", "ci"]


def test_an_object_copied_out_of_a_group_pastes_into_it_or_on_its_own() -> None:
    project = grouped()
    data = clipboard.copy_layers(project, ["sq"])
    inside = clipboard.paste_layers(project, data.payload, above="sq")
    assert inside.edit.project.layer(inside.selected).parent_id == "g"
    elsewhere = Project(canvas=CANVAS, layers=[Layer(id="x", spec=DOT)])
    alone = clipboard.paste_layers(elsewhere, data.payload)
    assert alone.edit.project.layer(alone.selected).parent_id is None


def test_the_readable_export_falls_back_to_the_exact_form() -> None:
    project = grouped()
    assert "g: groups are evaluated as one object" in readable_problems(project)
    assert "sq: groups are evaluated as one object" in readable_problems(project)
    assert not to_python(project).readable
    assert not any("groups" in why for why in readable_problems(loose()))


def test_old_files_without_groups_validate_as_before() -> None:
    project = loose()
    assert Project.model_validate_json(project.model_dump_json(by_alias=True)) == project
    assert edits.classify(project, project) == ("timing", frozenset())
