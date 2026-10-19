"""Importing a Manim scene (P10.3, ADR 0053): a recording becomes layers, clips and keys, or one
code layer when anything in it cannot be reproduced exactly.

The oracle: each scene is recorded in this process with ``sample_fps`` - every frame Manim would
draw, as pixels - and the imported project's frames, drawn by the editor's own export renderer at
the same times, must show the same pixels.
"""

from __future__ import annotations

import copy
import textwrap
from pathlib import Path

import numpy as np
import pytest

from manim_studio.core import scene_import
from manim_studio.core.evaluator import Evaluator
from manim_studio.core.python_export import to_python
from manim_studio.core.scene_import import import_scene, scene_classes, scene_code
from manim_studio.core.schema import Canvas, Clip, Layer, Project, Spec, Transform2D
from manim_studio.render.cairo_export import make_camera, render_frame
from manim_studio.scene_recorder import record

SMALL = "config.pixel_width = 192\nconfig.pixel_height = 108\nconfig.frame_rate = 10\n"


def recorded(tmp_path: Path, construct: str, header: str = "", name: str = "Demo") -> tuple[dict, str]:
    source = (
        "from manim import *\n"
        + SMALL
        + textwrap.dedent(header)
        + f"\n\nclass {name}(Scene):\n    def construct(self):\n"
        + textwrap.indent(textwrap.dedent(construct), " " * 8)
    )
    path = tmp_path / "scene.py"
    path.write_text(source, encoding="utf-8")
    return record(source, str(path), name, sample_fps=10), source


def imported(tmp_path: Path, construct: str, header: str = "") -> tuple[dict, scene_import.ImportResult]:
    rec, source = recorded(tmp_path, construct, header)
    return rec, import_scene(rec, source)


def assert_frames_match(rec: dict, project: Project, worst: float = 0.5) -> None:
    """Every frame Manim drew (the recording's samples) is what the editor draws at that time."""
    evaluator, camera = Evaluator(project), make_camera(project.canvas)
    assert rec["samples"]
    for sample in rec["samples"]:
        ours = render_frame(camera, evaluator.frame(sample["t"]))[:, :, :3].astype(int)
        theirs = sample["pixels"][:, :, :3].astype(int)
        assert np.abs(ours - theirs).mean() < worst, sample["t"]


def layers(result) -> dict[str, Layer]:
    return {x.id: x for x in result.project.layers}


# -- what converts --------------------------------------------------------------------------------------


def test_a_plain_scene_becomes_built_in_objects_with_clips_keys_and_a_morph(tmp_path) -> None:
    rec, result = imported(
        tmp_path,
        """
        circle = Circle(radius=1.5, color=BLUE)
        square = Square(side_length=2).shift(RIGHT * 3)
        title = Text("Hi", font_size=60).to_edge(UP)
        self.play(Create(circle))
        self.play(FadeIn(square, shift=UP), Write(title))
        self.wait(0.5)
        self.play(circle.animate.shift(LEFT * 2).scale(0.5))
        self.play(Transform(square, Star(color=YELLOW).shift(RIGHT * 3)))
        self.play(Indicate(title))
        self.play(FadeOut(circle))
        self.wait()
        """,
    )
    assert result.converted, result.report
    by_id = layers(result)
    assert [x.spec.type for x in result.project.layers] == ["Circle", "Square", "Star", "Text"]
    circle = by_id["circle-1"]
    assert circle.name == "circle" and circle.spec.params == {"radius": 1.5}
    assert [(c.kind, c.start, c.duration) for c in circle.clips] == [
        ("Create", 0.0, 1.0),
        ("FadeOut", 5.5, 1.0),
    ]
    assert [k.t for k in circle.tracks["position"]] == [2.5, 3.5]
    assert [k.value for k in circle.tracks["scale"]] == [1.0, 0.5]
    assert circle.tracks["scale"][0].ease.name == "smooth"
    square = by_id["square-1"]
    assert square.clips[0].params == {"shift": "UP"} and square.base.position == (3.0, 0.0)
    assert square.clips[1].kind == "Transform" and square.clips[1].to_layer == "star-1"
    assert "match" not in square.clips[1].params  # replays Manim's own Transform: classic (ADR 0056)
    assert by_id["text-1"].spec.params["text"] == "Hi"
    assert result.counts == {"layers": 4, "builtin": 4, "shapes": 0, "clips": 6, "moves": 1}
    assert result.project.canvas.duration == pytest.approx(7.5)
    assert result.project.canvas.fps == 10 and result.project.canvas.width_px == 192
    assert_frames_match(rec, result.project)


