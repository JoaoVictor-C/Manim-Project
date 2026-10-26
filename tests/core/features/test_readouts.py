"""Value readouts and connectors (P5b.1, ADR 0036).

A Number is Manim's DecimalNumber and counts with a ChangeDecimalToValue clip:
the clip harness of ADR 0007 must hold (any frame order equals Manim's own
play loop), clips chain from the value the last one ended on, and the number
keeps its left edge. A Connector is a Line or Arrow between two layers, ending
where the line between their centres leaves each drawing's box (or at the
centres), drawn again from its layers every frame.
"""

from __future__ import annotations

import random

import manim as m
import numpy as np
import pytest
from pydantic import ValidationError
from tests.support import CANVAS, FRAMES, assert_frames_equal, render_in_order

from manim_studio.core.editing import edits
from manim_studio.core.engine import adapter, warm
from manim_studio.core.engine.evaluator import Evaluator
from manim_studio.core.engine.frame_cache import changed_layers
from manim_studio.core.engine.python_export import readable_problems, to_python
from manim_studio.core.model.schema import Clip, Easing, Keyframe, Layer, Lifetime, Project, Spec, Transform2D
from manim_studio.render.cairo_export import make_camera, render_frame

pytestmark = pytest.mark.latex  # a DecimalNumber is one LaTeX glyph per character

NUMBER = Spec(type="DecimalNumber", params={"number": 2.5}, style={"fill": "#facc15"})


def count(*clips: Clip, spec: Spec = NUMBER, base: Transform2D | None = None) -> Project:
    layer = Layer(id="n", spec=spec, clips=list(clips), base=base or Transform2D())
    return Project(canvas=CANVAS, layers=[layer])


def to_value(value: float, start: float = 0.0, duration: float = 1.0, ease: Easing | None = None) -> Clip:
    return Clip(
        id=f"c{start:g}",
        kind="ChangeDecimalToValue",
        start=start,
        duration=duration,
        ease=ease,
        params={"target_number": value},
    )


def drawn_number(project: Project, t: float) -> m.Mobject:
    return Evaluator(project).frame_layers(t)[0][1]


# -- Number --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("ease", [None, Easing(name="smooth"), Easing(bezier=(0.3, 1.6, 0.6, 1.0))])
def test_counting_is_random_access(ease: Easing | None) -> None:
    """Frames scrubbed, shuffled or from a fresh evaluator equal Manim's play loop (ADR 0007)."""
    project = count(to_value(-137.25, ease=ease))
    camera = make_camera(CANVAS)
    mob = adapter.build_mobject(NUMBER)
    anim = adapter.make_animation("ChangeDecimalToValue", mob, ease, {"target_number": -137.25})
    anim.begin()
    expected = []
    for t in FRAMES:
        anim.interpolate(t)
        expected.append(render_frame(camera, [anim.mobject]))
    n = len(FRAMES)
    shuffled = random.Random(5).sample(range(n), n)
    assert_frames_equal(expected, render_in_order(project, shuffled, fresh_each_frame=True), "fresh")
    assert_frames_equal(expected, render_in_order(project, list(reversed(range(n))) + shuffled), "scrub")


def test_the_value_runs_from_the_number_to_the_target_and_stays() -> None:
    evaluator = Evaluator(count(to_value(10.0)))
    values = [evaluator.frame_layers(t)[0][1].number for t in (0.0, 0.5, 0.99, 1.5)]
    assert values[0] == pytest.approx(2.5)
    assert values[1] == pytest.approx(6.25)  # Manim's default: linear
    assert 2.5 < values[2] < 10.0
    assert values[3] == pytest.approx(10.0)  # the checkpoint after the clip


def test_clips_chain_from_where_the_last_one_ended() -> None:
    project = count(to_value(10.0, 0.0, 0.4), to_value(4.0, 0.5, 0.4))
    evaluator = Evaluator(project)
    assert evaluator.frame_layers(0.45)[0][1].number == pytest.approx(10.0)
    assert evaluator.frame_layers(0.7)[0][1].number == pytest.approx(7.0)
    assert evaluator.frame_layers(0.95)[0][1].number == pytest.approx(4.0)


def test_the_number_keeps_its_left_edge_and_its_colour() -> None:
    project = count(to_value(12345.0), base=Transform2D(position=(1.0, -1.0)))
    evaluator = Evaluator(project)
    start = evaluator.frame_layers(0.0)[0][1]
    left, colour = start.get_left()[0], start.family_members_with_points()[0].get_fill_color()
    end = evaluator.frame_layers(0.99)[0][1]
    assert end.width > start.width + 1.0  # more digits
    assert end.get_left()[0] == pytest.approx(left, abs=1e-6)
    assert all(sub.get_fill_color() == colour for sub in end.family_members_with_points())


