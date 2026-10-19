"""More clip kinds, clip parameters and overlay clips (P2g.1-P2g.2, ADR 0022).

The harness rule of ADR 0007 extended to parameters: every registered param is
sampled (every direction choice) and must give the same frames played in order,
scrubbed out of order, or begun fresh for each frame. Overlay clips draw the
object and the animation's own mobject together.
"""

from __future__ import annotations

import math
import random

import manim as m
import numpy as np
import pytest
from pydantic import ValidationError
from tests.support import (
    CANVAS,
    FRAMES,
    SQUARE,
    TEXT,
    TOLERANCE,
    assert_frames_equal,
    max_diff,
    render_in_order,
)

from manim_studio.core import adapter, edits
from manim_studio.core.evaluator import Evaluator
from manim_studio.core.schema import (
    CLIP_KIND_INFO,
    CLIP_PARAMS,
    DIRECTIONS,
    NUMBER_TYPES,
    Clip,
    Layer,
    PartKey,
    Project,
    Spec,
    Transform2D,
)
from manim_studio.render.cairo_export import make_camera, render_frame


def samples() -> list[tuple[str, dict]]:
    """Every registered param once, every direction and choice each once."""
    out = []
    for kind, params in CLIP_PARAMS.items():
        if CLIP_KIND_INFO[kind].category == "motion":
            continue  # needs a path layer: the two-layer harness in test_paths.py
        if CLIP_KIND_INFO[kind].category == "morph":
            continue  # needs a target layer: the two-layer harness in test_random_access.py (ADR 0056)
        if CLIP_KIND_INFO[kind].only_types == NUMBER_TYPES:
            continue  # counts a Number: the harness in test_readouts.py (ADR 0036)
        for param in params:
            if param.kind == "direction":
                values = [*DIRECTIONS, [0.5, -1.0]]
            elif param.kind == "layer":
                continue  # a path layer: the two-layer harness in test_paths.py
            elif param.kind == "choice":
                values = list(param.choices)
            elif param.kind == "color":
                values = ["#22d3ee"]
            else:
                values = [param.maximum]
            out += [(kind, {param.name: value}) for value in values]
    return out


def reference(kind: str, spec: Spec, params: dict) -> list[np.ndarray]:
    """Frames as Scene.play makes them: begin, interpolate in order."""
    camera = make_camera(CANVAS)
    mob = adapter.build_mobject(spec)
    anim = adapter.make_animation(kind, mob, None, params)
    anim.begin()
    drawn = [mob, anim.mobject] if CLIP_KIND_INFO[kind].overlay else [anim.mobject]
    frames = []
    for t in FRAMES:
        anim.interpolate(t)
        frames.append(render_frame(camera, drawn))
    return frames


@pytest.mark.parametrize(("kind", "params"), samples(), ids=lambda v: str(v))
def test_every_registered_param_keeps_frames_order_independent(kind: str, params: dict) -> None:
    clip = Clip(id="c", kind=kind, start=0.0, duration=1.0, params=params)
    project = Project(canvas=CANVAS, layers=[Layer(id="a", spec=SQUARE, clips=[clip])])
    expected = reference(kind, SQUARE, params)
    n = len(FRAMES)
    shuffled = random.Random(3).sample(range(n), n)
    assert_frames_equal(expected, render_in_order(project, shuffled, fresh_each_frame=True), "fresh")
    assert_frames_equal(expected, render_in_order(project, list(reversed(range(n))) + shuffled), "scrub")


def test_params_change_what_is_drawn() -> None:
    def centre_x(params: dict) -> float:
        clip = Clip(id="c", kind="FadeIn", start=0, duration=1, params=params)
        evaluator = Evaluator(Project(canvas=CANVAS, layers=[Layer(id="a", spec=SQUARE, clips=[clip])]))
        return float(evaluator.frame_layers(0.3)[0][1].get_center()[0])

    assert centre_x({}) == pytest.approx(0.0)
    assert centre_x({"shift": "LEFT"}) > 0.5  # moving left: it starts to the right of its place


# -- parameters: validation and conversion ------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "params", "message"),
    [
        ("FadeIn", {"shift": "NORTH"}, "shift must be a direction"),
        ("FadeIn", {"shift": [1, 2, 3, 4]}, "shift must be a direction"),
        ("Indicate", {"color": "yellow"}, "color must be a colour"),
        ("Indicate", {"scale_factor": 9}, "scale_factor must be a number from 1 to 3"),
        ("Circumscribe", {"shape": "star"}, "shape must be one of rectangle, circle"),
    ],
)
def test_registered_params_are_validated_on_load(kind, params, message) -> None:
    with pytest.raises(ValidationError, match=message):
        Clip(id="c", kind=kind, start=0, duration=1, params=params)


