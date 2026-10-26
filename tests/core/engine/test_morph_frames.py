"""Smart morph matching through the evaluator (ADR 0056, B73).

Classic stays Manim's own Transform, bit for bit; smart draws both ends exactly, is a pure
function of (project, t) and beats classic on the gallery's measures.
"""

from __future__ import annotations

import random

import manim as m
import numpy as np
import pytest
from pydantic import ValidationError

from manim_studio.core.engine import adapter, morph, python_export
from manim_studio.core.engine.evaluator import Evaluator
from manim_studio.core.model.schema import (
    CLIP_PARAMS,
    SMART_MORPH,
    SMART_MORPHS,
    Canvas,
    Clip,
    Easing,
    Layer,
    Project,
    Spec,
    Transform2D,
    new_clip_params,
)
from manim_studio.render.cairo_export import make_camera, render_frame

CANVAS = Canvas(width_px=320, height_px=180, fps=10, duration=2.5, background="#101418")
START, LENGTH = 0.5, 1.0
BLUE = {"fill": "#3b82f6", "fill_opacity": 0.8, "stroke": "#93c5fd", "stroke_width": 4}
RED = {"fill": "#ef4444", "fill_opacity": 0.8, "stroke": "#fca5a5", "stroke_width": 4}
OUTLINE = {"fill_opacity": 0.0, "stroke": "#f97316", "stroke_width": 8}
WHITE = {"fill": "#ffffff", "fill_opacity": 1.0}


def spec(type_name: str, style: dict | None = None, **params) -> Spec:
    return Spec(type=type_name, params=params, style=style or {})


# (name, source, target, target rotation): a subset of the B73 gallery that needs no LaTeX.
PAIRS = {
    "circle-square": (spec("Circle", BLUE, radius=1.2), spec("Square", RED, side_length=2.2), 0.0),
    "square-square90": (spec("Square", BLUE, side_length=2.0), spec("Square", RED, side_length=2.0), 90.0),
    "star-square": (spec("Star", RED, n=7, outer_radius=1.4), spec("Square", BLUE, side_length=2.0), 0.0),
    "line-arrow": (spec("Line", OUTLINE, start=(-1, -1), end=(1, 1)), spec("Arrow", OUTLINE), 0.0),
    "filled-outline": (spec("Circle", BLUE, radius=1.2), spec("Square", OUTLINE, side_length=2.0), 0.0),
    "Hello-World": (spec("Text", WHITE, text="Hello"), spec("Text", WHITE, text="World"), 0.0),
    "cat-elephant": (spec("Text", WHITE, text="cat"), spec("Text", WHITE, text="elephant"), 0.0),
    "oe-eo": (
        spec("Text", WHITE, text="oe", font_size=96),
        spec("Text", WHITE, text="eo", font_size=96),
        0.0,
    ),
    "o-square": (spec("Text", WHITE, text="o", font_size=144), spec("Square", RED, side_length=1.5), 0.0),
    "group-square": (
        spec("RightTriangle", BLUE, angle=40.0, side_length=2.5),
        spec("Square", RED, side_length=2.0),
        0.0,
    ),
}


def project(name: str, params: dict, kind: str = "Transform", start: float = START) -> Project:
    source, target, turn = PAIRS[name]
    clip = Clip(
        id="m",
        kind=kind,
        start=start,
        duration=LENGTH,
        to_layer="b",
        ease=Easing(name="linear"),
        params=params,
    )
    return Project(
        canvas=CANVAS,
        layers=[
            Layer(id="a", spec=source, base=Transform2D(position=(-2.0, 0.0)), clips=[clip]),
            Layer(id="b", spec=target, base=Transform2D(position=(2.0, 0.0), rotation=turn)),
        ],
    )


def morph_at(evaluator: Evaluator, proj: Project, alpha: float) -> m.Mobject:
    layer = proj.layers[0]
    return evaluator._morph_at(layer, 0, layer.clips[0], alpha)


SMART = {"match": "smart"}


# -- the parameter ---------------------------------------------------------------------------------


