"""Colour characters (ADR 0055): a Text, MathTex or Tex with one colour per drawn glyph.

The contract is Manim's own: an object with ``glyph_colours`` draws like the plain object with
``glyph.set_color(c)`` on each of its ``family_members_with_points()`` in order, before anything
plays - so FadeIn, Write and morphs carry the colours and a clip that changes colour (Indicate)
goes from the glyph's colour to its own and back.
"""

from __future__ import annotations

import manim as m
import numpy as np
import pytest
from pydantic import ValidationError
from tests.support import TOLERANCE, max_diff

from manim_studio.core.editing import clipboard, edits, library
from manim_studio.core.engine import adapter, warm
from manim_studio.core.engine.evaluator import Evaluator
from manim_studio.core.model import glyph_colours as gc
from manim_studio.core.model.schema import Canvas, Clip, Layer, PartKey, Project, Spec
from manim_studio.render.cairo_export import make_camera, render_frame

CANVAS = Canvas(width_px=320, height_px=180, fps=15, duration=4.0)
RED, GREEN, BLUE, PINK = "#ff0000", "#00ff00", "#0000ff", "#ff00ff"  # content: colours a user picks
WHITE = "#ffffff"
HELLO = Spec(type="Text", params={"text": "hello"})
WORDS = Spec(type="Text", params={"text": "Hi ok"})  # tests.support.TEXT: warm
EQ = Spec(type="MathTex", params={"text": r"a^2 + b^2 = c^2"})  # warm (test_part_layers)
EQ_LABELS = ["a", "2", "+", "b", "2", "=", "c", "2"]
EIGHT = [RED, GREEN, BLUE, PINK, "#123456", "#abcdef", "#00ffff", "#ffff00"]


def coloured(spec: Spec, colours: list[str | None]) -> Spec:
    return spec.model_copy(update={"params": {**spec.params, gc.PARAM: colours}})


def fills(mob: m.Mobject) -> list[str]:
    return [leaf.get_fill_color().to_hex().lower() for leaf in mob.family_members_with_points()]


def by_hand(spec: Spec, colours: list[str | None]) -> m.Mobject:
    """The plain object coloured as a Manim script would: ``glyph.set_color(c)`` per glyph."""
    mob = adapter.build_mobject(spec)
    for glyph, colour in zip(mob.family_members_with_points(), colours, strict=False):
        if colour:
            glyph.set_color(colour)
    return mob


def one(spec: Spec, *clips: Clip, layer_id: str = "t", **fields) -> Project:
    return Project(canvas=CANVAS, layers=[Layer(id=layer_id, spec=spec, clips=list(clips), **fields)])


def assert_renders(evaluator: Evaluator, t: float, expected: list[m.Mobject]) -> None:
    camera = make_camera(CANVAS)
    diff = max_diff(render_frame(camera, evaluator.frame(t)), render_frame(camera, expected))
    assert diff <= TOLERANCE, f"t={t}: differs by {diff}"


# -- the feature ---------------------------------------------------------------------------------


def test_the_two_ls_of_hello_get_different_colours() -> None:
    mob = adapter.build_mobject(coloured(HELLO, [None, None, RED, GREEN]))
    assert fills(mob) == [WHITE, WHITE, RED, GREEN, WHITE]  # the missing last entry: the object's
    assert fills(adapter.build_mobject(HELLO)) == [WHITE] * 5  # the plain build is untouched
    evaluator = Evaluator(one(coloured(HELLO, [None, None, RED, GREEN])))
    assert_renders(evaluator, 0.5, [by_hand(HELLO, [None, None, RED, GREEN])])


@pytest.mark.latex
def test_every_glyph_of_an_equation_has_its_own_colour() -> None:
    mob = adapter.build_mobject(coloured(EQ, EIGHT))
    assert fills(mob) == EIGHT
    assert_renders(Evaluator(one(coloured(EQ, EIGHT))), 0.5, [by_hand(EQ, EIGHT)])


def test_extra_entries_are_ignored() -> None:
    assert fills(adapter.build_mobject(coloured(WORDS, [RED, None, None, None, GREEN, BLUE]))) == [
        RED,
        WHITE,
        WHITE,
        WHITE,
    ]