def test_the_count_belongs_to_numbers() -> None:
    assert "ChangeDecimalToValue" in adapter.allowed_clip_kinds("DecimalNumber")
    assert "ChangeDecimalToValue" not in adapter.allowed_clip_kinds("Square")
    with pytest.raises(ValidationError, match="needs DecimalNumber"):
        Layer(id="s", spec=Spec(type="Square"), clips=[to_value(1.0)])
    with pytest.raises(ValidationError, match="target_number must be a number"):
        Clip(id="c", kind="ChangeDecimalToValue", start=0, duration=1, params={"target_number": "ten"})
    assert not to_value(1.0).info.introducer and not to_value(1.0).info.remover


def test_number_params_are_manims() -> None:
    spec = Spec(type="DecimalNumber", params={"number": 3, "include_sign": "yes", "unit": ""})
    assert adapter.number_kwargs(spec) == {"number": 3, "include_sign": True}
    assert adapter.number_kwargs(Spec(type="DecimalNumber", params={"unit": "m"})) == {"unit": "m"}
    signed = adapter.build_mobject(spec)
    assert signed.include_sign and signed.unit is None and signed.number == 3


def test_one_warm_key_per_unit_and_sign_holding_every_glyph() -> None:
    def key(**params):
        return warm.warm_key(Spec(type="DecimalNumber", params=params))

    assert key(number=1.0) == key(number=-75.5, num_decimal_places=4, font_size=96)
    assert key(unit="m") != key() != key(include_sign="yes")
    built = adapter.build_mobject(warm.key_spec(key(unit="m")))
    shown = f"{built.number:,.1f}"  # what DecimalNumber writes: grouped, one decimal place
    assert set("0123456789,.-") <= set(shown) and built.unit == "m"


def test_a_count_exports_as_plain_manim() -> None:
    project = count(to_value(-4.0, 0.0, 1.0))
    export = to_python(project, "Count")
    assert export.readable
    assert "DecimalNumber(number=2.5)" in export.code
    assert "ChangeDecimalToValue(n, target_number=-4.0)" in export.code


# -- Connector -----------------------------------------------------------------------------------------


def square(layer_id: str, x: float, **fields) -> Layer:
    return Layer(id=layer_id, spec=Spec(type="Square"), base=Transform2D(position=(x, 0.0)), **fields)


def connector(**params) -> Layer:
    return Layer(id="link", spec=Spec(type="Connector", params={"source": "a", "target": "b", **params}))


def joined(
    *extra: Layer, link: Layer | None = None, a: Layer | None = None, b: Layer | None = None
) -> Project:
    layers = [a or square("a", -3.0), b or square("b", 3.0), link or connector(), *extra]
    return Project(canvas=CANVAS, layers=layers)


def link_at(project: Project, t: float = 0.0) -> m.Mobject:
    return dict(Evaluator(project).frame_layers(t))["link"]


def ends(mob: m.Mobject) -> tuple[np.ndarray, np.ndarray]:
    return mob.get_start()[:2], mob.get_end()[:2]


def test_the_ends_leave_the_boxes_along_the_centre_line() -> None:
    box = (np.array([-1.0, -1.0]), np.array([1.0, 1.0]))
    other = (np.array([3.0, 2.0]), np.array([5.0, 4.0]))
    start, end = adapter.connector_ends(np.zeros(2), np.array([4.0, 3.0]), box, other, "edges")
    assert start == pytest.approx([1.0, 0.75]) and end == pytest.approx([3.0, 2.25])
    assert adapter.connector_ends(np.zeros(2), np.array([4.0, 3.0]), box, other, "centres")[
        1
    ] == pytest.approx([4.0, 3.0])
    overlapping = (np.array([0.5, -1.0]), np.array([2.5, 1.0]))
    assert adapter.connector_ends(np.zeros(2), np.array([1.5, 0.0]), box, overlapping, "edges") is None
    assert adapter.connector_ends(np.ones(2), np.ones(2), box, box, "centres") is None
    outside = adapter.box_exit(np.array([2.0, 0.0]), np.array([1.0, 0.0]), *box)
    assert outside == 0.0  # a point off its own drawing starts the line where it is


def test_a_connector_runs_between_the_edges_less_its_gap() -> None:
    start, end = ends(link_at(joined()))
    assert start == pytest.approx([-1.9, 0.0]) and end == pytest.approx([1.9, 0.0])
    start, end = ends(link_at(joined(link=connector(ends="centres", gap=0.0))))
    assert start == pytest.approx([-3.0, 0.0]) and end == pytest.approx([3.0, 0.0])