def test_matching_is_a_choice_of_the_plain_morphs_only() -> None:
    for kind in ("Transform", "ClockwiseTransform", "CounterclockwiseTransform"):
        (param,) = CLIP_PARAMS[kind]
        assert (param.name, param.default, param.choices, param.studio) == (
            "match",
            "classic",
            ("classic", "smart"),
            True,
        )
        assert "Smart" in param.tooltip and "Classic" in param.tooltip
    assert "match" not in str(CLIP_PARAMS.get("TransformMatchingTex", ()))
    with pytest.raises(ValidationError, match="match must be one of classic, smart"):
        Clip(id="m", kind="Transform", start=0, duration=1, to_layer="b", params={"match": "fancy"})
    assert adapter.clip_kwargs("Transform", SMART) == {}  # never reaches Manim
    assert new_clip_params("Transform") == SMART and new_clip_params("FadeTransform") == {}


# -- classic: Manim's own Transform, unchanged -----------------------------------------------------


def world(spec_: Spec, at: tuple[float, float], turn: float = 0.0) -> m.Mobject:
    mob = adapter.build_mobject(spec_).copy()
    if turn:
        mob.rotate(np.radians(turn), about_point=mob.get_center())
    return mob.shift([at[0], at[1], 0.0])


@pytest.mark.parametrize("params", [{}, {"match": "classic"}], ids=str)
@pytest.mark.parametrize(
    ("name", "kind"), [(n, "Transform") for n in PAIRS] + [("circle-square", "ClockwiseTransform")]
)
def test_classic_draws_exactly_what_manims_transform_draws(name: str, kind: str, params: dict) -> None:
    """A copy of the path every project took before ADR 0056: Manim's class on the world-space ends."""
    source, target, turn = PAIRS[name]
    if turn:
        pytest.skip("a turned target is placed by the evaluator's affine, not by rotate()")
    old = {"Transform": m.ReplacementTransform, "ClockwiseTransform": m.ClockwiseTransform}[kind]
    anim = old(world(source, (-2.0, 0.0)), world(target, (2.0, 0.0)), rate_func=m.linear)
    anim.begin()
    camera = make_camera(CANVAS)
    proj = project(name, params, kind, start=0.0)
    evaluator = Evaluator(proj)
    for t in (0.0, 0.3, 0.5, 0.9):
        anim.interpolate(t)
        expected = render_frame(camera, [anim.mobject])
        assert np.array_equal(render_frame(camera, evaluator.frame(t)), expected), (name, t)


# -- smart: exact ends, random access --------------------------------------------------------------


@pytest.mark.parametrize("name", list(PAIRS))
def test_smart_morphs_start_and_end_exactly_on_their_objects(name: str) -> None:
    proj = project(name, SMART)
    evaluator, camera = Evaluator(proj), make_camera(CANVAS)
    before = render_frame(camera, evaluator.frame(START / 2))  # the source alone
    after = render_frame(camera, evaluator.frame(START + LENGTH + 0.2))  # the target alone
    assert np.array_equal(render_frame(camera, evaluator.frame(START)), before)  # alpha 0
    assert np.array_equal(render_frame(camera, [morph_at(evaluator, proj, 1.0)]), after)
    assert np.array_equal(render_frame(camera, [morph_at(evaluator, proj, 0.0)]), before)


@pytest.mark.parametrize("name", ["circle-square", "Hello-World", "group-square", "o-square"])
def test_smart_frames_do_not_depend_on_the_order_they_are_asked_in(name: str) -> None:
    proj = project(name, SMART | {"lag_ratio": 0.0})
    times = [START + LENGTH * i / 8 for i in range(9)]
    camera = make_camera(CANVAS)
    forward = Evaluator(proj)
    expected = [render_frame(camera, forward.frame(t)) for t in times]
    scrub = Evaluator(proj)
    order = [*reversed(range(len(times))), *random.Random(5).sample(range(len(times)), len(times))]
    for i in order:
        assert np.array_equal(render_frame(camera, scrub.frame(times[i])), expected[i]), (name, i)
    for i in (3, 7):
        assert np.array_equal(render_frame(camera, Evaluator(proj).frame(times[i])), expected[i])