def test_glyph_labels_name_the_drawn_characters_without_spaces() -> None:
    assert adapter.glyph_labels(Spec(type="Text", params={"text": "hi there"})) == list("hithere")
    assert adapter.glyph_count(Spec(type="Text", params={"text": "a\nb c"})) == 3
    assert adapter.glyph_labels(HELLO) == list("hello")
    office = Spec(type="Text", params={"text": "office fi"})
    labels = adapter.glyph_labels(office)
    assert len(labels) == len(adapter.build_mobject(office).family_members_with_points())
    assert "".join(labels) == "officefi"  # ligatures are one glyph each, labelled by their letters
    assert adapter.glyph_labels(coloured(HELLO, [RED])) == list("hello")  # colours change nothing


def test_labels_that_cannot_be_matched_are_numbers(monkeypatch) -> None:
    assert adapter._text_labels(Spec(type="Text", params={"text": "abcd"}), 3) is None  # no ligature
    assert adapter._text_labels(Spec(type="Text", params={"text": "a ffi"}), 2) == ["a", "ffi"]
    monkeypatch.setattr(adapter, "_text_labels", lambda spec, count: ["x"] * (count + 1))
    assert adapter.glyph_labels(HELLO) == ["1", "2", "3", "4", "5"]


def test_tex_glyphs_are_labelled_from_their_font_codes() -> None:
    label = adapter._tex_label
    assert [label(f"g1-{code}", None, False) for code in (33, 43, 61, 97, 126)] == ["!", "+", "=", "a", "~"]
    assert label("g2-0", None, False) == "−"  # the minus of the symbol font
    assert label("g0-25", None, False) == "π"  # math: Greek
    assert label("g1-12", None, True) == "fi"  # text: a ligature
    assert label("g1-200", None, False) == "?"

    class Rect:  # a fraction bar has no glyph id
        pass

    assert label("", Rect(), False) == "—" and label("", object(), False) == "?"


@pytest.mark.latex
def test_glyph_labels_of_an_equation_follow_its_glyphs() -> None:
    assert adapter.glyph_labels(EQ) == EQ_LABELS
    leaves = adapter.build_mobject(EQ).family_members_with_points()
    xs = [leaf.get_center()[0] for leaf in leaves]
    assert xs == sorted(xs)  # left to right, as labelled
    assert adapter.glyph_count(EQ) == len(EQ_LABELS)


# -- the document --------------------------------------------------------------------------------


def test_glyph_colours_are_checked() -> None:
    assert one(coloured(HELLO, [RED, None, "#abc"])).layer("t").spec.params[gc.PARAM] == [RED, None, "#abc"]
    with pytest.raises(ValidationError, match="glyph 2 must be like #ff0000 or null"):
        one(coloured(HELLO, [RED, "red"]))
    with pytest.raises(ValidationError, match="must be a list"):
        one(coloured(HELLO, RED))
    with pytest.raises(ValidationError, match="at most 5000"):
        one(coloured(HELLO, [None] * 5001))
    with pytest.raises(ValidationError, match="only Text, MathTex and Tex"):
        one(Spec(type="Circle", params={gc.PARAM: [RED]}))


def test_old_files_are_unchanged_and_colours_round_trip() -> None:
    plain = one(HELLO)
    assert gc.PARAM not in plain.model_dump()["layers"][0]["spec"]["params"]
    project = one(coloured(HELLO, [None, RED]))
    assert Project.model_validate_json(project.model_dump_json(by_alias=True)) == project