def test_members_of_a_group_animated_on_their_own_become_layers(tmp_path) -> None:
    rec, result = imported(
        tmp_path,
        """
        a = Square(side_length=1).shift(LEFT * 2)
        b = Circle(radius=0.5)
        c = Triangle().shift(RIGHT * 2)
        g = VGroup(a, b, c)
        self.play(Create(g))
        self.play(b.animate.shift(UP), rate_func=linear)
        self.play(g.animate.shift(DOWN).scale(0.8))
        self.play(Rotate(a, PI / 4))
        self.play(FadeOut(c, shift=RIGHT))
        c.shift(UP * 3)
        self.add(c)
        self.wait(0.5)
        self.play(TransformFromCopy(a, Dot(UP * 2, color=RED)))
        self.play(ReplacementTransform(b, Square(side_length=0.4, color=GREEN)))
        self.play(a.animate.fade(0.6))
        self.play(ShrinkToCenter(c))
        self.wait(0.5)
        """,
    )
    assert result.converted, result.report
    by_id = layers(result)
    creates = sorted((c.start, c.duration) for x in by_id.values() for c in x.clips if c.kind == "Create")
    assert np.allclose(creates, [(0.0, 1 / 3), (1 / 3, 1 / 3), (2 / 3, 1 / 3)])  # split as in the whole
    assert all(c.params["lag_ratio"] == 1.0 for x in by_id.values() for c in x.clips if c.kind == "Create")
    a = next(x for x in by_id.values() if x.name == "a" and x.spec.type == "Square" and x.clips)
    assert [k.value for k in a.tracks["rotation"]] == [0.0, 45.0]
    assert [k.value for k in a.tracks["opacity"]] == [1.0, pytest.approx(0.4)]
    triangles = [x for x in by_id.values() if x.spec.type == "Triangle"]
    assert len(triangles) == 2  # moved by code after its FadeOut, added again: a new layer
    assert triangles[1].lifetime.in_ == pytest.approx(5.0) and triangles[1].clips[0].kind == "ShrinkToCenter"
    copy_layer = next(x for x in by_id.values() if x.lifetime.in_ == pytest.approx(5.5))
    assert copy_layer.clips[0].kind == "Transform" and by_id[copy_layer.clips[0].to_layer].spec.type == "Dot"
    assert_frames_match(rec, result.project)


def test_a_lagged_start_and_arrange_become_clips_and_keys_per_member(tmp_path) -> None:
    rec, result = imported(
        tmp_path,
        """
        dots = VGroup(*[Dot(RIGHT * i) for i in range(-2, 3)])
        self.play(LaggedStart(*[GrowFromCenter(d) for d in dots], lag_ratio=0.5))
        self.play(Indicate(dots[2]))
        self.play(dots.animate.arrange(DOWN))
        self.wait()
        """,
    )
    assert result.converted, result.report
    starts = [x.clips[0].start for x in result.project.layers]
    assert starts == pytest.approx([0.0, 0.5, 1.0, 1.5, 2.0])
    moved = ["position" in x.tracks for x in result.project.layers]
    assert moved == [True, True, False, True, True]  # the middle dot is where arrange puts it
    assert_frames_match(rec, result.project)