def test_vectors_and_unregistered_params_pass() -> None:
    Clip(id="c", kind="FadeIn", start=0, duration=1, params={"shift": [0, 1]})  # hand-written files
    Clip(id="c", kind="FadeIn", start=0, duration=1, params={"scale": 0.5})  # not registered: unverified


def test_params_become_manim_values_with_registered_defaults() -> None:
    kwargs = adapter.clip_kwargs("FadeIn", {"shift": "UP"})
    assert np.array_equal(kwargs["shift"], m.UP)
    assert np.array_equal(adapter.clip_kwargs("FadeIn", {"shift": [1, 2]})["shift"], [1, 2, 0])
    assert "shift" not in adapter.clip_kwargs("FadeIn", {})  # no default: Manim's own (no shift)
    assert np.array_equal(adapter.clip_kwargs("GrowFromEdge", {})["edge"], m.DOWN)
    indicate = adapter.clip_kwargs("Indicate", {})
    assert indicate["color"] == m.ManimColor("#FFFF00") and indicate["scale_factor"] == 1.2
    assert adapter.clip_kwargs("Circumscribe", {"shape": "circle"})["shape"] is m.Circle
    assert adapter.clip_kwargs("Write", {"lag_ratio": 0.3}) == {"lag_ratio": 0.3}  # passes through


def test_changing_the_kind_keeps_only_params_the_new_kind_registers() -> None:
    clip = Clip(id="c", kind="FadeIn", start=0, duration=1, params={"shift": "UP", "scale": 0.5})
    project = Project(canvas=CANVAS, layers=[Layer(id="a", spec=SQUARE, clips=[clip])])
    fade_out = edits.update_clip(project, "a", "c", kind="FadeOut").project
    assert fade_out.layers[0].clips[0].params == {"shift": "UP"}
    write = edits.update_clip(fade_out, "a", "c", kind="Write").project
    assert write.layers[0].clips[0].params == {}
    Evaluator(write).frame(0.5)  # still renders


# -- type restrictions ---------------------------------------------------------------------------


def test_letter_by_letter_is_for_text_and_spiral_in_for_vectors() -> None:
    assert {"AddTextLetterByLetter", "RemoveTextLetterByLetter"} <= set(adapter.allowed_clip_kinds("Text"))
    assert "AddTextLetterByLetter" not in adapter.allowed_clip_kinds("Square")
    assert "AddTextLetterByLetter" not in adapter.allowed_clip_kinds("MathTex")
    assert "SpiralIn" not in adapter.allowed_clip_kinds("ImageMobject")
    assert {"Circumscribe", "Flash", "FocusOn"} <= set(adapter.allowed_clip_kinds("ImageMobject"))
    with pytest.raises(ValidationError, match="AddTextLetterByLetter needs Text, not Square"):
        Layer(id="a", spec=SQUARE, clips=[Clip(id="c", kind="AddTextLetterByLetter", start=0, duration=1)])
    part = Layer(
        id="b",
        parent_id="eq",
        part=PartKey(tex="b"),
        clips=[Clip(id="c", kind="AddTextLetterByLetter", start=0, duration=1)],
    )
    root = Layer(id="eq", spec=Spec(type="MathTex", params={"text": "a+b"}))
    with pytest.raises(ValidationError, match="needs Text, not MathTex"):
        Project(layers=[root, part])


def test_text_letter_by_letter_matches_manim() -> None:
    for kind in ("AddTextLetterByLetter", "RemoveTextLetterByLetter"):
        clip = Clip(id="c", kind=kind, start=0, duration=1)
        project = Project(canvas=CANVAS, layers=[Layer(id="a", spec=TEXT, clips=[clip])])
        order = random.Random(5).sample(range(len(FRAMES)), len(FRAMES))
        assert_frames_equal(reference(kind, TEXT, {}), render_in_order(project, order), kind)


# -- overlays --------------------------------------------------------------------------------------


def test_an_overlay_clip_checkpoints_the_object_not_the_overlay() -> None:
    clips = [
        Clip(id="f", kind="Flash", start=0, duration=0.4),
        Clip(id="i", kind="Indicate", start=0.4, duration=0.6),
    ]
    project = Project(canvas=CANVAS, layers=[Layer(id="a", spec=SQUARE, clips=clips)])
    mob = adapter.build_mobject(SQUARE)
    anim = adapter.make_animation("Indicate", mob, None, {})
    anim.begin()
    anim.interpolate(0.5)
    camera = make_camera(CANVAS)
    diff = max_diff(render_frame(camera, Evaluator(project).frame(0.7)), render_frame(camera, [anim.mobject]))
    assert diff <= TOLERANCE