# -- smart: better in-between frames (the B73 measures) ---------------------------------------------


def snapshot(mob: m.Mobject) -> np.ndarray:
    return np.concatenate([leaf.points[:, :2] for leaf in mob.family_members_with_points()])


def measures(name: str, params: dict) -> dict:
    proj = project(name, params)
    evaluator = Evaluator(proj)
    first = snapshot(morph_at(evaluator, proj, 1e-9))
    last = snapshot(morph_at(evaluator, proj, 1 - 1e-9))
    size = np.mean([np.linalg.norm(np.ptp(p, axis=0)) for p in (first, last)])
    shift = (last.min(0) + last.max(0)) / 2 - (first.min(0) + first.max(0)) / 2
    travel = float(np.mean(np.linalg.norm(last - first - shift, axis=1)) / size)

    def outlines(alpha):
        mob = morph_at(evaluator, proj, alpha)
        for leaf in mob.family_members_with_points():
            for sub in morph.subpaths(leaf.points):
                yield leaf, morph.sample_subpath(sub[:, :2])

    def crossings(alpha):
        return sum(morph.self_crossings(poly) for _, poly in outlines(alpha))

    def area(alpha):
        by_leaf: dict[int, float] = {}
        for leaf, poly in outlines(alpha):
            if leaf.get_fill_opacity() > 0:
                by_leaf[id(leaf)] = by_leaf.get(id(leaf), 0.0) + morph.signed_area(poly)
        return sum(abs(v) for v in by_leaf.values())

    ends = max(crossings(0.0), crossings(1.0))
    a0, a1 = area(0.0), area(1.0)
    dip = (
        min((area(x) / (a0 + (a1 - a0) * x) for x in (0.25, 0.5, 0.75)), default=1.0) if max(a0, a1) else 1.0
    )
    return {
        "travel": travel,
        "cross": sum(max(0, crossings(x) - ends) for x in (0.25, 0.5, 0.75)),
        "dip": dip,
    }


def test_smart_beats_classic_on_the_gallery() -> None:
    classic = {name: measures(name, {}) for name in PAIRS}
    smart = {name: measures(name, SMART) for name in PAIRS}
    # Twisting: points travel needlessly around the outline (B73: 0.37 -> 0.12 on these pairs).
    assert np.mean([s["travel"] for s in smart.values()]) < 0.6 * np.mean(
        [c["travel"] for c in classic.values()]
    )
    assert (
        sum(s["travel"] <= c["travel"] + 0.01 for s, c in zip(smart.values(), classic.values(), strict=True))
        >= 9
    )
    # Tangled glyph outlines in the in-between frames (B73: 130 -> 26 here).
    assert sum(s["cross"] for s in smart.values()) <= 0.35 * sum(c["cross"] for c in classic.values())
    # The same square turned: classic spins it through a smaller diamond, smart leaves it be.
    assert classic["square-square90"]["travel"] > 0.5 and smart["square-square90"]["travel"] < 1e-9
    assert classic["square-square90"]["dip"] < 0.6 and smart["square-square90"]["dip"] > 0.999
    # The hole of an "o" closes in the middle instead of flying out of the square.
    assert classic["o-square"]["dip"] < 0.2 and smart["o-square"]["dip"] > 0.9
    # A group's small marks shrink away instead of growing into whole squares.
    assert classic["group-square"]["travel"] > 3 * smart["group-square"]["travel"]