@pytest.mark.latex
def test_equations_stay_editable_math_and_the_report_says_they_need_latex(tmp_path) -> None:
    rec, result = imported(
        tmp_path,
        r"""
        eq = MathTex("a^2 + b^2 = c^2")
        self.play(Write(eq))
        self.play(eq.animate.to_edge(UP))
        other = MathTex(r"e^{i\pi} + 1 = 0").next_to(eq, DOWN)
        self.play(FadeIn(other, shift=DOWN))
        self.play(Transform(eq, other.copy().shift(DOWN * 2)))
        self.wait()
        """,
    )
    assert result.converted, result.report
    assert [x.spec.type for x in result.project.layers] == ["MathTex"] * 3
    assert result.project.layers[0].spec.params["text"] == "a^2 + b^2 = c^2"
    assert any("LaTeX" in line for line in result.report)
    assert_frames_match(rec, result.project)


def test_code_that_changes_an_object_between_plays_starts_a_new_layer(tmp_path) -> None:
    rec, result = imported(
        tmp_path,
        """
        dot = Dot(color=RED)
        self.add(dot)
        self.wait()
        dot.set_color(BLUE).shift(RIGHT)
        self.wait()
        self.remove(dot)
        self.wait()
        """,
    )
    assert result.converted, result.report
    first, second = result.project.layers
    assert (first.lifetime.in_, first.lifetime.out) == (None, 1.0)
    assert (second.lifetime.in_, second.lifetime.out) == (1.0, 2.0)
    assert first.spec.style["fill"] != second.spec.style["fill"]
    assert_frames_match(rec, result.project)


def test_entrances_emphases_overlays_and_exits_play_as_in_manim(tmp_path) -> None:
    rec, result = imported(
        tmp_path,
        """
        s = Square(color=BLUE).shift(LEFT * 3)
        c = Circle(color=RED, fill_opacity=0.5)
        t = Text("abc").shift(UP * 2.5)
        self.play(DrawBorderThenFill(s), GrowFromEdge(c, DOWN), AddTextLetterByLetter(t))
        self.play(Circumscribe(s), Flash(c))
        self.play(Wiggle(c), SpinInFromNothing(Star().shift(RIGHT * 3)))
        self.play(Succession(Indicate(s), s.animate.shift(DOWN)))
        self.play(ClockwiseTransform(c, Square(side_length=1).shift(RIGHT)))
        self.play(Uncreate(s), Unwrite(t))
        self.wait(0.5)
        """,
    )
    assert result.converted, result.report
    kinds = {c.kind for x in result.project.layers for c in x.clips}
    assert {
        "DrawBorderThenFill",
        "GrowFromEdge",
        "AddTextLetterByLetter",
        "Circumscribe",
        "Flash",
        "Wiggle",
    } <= kinds
    squares = [x for x in result.project.layers if x.name == "s"]
    assert len(squares) == 2  # the Succession adds the square again, in front: a new layer from then on
    assert squares[1].lifetime.in_ == pytest.approx(5.0)
    assert_frames_match(rec, result.project)


def test_matching_and_fading_morphs_and_z_index_play_as_in_manim(tmp_path) -> None:
    rec, result = imported(
        tmp_path,
        """
        a = Text("one")
        b = Text("noe").shift(DOWN)
        self.add(a)
        self.play(TransformMatchingShapes(a, b))
        c = Circle().shift(UP * 2)
        self.play(FadeTransform(b, c))
        d = Square().set_z_index(-1)
        self.add(d)
        self.wait()
        self.play(GrowFromCenter(Triangle().scale(2)))
        self.wait()
        """,
    )
    assert result.converted, result.report
    triangle = next(x for x in result.project.layers if x.spec.type == "Triangle")
    assert triangle.base.scale == pytest.approx(2.0)  # a built-in with its scale: GrowFromCenter suits it
    assert_frames_match(rec, result.project)


def test_an_ease_given_to_play_is_the_clips_ease(tmp_path) -> None:
    rec, result = imported(tmp_path, "self.play(FadeIn(Square()), rate_func=rush_into)\nself.wait(0.5)")
    assert result.converted, result.report
    assert result.project.layers[0].clips[0].ease.name == "rush_into"
    assert_frames_match(rec, result.project)