def test_set_glyph_colours_is_one_spec_edit_and_all_null_removes_the_param() -> None:
    p = one(HELLO)
    edit = edits.set_glyph_colours(p, "t", [None, None, RED, GREEN, None])
    assert edit.kind == "spec" and edit.layer_ids == frozenset({"t"})
    assert edit.project.layer("t").spec.params[gc.PARAM] == [None, None, RED, GREEN]  # trimmed
    assert gc.PARAM not in p.layer("t").spec.params  # pure
    cleared = edits.set_glyph_colours(edit.project, "t", [None, None])
    assert gc.PARAM not in cleared.project.layer("t").spec.params
    assert cleared.project.layer("t").spec == HELLO
    assert edits.set_glyph_colours(edit.project, "t", []).project.layer("t").spec == HELLO
    with pytest.raises(edits.EditError, match="not a Text, MathTex or Tex"):
        edits.set_glyph_colours(one(Spec(type="Circle")), "t", [RED])
    with pytest.raises(edits.EditError, match="no layer"):
        edits.set_glyph_colours(p, "nope", [RED])
    with pytest.raises(ValidationError):
        edits.set_glyph_colours(p, "t", ["red"])


def test_copy_paste_and_duplicate_keep_the_colours() -> None:
    p = one(coloured(HELLO, [RED, GREEN]))
    pasted = clipboard.paste_layers(p, clipboard.copy_layers(p, ["t"]).payload)
    assert pasted.edit.project.layer(pasted.selected).spec.params[gc.PARAM] == [RED, GREEN]
    duplicated = clipboard.duplicate_layers(p, ["t"])
    assert duplicated.edit.project.layer(duplicated.selected).spec.params[gc.PARAM] == [RED, GREEN]


def test_a_colour_edit_needs_no_new_disk_cache_entry() -> None:
    assert warm.warm_key(coloured(EQ, [RED])) == warm.warm_key(EQ)
    old, new = one(EQ), one(coloured(EQ, [RED]))
    assert warm.needs_warm(old, new, {warm.warm_key(EQ)}) == set()


def test_a_colour_edit_reuses_the_plain_build(monkeypatch) -> None:
    adapter.build_mobject(WORDS)  # built (and cached) once
    calls = []
    original = adapter._build
    monkeypatch.setattr(adapter, "_build", lambda spec: calls.append(spec) or original(spec))
    for colours in ([RED], [GREEN, BLUE], [None, PINK]):
        assert fills(adapter.build_mobject(coloured(WORDS, colours)))[: len(colours)] == [
            c or WHITE for c in colours
        ]
    assert calls == []  # every colouring is a copy of the cached plain object


# -- composing with the other colours ------------------------------------------------------------


def test_glyph_colours_win_over_t2c_and_the_fill_on_the_glyphs_they_set() -> None:
    pieces = Spec(type="Text", params={"text": "Hi ok", "t2c": {"ok": RED}})
    assert fills(adapter.build_mobject(coloured(pieces, [None, None, GREEN]))) == [WHITE, WHITE, GREEN, RED]
    filled = WORDS.model_copy(update={"style": {"fill": BLUE}})
    assert fills(adapter.build_mobject(coloured(filled, [RED]))) == [RED, BLUE, BLUE, BLUE]
    both = pieces.model_copy(update={"style": {"fill": BLUE}})
    assert fills(adapter.build_mobject(coloured(both, [None, PINK]))) == [BLUE, PINK, RED, RED]


@pytest.mark.latex
def test_a_coloured_part_wins_over_glyph_colours_on_its_glyphs() -> None:
    eq = Layer(id="eq", spec=coloured(EQ, [GREEN] * 8))
    part = Layer(id="b", parent_id="eq", part=PartKey(tex="b^2"), style={"fill": RED})
    evaluator = Evaluator(Project(canvas=CANVAS, layers=[eq, part]))
    expected = by_hand(EQ, [GREEN, GREEN, GREEN, RED, RED, GREEN, GREEN, GREEN])
    assert_renders(evaluator, 0.5, [expected])
    assert adapter.glyph_labels(coloured(EQ, [GREEN])) == EQ_LABELS  # parts' markers draw nothing
    from manim_studio.core.model import parts

    marked = parts.build_spec(Project(canvas=CANVAS, layers=[eq, part]), "eq")
    regions = adapter.part_regions(marked)
    misses = adapter._regions_cached.cache_info().misses
    assert adapter.part_regions(coloured(marked, [BLUE])) == regions == [(3, 4)]
    assert adapter._regions_cached.cache_info().misses == misses  # a colour edit finds the parts again