def test_tips_and_colour() -> None:
    style = {"stroke": "#ef4444", "stroke_width": 3}
    arrow = link_at(
        joined(
            link=connector(tips="end").model_copy(
                update={
                    "spec": Spec(
                        type="Connector", params={"source": "a", "target": "b", "tips": "end"}, style=style
                    )
                }
            )
        )
    )
    assert isinstance(arrow, m.Arrow) and not isinstance(arrow, m.DoubleArrow)
    assert arrow.tip.get_fill_color() == m.ManimColor("#ef4444")  # the tip takes the colour too
    assert isinstance(link_at(joined(link=connector(tips="both"))), m.DoubleArrow)
    assert type(link_at(joined())) is m.Line


def test_a_connector_follows_moving_layers_in_any_frame_order() -> None:
    moving = square(
        "b", 3.0, tracks={"position": [Keyframe(t=0, value=(3.0, -2.0)), Keyframe(t=1, value=(1.0, 2.5))]}
    )
    project = joined(b=moving)
    n = len(FRAMES)
    in_order = render_in_order(project, list(range(n)))
    expected = [in_order[i] for i in range(n)]
    shuffled = random.Random(9).sample(range(n), n)
    assert_frames_equal(expected, render_in_order(project, shuffled, fresh_each_frame=True), "fresh")
    assert_frames_equal(expected, render_in_order(project, list(reversed(range(n))) + shuffled), "scrub")
    first, last = ends(link_at(project, 0.0))[1], ends(link_at(project, 0.99))[1]
    assert first[1] < -0.5 and last[1] > 1.0


def test_nothing_is_drawn_while_either_layer_is_hidden() -> None:
    late = square("b", 3.0, lifetime=Lifetime(in_=0.5))
    project = joined(b=late)
    assert not link_at(project, 0.2).family_members_with_points()
    assert link_at(project, 0.6).family_members_with_points()


def test_offsets_turn_with_their_layer() -> None:
    turned = square("b", 3.0).model_copy(update={"base": Transform2D(position=(3.0, 0.0), rotation=90.0)})
    project = joined(b=turned, link=connector(ends="centres", gap=0.0, target_offset=(0.0, 1.0)))
    assert ends(link_at(project))[1] == pytest.approx([2.0, 0.0])  # (0, 1) turned a quarter left


def test_a_connector_reaches_an_object_on_axes() -> None:
    axes = Layer(id="ax", spec=Spec(type="Axes"))
    point = Layer(id="p", parent_id="ax", spec=Spec(type="Point", params={"x": 2.0, "y": 1.0}))
    link = Layer(
        id="link",
        spec=Spec(type="Connector", params={"source": "a", "target": "p", "ends": "centres", "gap": 0.0}),
    )
    project = Project(canvas=CANVAS, layers=[square("a", -3.0), axes, point, link])
    expected = Evaluator(project).frame_layers(0.0)
    centre = dict(expected)["p"].get_center()[:2]
    assert ends(link_at(project))[1] == pytest.approx(centre)


def test_what_a_connector_may_join() -> None:
    trace = Layer(id="t", spec=Spec(type="TracedPath", params={"target": "a"}))
    base = [square("a", -3.0), square("b", 3.0), trace]
    for source, target, message in [
        ("a", "a", "two different layers"),
        ("a", "zz", "'zz' is missing"),
        ("a", "t", "'t' cannot be joined"),
        ("a", "link", "'link' cannot be joined"),
    ]:
        link = Layer(id="link", spec=Spec(type="Connector", params={"source": source, "target": target}))
        with pytest.raises(ValidationError, match=message):
            Project(canvas=CANVAS, layers=[*base, link])
    with pytest.raises(ValidationError, match="a connector has no clips"):
        Layer.model_validate(
            connector().model_dump() | {"clips": [{"id": "c", "kind": "FadeIn", "start": 0, "duration": 1}]}
        )
    project = joined(trace)
    assert "link" not in project.traceable_ids("t")  # a trace cannot follow a connector
    assert "link" not in [x.id for x in project.path_layers("a")]  # nor can anything travel along one
    assert adapter.allowed_clip_kinds("Connector") == []
    morph = square("a", -3.0, clips=[Clip(id="m", kind="Transform", start=0, duration=1, to_layer="link")])
    with pytest.raises(ValidationError, match="cannot morph into a connector"):
        joined(a=morph)


def test_deleting_either_layer_deletes_the_connector() -> None:
    project = joined()
    assert [x.id for x in edits.remove_layer(project, "b").project.layers] == ["a"]
    assert [x.id for x in edits.remove_layer(project, "a").project.layers] == ["b"]