def test_an_object_made_more_opaque_than_it_began_is_refused(tmp_path) -> None:
    _, result = imported(
        tmp_path, "d = Dot().set_opacity(0.5)\nself.add(d)\nself.play(d.animate.set_opacity(1))"
    )
    assert not result.converted and "more opaque" in result.reasons[0]


@pytest.mark.latex
def test_a_morph_between_equations_split_into_pieces_is_refused(tmp_path) -> None:
    _, result = imported(
        tmp_path,
        """
        eq = MathTex("a^2", "+", "b^2", "=", "c^2")
        self.add(eq)
        self.play(Transform(eq, MathTex("a^2 + b^2 = c^2").shift(DOWN)))
        """,
    )
    assert not result.converted  # its pieces pair otherwise than one string's would
    assert "sub-objects" in result.reasons[0] and "nested group" in result.reasons[0]


def test_a_clip_the_editor_plays_differently_keeps_the_scene_as_code(tmp_path) -> None:
    _, result = imported(tmp_path, "t = Text('x')\nself.add(t)\nself.play(FocusOn(t))")
    assert not result.converted and "FocusOn" in result.reasons[0]


def test_objects_that_no_built_in_rebuilds_are_exact_shapes(tmp_path) -> None:
    rec, result = imported(
        tmp_path,
        """
        arc = Arc(radius=2, angle=PI, color=GREEN)
        both = VGroup(Square(), Circle()).arrange(RIGHT)
        self.play(Create(arc), FadeIn(both))
        self.play(both.animate.shift(DOWN))
        """,
    )
    assert result.converted, result.report
    assert [x.spec.type for x in result.project.layers] == ["Shape", "Shape"]
    arc = result.project.layers[0]
    points = np.vstack([np.asarray(p["points"]) for p in arc.spec.params["shapes"]])
    assert np.allclose((points.min(axis=0) + points.max(axis=0)) / 2, 0.0)  # centred, placed by its base
    assert_frames_match(rec, result.project)


# -- what does not: the whole scene is one code layer ------------------------------------------------------


def test_updaters_keep_the_whole_scene_as_one_code_layer_with_the_reason(tmp_path) -> None:
    _, result = imported(
        tmp_path,
        """
        dot = Dot()
        label = always_redraw(lambda: Text("x").next_to(dot, UP))
        self.add(dot, label)
        self.play(dot.animate.shift(RIGHT))
        """,
        header="\n\nclass Other(Scene):\n    def construct(self):\n        pass\n",
    )
    assert not result.converted
    (layer,) = result.project.layers
    assert layer.spec.type == "Code" and "class Demo(Scene)" in layer.spec.params["code"]
    assert "class Other" not in layer.spec.params["code"]  # a code layer holds one scene
    assert any("updaters" in why and "line" in why for why in result.reasons)
    assert result.project.canvas.duration == pytest.approx(1.0)


def test_a_change_keys_cannot_redo_is_refused_not_approximated(tmp_path) -> None:
    _, result = imported(tmp_path, "c = Circle()\nself.add(c)\nself.play(c.animate.set_opacity(0.5))")
    assert not result.converted  # set_opacity fills an unfilled circle: not a fade of what it draws
    assert "not a move, a uniform scale or a fade" in result.reasons[0]
    _, result = imported(tmp_path, "s = Square()\nself.add(s)\nself.play(s.animate.rotate(PI / 3))")
    assert not result.converted  # .animate cuts a turn as a chord


def test_a_clip_on_a_scaled_object_that_would_be_scaled_with_it_is_refused(tmp_path) -> None:
    _, result = imported(
        tmp_path,
        "s = Square()\nself.add(s)\nself.play(s.animate.scale(2))\nself.play(Circumscribe(s))",
    )
    assert not result.converted and "Circumscribe would be scaled" in result.reasons[0]


def test_two_animations_of_one_object_at_once_are_refused(tmp_path) -> None:
    _, result = imported(tmp_path, "s = Square()\nself.add(s)\nself.play(Indicate(s), s.animate.shift(UP))")
    assert not result.converted


