"""Equation steps as layers (P11, ADR 0054): ``edits.add_equation_steps`` makes one MathTex per
step and morphs each into the next; the evaluator then shows exactly one step at a time.

LaTeX is slow on the user's computer: the formulas here are few, and the frame tests share the
Pythagoras steps (each formula compiles once, then Manim's cache answers)."""

from __future__ import annotations

import shutil

import manim as m
import pytest

from manim_studio.core.editing import edits
from manim_studio.core.editing.equation_steps import REPLACING
from manim_studio.core.engine import adapter
from manim_studio.core.engine.evaluator import Evaluator
from manim_studio.core.model.schema import Canvas, Layer, Project, Spec
from manim_studio.render.cairo_export import make_camera, render_frame
from support import TOLERANCE, max_diff

CANVAS = Canvas(width_px=320, height_px=180, fps=10, duration=2.0)
PYTHAGORAS = [r"A = L \times L", r"L = a+b", r"A = (a+b) \times (a+b)"]
YELLOW = "#ffff00"  # content: the highlight the user picks
TIMING = {"start": 0.5, "step_duration": 1.0, "hold": 0.5}  # write 0.5-1.5, morphs 2-3 and 3.5-4.5


def steps(lines=PYTHAGORAS, project: Project | None = None, **options):
    project = project or Project(canvas=CANVAS)
    return edits.add_equation_steps(project, lines, **{**TIMING, **options})


# -- the layers and clips (no LaTeX) ---------------------------------------------------------------


def test_one_mathtex_per_step_named_and_placed_with_morphs_back_to_back() -> None:
    edit, report = steps(position=(1.0, -0.5))
    roots = edit.project.roots()
    assert [r.name for r in roots] == ["Step 1", "Step 2", "Step 3"]
    assert [r.spec.params for r in roots] == [{"text": t} for t in PYTHAGORAS]
    assert all(r.base.position == (1.0, -0.5) and r.spec.style == {} for r in roots)
    one, two, three = roots
    assert [(c.kind, c.start, c.duration, c.to_layer) for c in one.clips] == [
        ("Write", 0.5, 1.0, None),
        (REPLACING, 2.0, 1.0, two.id),
    ]
    assert [(c.kind, c.start, c.duration, c.to_layer) for c in two.clips] == [
        (REPLACING, 3.5, 1.0, three.id)
    ]
    assert three.clips == []
    assert report.layer_ids == (one.id, two.id, three.id)
    assert report.transitions == (REPLACING, REPLACING) and report.end == 4.5
    assert report.summary() == "Added 3 steps, 2 Transform morphs"
    assert all(
        clip.params == {"match": "smart"}
        for root in (one, two)
        for clip in root.clips
        if clip.to_layer
    )
    # Lifetimes come from the clips alone (ADR 0005): each step only in its own window.
    assert edit.project.lifetime(one.id) == (0.5, 3.0)
    assert edit.project.lifetime(two.id) == (3.0, 4.5)
    assert edit.project.lifetime(three.id)[0] == 4.5 and edit.project.lifetime(three.id)[1] > 1e9
    assert edit.kind == "clip" and set(report.layer_ids) <= edit.layer_ids


def test_the_scene_grows_to_hold_the_last_step_and_a_fixed_length_stays() -> None:
    edit, _ = steps()
    assert edit.project.canvas.duration == pytest.approx(5.0)  # the last morph ends at 4.5, plus the hold
    fixed = Project(canvas=CANVAS.model_copy(update={"grow_with_content": False}))
    assert steps(project=fixed)[0].project.canvas.duration == CANVAS.duration
    long = Project(canvas=CANVAS.model_copy(update={"duration": 20.0}))
    assert steps(project=long)[0].project.canvas.duration == 20.0  # never shrinks


def test_options_font_size_colour_fade_in_and_names() -> None:
    edit, _ = steps(font_size=36, colour="#ff0000", entrance="FadeIn", name="Line")
    first = edit.project.roots()[0]
    assert first.name == "Line 1" and first.clips[0].kind == "FadeIn"
    assert first.spec.params == {"text": PYTHAGORAS[0], "font_size": 36.0}
    assert first.spec.style == {"fill": "#ff0000"}
    plain, _ = steps(font_size=48, colour="#FFFFFF")  # the defaults are left out of the file
    assert plain.project.roots()[0].spec == Spec(type="MathTex", params={"text": PYTHAGORAS[0]})


def test_steps_go_on_top_of_what_is_there_with_fresh_ids() -> None:
    there = Project(canvas=CANVAS, layers=[Layer(id="mathtex-1", spec=Spec(type="Circle"))])
    edit, report = steps(project=there)
    assert [x.id for x in edit.project.layers][:1] == ["mathtex-1"]
    assert report.layer_ids == ("mathtex-2", "mathtex-3", "mathtex-4")


def test_one_step_has_only_its_entrance_and_every_transition_uses_transform() -> None:
    edit, report = steps(["x = 1"])
    (only,) = edit.project.roots()
    assert [c.kind for c in only.clips] == ["Write"] and report.transitions == ()
    replaced, report = steps(["x = 1", "y^2 + 7"])
    assert report.transitions == (REPLACING,)
    assert replaced.project.roots()[0].clips[1].params == {"match": "smart"}  # ADR 0056
    shared, _ = steps()
    assert shared.project.roots()[0].clips[1].params == {"match": "smart"}