def test_smart_blends_colour_without_muddying_and_keeps_ends() -> None:
    proj = project("circle-square", SMART)
    evaluator = Evaluator(proj)
    leaf = lambda a: morph_at(evaluator, proj, a).family_members_with_points()[0]  # noqa: E731
    blue, red = leaf(0.0).fill_rgbas.copy(), leaf(1.0).fill_rgbas.copy()
    middle = leaf(0.5).fill_rgbas.copy()
    lab = morph.srgb_to_oklab(np.vstack([blue[:, :3], red[:, :3], middle[:, :3]]))
    assert lab[2, 0] == pytest.approx((lab[0, 0] + lab[1, 0]) / 2, abs=1e-6)
    assert np.array_equal(blue, adapter.build_mobject(PAIRS["circle-square"][0]).fill_rgbas)
    widths = [leaf(a).stroke_width for a in (0.0, 0.5, 1.0)]
    assert widths == [4, 4, 4]


def test_pieces_without_partner_fade_and_an_overshooting_ease_holds_widths() -> None:
    triangle = adapter.build_mobject(PAIRS["group-square"][0])  # a polygon and two marks
    square = adapter.build_mobject(spec("Square", {**RED, "stroke_width": 8}))
    starts, ends, exact = adapter.smart_pair(triangle, square)
    lone = [i for i, (first, last) in enumerate(exact) if last is None]
    assert len(lone) == 2  # the marks
    for i in lone:
        assert not ends[i].stroke_rgbas[:, 3].any() and not ends[i].fill_rgbas[:, 3].any()
        assert starts[i].stroke_rgbas[:, 3].all()
    back = Easing(bezier=(0.34, 1.56, 0.64, 1.0), name=None)  # overshoots past 1
    anim = adapter.make_animation("Transform", triangle, back, SMART, square)
    anim.begin()
    widths = set()
    for t in np.linspace(0, 1, 21):
        anim.interpolate(t)
        widths |= {leaf.stroke_width for leaf in anim.mobject.family_members_with_points()}
    assert min(widths) >= 4 and max(widths) <= 8


def test_a_smart_morph_falls_back_to_classic_on_an_image() -> None:
    source = adapter.build_mobject(PAIRS["circle-square"][0])
    image = m.ImageMobject(np.zeros((4, 4, 4), dtype=np.uint8))
    assert adapter.smart_pair(source, m.Group(image)) is None
    anim = adapter.make_animation("Transform", source, None, SMART, m.Group(image))
    assert type(anim) is m.ReplacementTransform


@pytest.mark.latex
def test_a_smart_equation_morph_keeps_its_ends_and_scrubs() -> None:
    PAIRS["tex"] = (
        spec("MathTex", WHITE, text="a^2 + b^2 = c^2"),
        spec("MathTex", WHITE, text=r"e^{i\pi}+1=0"),
        0.0,
    )
    try:
        test_smart_morphs_start_and_end_exactly_on_their_objects("tex")
        test_smart_frames_do_not_depend_on_the_order_they_are_asked_in("tex")
        smart, classic = measures("tex", SMART), measures("tex", {})
        assert smart["cross"] < classic["cross"]
    finally:
        del PAIRS["tex"]


# -- export ----------------------------------------------------------------------------------------


@pytest.mark.slow
def test_the_exact_export_of_a_smart_morph_renders_what_the_editor_shows(tmp_path) -> None:
    from tests.core.engine.test_python_export import assert_matches_editor, rendered

    proj = project("o-square", SMART)  # on black: h264 shifts a grey background by a level (B43)
    proj = proj.model_copy(update={"canvas": CANVAS.model_copy(update={"background": "#000000"})})
    export = python_export.to_python(proj, "Smart")
    assert not export.readable and f"#   - a: {SMART_MORPH}" in export.code
    assert_matches_editor(proj, rendered(export.code, "Smart", tmp_path))


def test_a_smart_morph_exports_in_the_exact_form_and_classic_stays_readable() -> None:
    smart = project("circle-square", SMART)
    assert python_export.readable_problems(smart) == [f"a: {SMART_MORPH}"]
    assert not python_export.to_python(smart, "Smart").readable
    for params in ({}, {"match": "classic"}):
        export = python_export.to_python(project("circle-square", params), "Classic")
        assert export.readable and "match" not in export.code
        assert "ReplacementTransform(" in export.code
    assert {"Transform", "ClockwiseTransform", "CounterclockwiseTransform"} == SMART_MORPHS