# -- hand-built recordings: the rules without Manim --------------------------------------------------------


def piece(x: float, alpha: float = 1.0) -> dict:
    return {
        "points": [[x, 0.0], [x + 1, 0.0], [x + 1, 1.0], [x, 1.0]],
        "fill": [1.0, 0.0, 0.0, alpha],
        "stroke": [1.0, 1.0, 1.0, alpha],
        "stroke_width": 4.0,
    }


def base_recording(steps: list[dict], states: dict, problems=()) -> dict:
    return {
        "version": 1,
        "file": "demo.py",
        "scene": "Demo",
        "canvas": {"width_px": 160, "height_px": 90, "fps": 10, "background": "#000000", "frame_height": 8.0},
        "duration": 3.0,
        "states": states,
        "objects": {"o1": {"class": "VMobject", "line": 4, "name": "box"}},
        "candidates": [],
        "steps": steps,
        "problems": list(problems),
        "notes": [],
    }


def fade_in(t: float, state: str, end_state: str | None = None) -> dict:
    return {
        "type": "play",
        "t": t,
        "duration": 1.0,
        "line": 5,
        "animations": [
            {
                "class": "FadeIn",
                "kind": "FadeIn",
                "start": 0.0,
                "duration": 1.0,
                "begin": 0.0,
                "line": 5,
                "problems": [],
                "target": "o1",
                "params": {},
                "ease": None,
                "lag_ratio": 0.0,
                "leafwise": True,
                "at_begin": [["p1", state]],
                "at_finish": [["p1", end_state or state]],
                "flat": True,
                "finish_flat": True,
            }
        ],
        "before": [],
        "during": ["p1"],
        "after": [["p1", end_state or state]],
    }


def test_a_recorded_fade_in_becomes_a_centred_shape_with_its_clip() -> None:
    rec = base_recording([fade_in(1.0, "s1")], {"s1": piece(2.0)})
    result = import_scene(rec, "")
    assert result.converted, result.report
    (layer,) = result.project.layers
    assert layer.spec.type == "Shape" and layer.base.position == (2.5, 0.5)
    assert layer.spec.params["shapes"][0]["points"][0] == [-0.5, -0.5]
    assert [(c.kind, c.start, c.duration) for c in layer.clips] == [("FadeIn", 1.0, 1.0)]
    assert layer.lifetime.in_ is None  # the introducer brings it in at 1 s
    assert layer.name == "box" and result.project.subtitle_style.burn_in is False


def test_a_verified_built_in_candidate_is_used_for_the_same_pieces() -> None:
    rec = base_recording([fade_in(0.0, "s1")], {"s1": piece(0.0)})
    rec["candidates"] = [
        {
            "leaves": [["p1", "s1"]],
            "spec": {"type": "Square", "params": {"side_length": 1.0}, "style": {}},
            "base": {"position": [0.5, 0.5], "rotation": 0.0, "scale": 1.0},
            "structure": True,
        }
    ]
    (layer,) = import_scene(rec, "").project.layers
    assert layer.spec.type == "Square" and layer.base.position == (0.5, 0.5)


def test_an_animation_that_does_not_end_as_its_clip_leaves_it_falls_back() -> None:
    source = "from manim import *\n\nclass Demo(Scene):\n    def construct(self):\n        pass\n"
    rec = base_recording([fade_in(0.0, "s1", end_state="s2")], {"s1": piece(0.0), "s2": piece(3.0)})
    result = import_scene(rec, source)
    assert not result.converted and "does not end as its clips leave it" in result.reasons[0]
    assert result.reasons[0].startswith("line 5")


def test_recorded_problems_make_a_code_layer_without_trying() -> None:
    source = "from manim import *\n\nclass Demo(Scene):\n    def construct(self):\n        pass\n"
    rec = base_recording([fade_in(0.0, "s1")], {"s1": piece(0.0)}, [{"line": 7, "what": "updaters"}])
    result = import_scene(rec, source)
    assert not result.converted and result.reasons == ["line 7: updaters"]
    assert result.project.layers[0].spec.params["code"] == source