@pytest.mark.parametrize(
    ("lines", "options", "message"),
    [
        ([], {}, "at least one equation"),
        (["x = 1", "  "], {}, "a step is empty"),
        (["x = 1"] * 41, {}, "41 steps: at most 40"),
        (["x = 1"], {"step_duration": 0}, "step duration more than 0"),
        (["x = 1"], {"hold": -1}, "hold must be 0 or more"),
        (["x = 1"], {"start": -1}, "start and hold must be 0 or more"),
        (["x = 1"], {"entrance": "Create"}, "Write or FadeIn, not 'Create'"),
        (["x = 1"], {"colour": "red"}, "the colour must be like"),
        (["x = 1"], {"highlight_colour": "yellow"}, "the highlight colour must be like"),
        (["x = 1"], {"font_size": 2}, "font size must be from 4 to 400"),
    ],
)
def test_bad_requests_are_refused_with_the_reason(lines, options, message) -> None:
    with pytest.raises(edits.EditError, match=message):
        steps(lines, **options)


def test_new_terms_are_coloured_parts_of_their_own_step_only() -> None:
    edit, report = steps(highlight_colour=YELLOW)
    one, two, three = edit.project.roots()
    assert edit.project.children(one.id) == []  # the first step has nothing new
    assert [(p.part.tex, p.part.occurrence, p.style) for p in edit.project.children(two.id)] == [
        ("= a+b", 0, {"fill": YELLOW})
    ]
    assert [p.part.tex for p in edit.project.children(three.id)] == ["A", r"\times (a+b)"]
    assert report.highlighted == ((2, "= a+b", 0), (3, "A", 0), (3, r"\times (a+b)", 0))
    assert report.skipped == () and "3 new terms coloured" in report.summary()


def test_terms_the_parts_cannot_isolate_are_skipped_and_reported() -> None:
    # A whole fraction as an unbraced superscript cannot carry a part marker (ADR 0012).
    edit, report = steps(["y = x", r"y = x^\frac{1}{2}"], highlight_colour=YELLOW)
    assert edit.project.children(report.layer_ids[1]) == []
    assert report.skipped == ((2, r"\frac{1}{2}", "the part starts inside a superscript or subscript"),)
    edit, report = steps(["a = y", "a a a = y"], highlight_colour=YELLOW)  # the key would find another "a a"
    assert report.skipped == ((2, "a a", "it overlaps another match of the same text"),)
    assert "1 not coloured" in report.summary()


def test_a_replacement_step_is_not_highlighted() -> None:
    edit, report = steps(["x = 1", "y^2 + 7"], highlight_colour=YELLOW)
    assert edit.project.children(report.layer_ids[1]) == [] and report.highlighted == ()


def test_the_edit_is_pure() -> None:
    before = Project(canvas=CANVAS)
    steps(project=before, highlight_colour=YELLOW)
    assert before.layers == [] and before.canvas == CANVAS


# -- what the evaluator draws (LaTeX) --------------------------------------------------------------


def reference(tex: str, position=(0.0, 0.0)) -> m.Mobject:
    return adapter.build_mobject(Spec(type="MathTex", params={"text": tex})).shift([*position, 0.0])


def render(mobs) -> object:
    return render_frame(make_camera(CANVAS), mobs)


@pytest.mark.latex
def test_one_step_at_a_time_and_a_morph_between_them() -> None:
    edit, report = steps(position=(0.0, 1.0))
    evaluator = Evaluator(edit.project)
    one, two, three = report.layer_ids
    assert evaluator.frame_layers(0.25) == []  # before the first step enters
    for t, layer_id, tex in (
        (1.75, one, PYTHAGORAS[0]),
        (3.25, two, PYTHAGORAS[1]),
        (4.9, three, PYTHAGORAS[2]),
    ):
        assert [i for i, _ in evaluator.frame_layers(t)] == [layer_id], t
        assert max_diff(render(evaluator.frame(t)), render([reference(tex, (0.0, 1.0))])) <= TOLERANCE, t
    for t, source, (a, b) in ((2.5, one, PYTHAGORAS[:2]), (4.0, two, PYTHAGORAS[1:])):
        assert [i for i, _ in evaluator.frame_layers(t)] == [source]  # drawn as one morph
        frame = render(evaluator.frame(t))
        assert max_diff(frame, render([reference(a, (0.0, 1.0))])) > TOLERANCE
        assert max_diff(frame, render([reference(b, (0.0, 1.0))])) > TOLERANCE


@pytest.mark.latex
def test_a_highlighted_step_draws_like_the_same_equation_coloured_by_hand() -> None:
    edit, report = steps(PYTHAGORAS[:2], highlight_colour=YELLOW)
    two = report.layer_ids[1]
    by_hand = Project(
        canvas=CANVAS, layers=[Layer(id="eq", spec=Spec(type="MathTex", params={"text": PYTHAGORAS[1]}))]
    )
    by_hand = edits.colour_part(by_hand, "eq", "= a+b", 0, fill=YELLOW).project
    expected = render(Evaluator(by_hand).frame(0.0))
    evaluator = Evaluator(edit.project)
    assert next(i for i, _ in evaluator.frame_layers(3.25)) == two  # then its coloured part
    assert max_diff(render(evaluator.frame(3.25)), expected) <= TOLERANCE
    assert max_diff(expected, render([reference(PYTHAGORAS[1])])) > TOLERANCE  # it is coloured


def test_without_latex_the_steps_are_added_and_drawn_as_placeholders_that_say_why(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    assert shutil.which("latex") is None
    unseen = [r"p = q + \text{p11-no-latex-1}", r"p + 1 = q + 1 + \text{p11-no-latex-1}"]
    edit, report = steps(unseen, highlight_colour=YELLOW)
    evaluator = Evaluator(edit.project)
    for t in (1.0, 2.5, 3.25):
        drawn = dict(evaluator.frame_layers(t))
        assert len(drawn) == 1 and next(iter(drawn.values())).family_members_with_points()
    errors = evaluator.build_errors()
    assert all("LaTeX is not installed" in errors[i] for i in report.layer_ids)