def test_render_ahead_redraws_a_connector_when_a_layer_changes() -> None:
    old = joined()
    new = edits.update_layer(old, "b", base=Transform2D(position=(3.0, 2.0))).project
    assert changed_layers(old, new) >= {"b", "link"}


# -- export --------------------------------------------------------------------------------------------


def test_a_centre_connector_exports_as_always_redraw() -> None:
    export = to_python(joined(link=connector(ends="centres", tips="end", gap=0.2)), "Joined")
    assert export.readable, export.problems
    assert "link = always_redraw(lambda: Arrow(a.get_center(), b.get_center(), buff=0.2).set_z_index(2))" in (
        export.code
    )
    assert export.code.index("link = ") > export.code.index("b = ")  # after the objects it reads


@pytest.mark.parametrize(
    ("link", "a", "why"),
    [
        (connector(), None, "ending at the edges"),
        (connector(ends="centres", source_offset=(0.5, 0.0)), None, "off the centres"),
        (
            connector(ends="centres").model_copy(update={"base": Transform2D(opacity=0.5)}),
            None,
            "moved, turned, scaled or faded",
        ),
        (connector(ends="centres"), square("a", -3.0, lifetime=Lifetime(in_=0.5)), "not drawn all the time"),
    ],
)
def test_other_connectors_make_the_export_exact(link: Layer, a: Layer | None, why: str) -> None:
    problems = readable_problems(joined(link=link, a=a))
    assert any(why in p for p in problems), problems


def test_a_connector_to_a_morphing_object_is_exact() -> None:
    morph = square("a", -3.0, clips=[Clip(id="m", kind="Transform", start=0.2, duration=0.5, to_layer="c")])
    project = joined(Layer(id="c", spec=Spec(type="Circle")), a=morph, link=connector(ends="centres"))
    assert any("morphing" in p for p in readable_problems(project))


@pytest.mark.slow
def test_manim_renders_a_readable_count_and_connector_as_the_editor_does(tmp_path) -> None:
    from tests.core.engine.test_python_export import assert_matches_editor, rendered

    canvas = CANVAS.model_copy(update={"duration": 2.0})
    number = Layer(
        id="n",
        spec=Spec(type="DecimalNumber", params={"number": 0.0, "unit": r"\%"}, style={"fill": "#facc15"}),
        base=Transform2D(position=(-2.0, 2.5)),
        clips=[to_value(100.0, 0.2, 1.5)],
    )
    arriving = square(
        "b", 3.0, clips=[Clip(id="f", kind="FadeIn", start=0.0, duration=1.2, params={"shift": "UP"})]
    )
    link = connector(ends="centres", tips="end", gap=0.3)
    project = Project(canvas=canvas, layers=[square("a", -3.0), arriving, link, number])
    export = to_python(project, "Readout")
    assert export.readable, export.problems
    assert_matches_editor(project, rendered(export.code, "Readout", tmp_path))


def test_a_connector_to_a_simulation_ends_at_its_traced_point() -> None:
    from tests.core.features.test_simulated_layers import SWING

    from manim_studio import plugins

    plugins.register(SWING)
    try:
        swing = Layer(id="b", spec=Spec(type="Swing"), base=Transform2D(position=(2.0, 1.0)))
        project = joined(b=swing, link=connector(ends="centres", gap=0.0))
        x, y = 1.5 * np.sin(np.radians(60.0)), -1.5 * np.cos(np.radians(60.0))  # the bob at the start
        assert ends(link_at(project))[1] == pytest.approx([2.0 + x, 1.0 + y])
    finally:
        plugins.unregister("Swing")


def test_a_connector_listed_first_is_built_after_its_objects() -> None:
    link = connector(ends="centres")
    project = Project(canvas=CANVAS, layers=[link, square("a", -3.0), square("b", 3.0)])
    export = to_python(project, "First")
    assert export.readable
    assert export.code.index("link = ") > export.code.index("b = ")
    assert ".set_z_index(0))" in export.code  # still drawn under them


def test_a_connector_to_an_object_that_leaves_early_is_exact() -> None:
    leaving = square("b", 3.0, clips=[Clip(id="o", kind="FadeOut", start=0.2, duration=0.3)])
    problems = readable_problems(joined(b=leaving, link=connector(ends="centres")))
    assert any("not drawn all the time" in p for p in problems), problems


def test_a_signed_number_without_a_unit_exports_as_manim_takes_it() -> None:
    spec = Spec(type="DecimalNumber", params={"number": 1.0, "include_sign": "yes", "unit": ""})
    export = to_python(count(spec=spec), "Signed")
    assert "DecimalNumber(number=1.0, include_sign=True)" in export.code