def test_sounds_and_subtitles_come_along(tmp_path) -> None:
    rec = base_recording([fade_in(0.0, "s1")], {"s1": piece(0.0)})
    rec["steps"] += [
        {"type": "subcaption", "t": 0.5, "duration": 1.0, "text": "Hello", "line": 6},
        {"type": "subcaption", "t": 1.0, "duration": 1.0, "text": "Overlaps", "line": 7},
        {"type": "sound", "t": 0.0, "path": str(tmp_path / "missing.wav"), "gain": 0.0, "exists": False},
    ]
    result = import_scene(rec, "")
    assert [(c.start, c.end, c.text) for c in result.project.subtitles] == [(0.5, 1.5, "Hello")]
    assert any("Overlaps" in line for line in result.report)
    assert any("missing.wav" in line for line in result.report) and not result.project.audio


# -- the file ----------------------------------------------------------------------------------------------


def test_scene_classes_are_read_without_running_the_file() -> None:
    source = textwrap.dedent(
        """
        from manim import *
        class Helper:
            pass
        class Base(MovingCameraScene):
            pass
        class Mine(Base):
            pass
        class Plain(manim.Scene):
            pass
        """
    )
    assert scene_classes(source) == ["Base", "Mine", "Plain"]
    assert scene_classes("not python (") == []
    code = scene_code(source, "Plain")
    assert "class Plain" in code and "class Base" not in code and "class Helper" in code
    with pytest.raises(ValueError, match="derives from Base"):
        scene_code(source, "Mine")


# -- a round trip: what the editor writes, imported back -----------------------------------------------------


def test_a_readable_export_imports_back_to_the_same_frames(tmp_path) -> None:
    project = Project(
        canvas=Canvas(width_px=192, height_px=108, fps=10, duration=4.0),
        layers=[
            Layer(
                id="ring",
                spec=Spec(type="Circle", params={"radius": 1.5}, style={"stroke": "#38bdf8"}),
                clips=[Clip(id="c", kind="Create", start=0.0, duration=1.0)],
            ),
            Layer(
                id="sq",
                spec=Spec(type="Square"),
                base=Transform2D(position=(3.0, -1.0)),
                clips=[
                    Clip(id="f", kind="FadeIn", start=0.5, duration=1.0, params={"shift": "UP"}),
                    Clip(id="t", kind="Transform", start=3.0, duration=0.6, to_layer="star"),
                ],
            ),
            Layer(
                id="star",
                spec=Spec(type="Star", style={"fill": "#facc15", "fill_opacity": 1.0}),
                base=Transform2D(position=(3.0, 1.0)),
            ),
            Layer(
                id="title",
                spec=Spec(type="Text", params={"text": "Hello"}),
                base=Transform2D(position=(0, 2.6)),
                clips=[Clip(id="w", kind="Write", start=1.0, duration=1.0)],
            ),
        ],
    )
    export = to_python(project, "RoundTrip")
    assert export.readable
    path = tmp_path / "round.py"
    path.write_text(export.code, encoding="utf-8")
    rec = record(export.code, str(path), "RoundTrip", sample_fps=10)
    result = import_scene(rec, export.code)
    assert result.converted, result.report
    assert sorted(x.spec.type for x in result.project.layers) == ["Circle", "Square", "Star", "Text"]
    assert_frames_match(rec, result.project)
    original, again = Evaluator(project), Evaluator(result.project)
    camera = make_camera(project.canvas)
    for t in (0.0, 0.5, 1.2, 2.0, 3.3, 3.9):
        a = render_frame(camera, original.frame(t))[:, :, :3].astype(int)
        b = render_frame(camera, again.frame(t))[:, :, :3].astype(int)
        assert np.abs(a - b).mean() < 0.5, t