@pytest.mark.parametrize("params", [{}, {"fade_in": True, "fade_out": True}], ids=["flash", "three-parts"])
def test_circumscribe_matches_manim_played_forward(params: dict) -> None:
    """Against Manim's own Succession played in order, drawn as a scene shows it (B35)."""
    camera = make_camera(CANVAS)
    mob = adapter.build_mobject(SQUARE)
    forward = m.Circumscribe(mob, **params)
    forward.scene = None
    forward.begin()
    shown = list({id(p.mobject): p.mobject for p in forward.animations}.values())
    expected = []
    for t in FRAMES:
        forward.interpolate(t)
        expected.append(render_frame(camera, [mob, *shown]))
    plain = render_frame(camera, [adapter.build_mobject(SQUARE)])
    assert max(max_diff(frame, plain) for frame in expected) > 100  # the frame is really drawn
    clip = Clip(id="c", kind="Circumscribe", start=0, duration=1, params=params)
    project = Project(canvas=CANVAS, layers=[Layer(id="a", spec=SQUARE, clips=[clip])])
    order = list(reversed(range(len(FRAMES)))) + random.Random(9).sample(range(len(FRAMES)), len(FRAMES))
    assert_frames_equal(expected, render_in_order(project, order), "circumscribe")


def test_an_overlay_turns_with_its_layer() -> None:
    clip = Clip(id="c", kind="Circumscribe", start=0, duration=1, params={"color": "#22d3ee"})
    base = Transform2D(rotation=30.0, position=(1.0, 0.0))
    project = Project(canvas=CANVAS, layers=[Layer(id="a", spec=SQUARE, base=base, clips=[clip])])
    mob = adapter.build_mobject(SQUARE)
    anim = adapter.make_animation("Circumscribe", mob, None, {"color": "#22d3ee"})
    anim.begin()
    anim.interpolate(0.3)
    both = m.Group(mob, anim.mobject).copy()
    both.rotate(math.radians(30.0), about_point=m.ORIGIN).shift((1.0, 0, 0))
    camera = make_camera(CANVAS)
    assert (
        max_diff(render_frame(camera, Evaluator(project).frame(0.3)), render_frame(camera, [both]))
        <= TOLERANCE
    )


@pytest.mark.latex
def test_circumscribe_a_part_under_a_turned_object() -> None:
    spec = Spec(type="MathTex", params={"text": r"a^2 + b^2 = c^2"})
    clip = Clip(id="c", kind="Circumscribe", start=0, duration=1)
    root = Layer(id="eq", spec=spec, base=Transform2D(rotation=20.0, scale=1.2))
    b = Layer(id="b", parent_id="eq", part=PartKey(tex="b^2"), clips=[clip])
    evaluator = Evaluator(Project(canvas=CANVAS, layers=[root, b]))
    eq = adapter.build_mobject(spec)
    leaves = eq.family_members_with_points()
    anim = adapter.make_animation("Circumscribe", m.VGroup(leaves[3], leaves[4]), None, {})
    anim.begin()
    anim.interpolate(0.4)
    both = m.Group(eq, anim.mobject).copy()
    both.scale(1.2, about_point=m.ORIGIN).rotate(math.radians(20.0), about_point=m.ORIGIN)
    camera = make_camera(CANVAS)
    assert max_diff(render_frame(camera, evaluator.frame(0.4)), render_frame(camera, [both])) <= TOLERANCE


@pytest.mark.latex
def test_an_overlay_on_an_object_whose_glyphs_all_belong_to_parts_is_drawn() -> None:
    spec = Spec(type="MathTex", params={"text": "ab"})
    root = Layer(id="eq", spec=spec, clips=[Clip(id="c", kind="Circumscribe", start=0, duration=1)])
    parts = [Layer(id=x, parent_id="eq", part=PartKey(tex=x)) for x in "ab"]
    layers = Evaluator(Project(canvas=CANVAS, layers=[root, *parts])).frame_layers(0.4)
    assert [layer_id for layer_id, _ in layers] == ["eq", "a", "b"]  # the root draws the frame


def test_new_morph_kinds_hand_off_like_transform() -> None:
    circle = Spec(type="Circle", params={"radius": 1.5})
    for kind in ("ClockwiseTransform", "CounterclockwiseTransform", "FadeTransformPieces"):
        layers = [
            Layer(id="a", spec=SQUARE, clips=[Clip(id="m", kind=kind, start=0, duration=1, to_layer="b")]),
            Layer(id="b", spec=circle),
        ]
        evaluator = Evaluator(Project(canvas=CANVAS, layers=layers))
        assert [i for i, _ in evaluator.frame_layers(0.5)] == ["a"]
        assert [i for i, _ in evaluator.frame_layers(1.0)] == ["b"]


def test_add_clip_takes_params() -> None:
    project = Project(canvas=CANVAS, layers=[Layer(id="a", spec=SQUARE)])
    edit = edits.add_clip(project, "a", "Flash", 0.0, 0.5, params={"color": "#fde047"})
    assert edit.project.layers[0].clips[0].params == {"color": "#fde047"}
    with pytest.raises(ValidationError, match="color must be a colour"):
        edits.add_clip(project, "a", "Flash", 0.0, 0.5, params={"color": "gold"})