@pytest.mark.latex
def test_indicate_goes_from_the_glyph_colours_to_its_own_and_back() -> None:
    colours = [RED, None, None, GREEN]
    indicate = Clip(id="i", kind="Indicate", start=1.0, duration=1.0)
    evaluator = Evaluator(one(coloured(EQ, colours), indicate))
    for alpha in (0.25, 0.5):
        mob = by_hand(EQ, colours)
        anim = adapter.make_animation("Indicate", mob, None, {})
        anim.begin()
        anim.interpolate(alpha)
        assert_renders(evaluator, 1.0 + alpha, [mob])  # the clip's yellow wins while it plays
    assert_renders(evaluator, 2.5, [by_hand(EQ, colours)])  # and the glyph colours are back


def test_write_and_fade_in_carry_the_colours() -> None:
    colours = [RED, GREEN, BLUE, PINK]
    for kind in ("Write", "FadeIn"):
        evaluator = Evaluator(one(coloured(WORDS, colours), Clip(id="c", kind=kind, start=0.0, duration=1.0)))
        mob = by_hand(WORDS, colours)
        anim = adapter.make_animation(kind, mob, None, {})
        anim.begin()
        anim.interpolate(0.6)
        assert_renders(evaluator, 0.6, [anim.mobject])


def test_a_morph_target_keeps_its_own_glyph_colours() -> None:
    source, target = coloured(WORDS, [RED] * 4), coloured(HELLO, [None, BLUE, None, None, GREEN])
    morph = Clip(id="m", kind="Transform", start=0.0, duration=1.0, to_layer="b")
    project = Project(
        canvas=CANVAS, layers=[Layer(id="a", spec=source, clips=[morph]), Layer(id="b", spec=target)]
    )
    evaluator = Evaluator(project)
    anim = adapter.make_animation(
        "Transform", by_hand(WORDS, [RED] * 4), None, {}, by_hand(HELLO, [None, BLUE, None, None, GREEN])
    )
    anim.begin()
    anim.interpolate(0.5)
    assert_renders(evaluator, 0.5, [anim.mobject])
    assert_renders(evaluator, 1.5, [by_hand(HELLO, [None, BLUE, None, None, GREEN])])


def test_a_theme_recolours_the_text_but_not_its_coloured_glyphs() -> None:
    project = one(coloured(WORDS, [None, RED]))
    theme = library.load_library([library.BUILTIN_FOLDER]).themes[0]
    themed = library.apply_theme(project, theme).project.layer("t").spec
    assert themed.params[gc.PARAM] == [None, RED]  # explicit choices are kept
    text = theme.text.lower()
    assert fills(adapter.build_mobject(themed)) == [text, RED, text, text]


@pytest.mark.latex
def test_freezing_keeps_the_colours_pixel_for_pixel() -> None:
    write = Clip(id="w", kind="Write", start=0.0, duration=1.0)
    project = one(coloured(EQ, EIGHT), write)
    frozen = edits.freeze_layer(project, "t", adapter.freeze_data(project.layer("t").spec)).project
    camera = make_camera(CANVAS)
    a, b = Evaluator(project), Evaluator(frozen)
    for t in (0.3, 0.7, 1.5):
        assert np.array_equal(render_frame(camera, a.frame(t)), render_frame(camera, b.frame(t))), t


# -- no LaTeX ------------------------------------------------------------------------------------


@pytest.fixture
def no_latex(monkeypatch, tmp_path):
    import shutil

    monkeypatch.setenv("PATH", str(tmp_path))
    assert shutil.which("latex") is None


def test_without_latex_a_text_is_coloured_and_an_equation_is_a_placeholder(no_latex) -> None:
    import uuid

    assert fills(adapter.build_mobject(coloured(HELLO, [RED]))) == [RED] + [WHITE] * 4
    unseen = Spec(type="MathTex", params={"text": rf"x + \text{{{uuid.uuid4().hex[:8]}}}", gc.PARAM: [RED]})
    evaluator = Evaluator(one(unseen))
    assert evaluator.frame_layers(0.5)  # the dashed placeholder, not an error
    assert "LaTeX is not installed" in evaluator.build_errors()["t"]