def test_the_recording_is_not_changed_by_importing() -> None:
    rec = base_recording([fade_in(1.0, "s1")], {"s1": piece(2.0)})
    before = copy.deepcopy(rec)
    import_scene(rec, "")
    assert rec == before


# -- against a real `manim render` of the original scene (slow) ----------------------------------------------

REAL = "config.pixel_width = 320\nconfig.pixel_height = 180\nconfig.frame_rate = 10\n"


def real_import(tmp_path: Path, construct: str) -> tuple[str, scene_import.ImportResult]:
    source = (
        "from manim import *\n"
        + REAL
        + "\n\nclass Original(Scene):\n    def construct(self):\n"
        + textwrap.indent(textwrap.dedent(construct), " " * 8)
    )
    path = tmp_path / "original.py"
    path.write_text(source, encoding="utf-8")
    return source, import_scene(record(source, str(path), "Original"), source)


@pytest.mark.slow
def test_an_imported_scene_renders_what_manim_renders(tmp_path) -> None:
    from tests.core.test_python_export import assert_matches_editor, rendered

    source, result = real_import(
        tmp_path,
        """
        circle = Circle(radius=1.5, color=BLUE)
        square = Square(side_length=2).shift(RIGHT * 3)
        title = Text("Hi", font_size=60).to_edge(UP)
        self.play(Create(circle))
        self.play(FadeIn(square, shift=UP), Write(title))
        self.wait(0.5)
        self.play(circle.animate.shift(LEFT * 2).scale(0.5))
        self.play(Transform(square, Star(color=YELLOW).shift(RIGHT * 3)))
        self.play(Indicate(title))
        self.play(FadeOut(circle))
        self.wait()
        """,
    )
    assert result.converted, result.report
    assert_matches_editor(result.project, rendered(source, "Original", tmp_path))


@pytest.mark.slow
def test_an_imported_group_scene_renders_what_manim_renders(tmp_path) -> None:
    from tests.core.test_python_export import assert_matches_editor, rendered

    source, result = real_import(
        tmp_path,
        """
        a = Square(side_length=1).shift(LEFT * 2)
        b = Circle(radius=0.5)
        c = Triangle().shift(RIGHT * 2)
        g = VGroup(a, b, c)
        self.play(Create(g))
        self.play(g.animate.shift(DOWN).scale(0.8))
        self.play(Rotate(a, PI / 4), b.animate.shift(UP))
        self.play(TransformFromCopy(a, Dot(UP * 2, color=RED)), FadeOut(c, shift=RIGHT))
        self.play(a.animate.fade(0.6))
        self.wait(0.5)
        """,
    )
    assert result.converted, result.report
    assert_matches_editor(result.project, rendered(source, "Original", tmp_path))


def test_the_export_tests_rich_project_imports_back_to_the_same_frames(tmp_path) -> None:
    from tests.core.test_python_export import rich

    project = rich()  # a cluster, a gap, a morph, a turned and faded square, eases the export helps with
    project = project.model_copy(
        update={
            "layers": [x for x in project.layers if x.id != "dot"],  # MoveAlongPath is not imported (yet)
            "canvas": project.canvas.model_copy(update={"width_px": 192, "height_px": 108}),
        }
    )
    export = to_python(project, "Rich")
    assert export.readable
    path = tmp_path / "rich.py"
    path.write_text(export.code, encoding="utf-8")
    rec = record(export.code, str(path), "Rich", sample_fps=10)
    result = import_scene(rec, export.code)
    assert result.converted, result.report
    title = next(x for x in result.project.layers if x.spec.type == "Text")
    assert title.clips[0].ease.name == "ease_out_back"  # the export's clamped() helper read back
    assert_frames_match(rec, result.project)
    original, again = Evaluator(project), Evaluator(result.project)
    camera = make_camera(project.canvas)
    for t in (0.0, 0.7, 1.6, 2.3, 3.2, 3.9):
        a = render_frame(camera, original.frame(t))[:, :, :3].astype(int)
        b = render_frame(camera, again.frame(t))[:, :, :3].astype(int)
        assert np.abs(a - b).mean() < 0.5, t
