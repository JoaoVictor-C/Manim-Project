"""The clipboard (P5d.1, ADR 0038): copying layers with their subtree and pasting them with fresh
ids and remapped references; clips, sounds and subtitles placed and refused."""

from __future__ import annotations

import json

import pytest

from manim_studio.core import clipboard, edits
from manim_studio.core.clipboard import ClipboardError
from manim_studio.core.evaluator import Evaluator
from manim_studio.core.schema import (
    AudioClip,
    Clip,
    Cue,
    Easing,
    Keyframe,
    Layer,
    Lifetime,
    PartKey,
    Project,
    Spec,
    Transform2D,
)
from support import CANVAS, CIRCLE, MATH, SQUARE, TEXT, assert_evaluators_agree

AXES = Spec(type="Axes")
SIN = Spec(type="Graph", params={"expression": "sin(x)"})
PARABOLA = Spec(type="Graph", params={"expression": "x**2/10 - 1"})


def scene() -> Project:
    """An equation with a part, axes with two graphs (one morphs into the other) and an area,
    a circle riding along a square, a trace of the circle and a connector between them."""
    return Project(
        canvas=CANVAS,
        layers=[
            Layer(id="eq", name="Euler", spec=MATH),
            Layer(id="term", name="plus one", parent_id="eq", part=PartKey(tex="+1")),
            Layer(id="ax", name="Axes", spec=AXES),
            Layer(
                id="g1",
                parent_id="ax",
                spec=SIN,
                clips=[Clip(id="m", kind="Transform", start=0.5, duration=0.3, to_layer="g2")],
            ),
            Layer(id="g2", parent_id="ax", spec=PARABOLA),
            Layer(
                id="area", parent_id="ax", spec=Spec(type="Area", params={"graph": "g1", "x_range": [0, 2]})
            ),
            Layer(id="sq", name="Square", spec=SQUARE),
            Layer(
                id="c",
                name="Circle",
                spec=CIRCLE,
                base=Transform2D(position=(-2.0, 1.0)),
                tracks={"opacity": [Keyframe(t=0.0, value=0.2), Keyframe(t=0.6, value=1.0)]},
                clips=[
                    Clip(id="in", kind="FadeIn", start=0.0, duration=0.3, params={"shift": "UP"}),
                    Clip(id="ride", kind="MoveAlongPath", start=0.4, duration=0.5, params={"path": "sq"}),
                ],
            ),
            Layer(id="tr", name="Trail", spec=Spec(type="TracedPath", params={"target": "c"})),
            Layer(
                id="link", name="Link", spec=Spec(type="Connector", params={"source": "c", "target": "sq"})
            ),
        ],
        audio=[AudioClip(id="audio-1", name="pop", path="C:/s/pop.wav", start=0.2, duration=0.5)],
        subtitles=[Cue(id="cue-1", start=0.0, end=0.4, text="Hello")],
    )


def morph_project() -> Project:
    return Project(
        canvas=CANVAS,
        layers=[
            Layer(
                id="a",
                name="A",
                spec=SQUARE,
                clips=[Clip(id="m", kind="Transform", start=0.4, duration=0.4, to_layer="b")],
            ),
            Layer(id="b", name="B", spec=CIRCLE),
        ],
    )


def paste(project: Project, ids: list[str], into: Project | None = None, above: str | None = None):
    data = clipboard.copy_layers(project, ids)
    return clipboard.paste_layers(into or project, data.payload, above=above)


def new_layers(before: Project, after: Project) -> list[Layer]:
    old = {layer.id for layer in before.layers}
    return [layer for layer in after.layers if layer.id not in old]


# -- layers -----------------------------------------------------------------------------------------


def test_an_object_is_copied_with_its_parts_and_fresh_ids() -> None:
    project = scene()
    project = edits.add_audio(project, "C:/s/x.wav", 0.0, 0.2).project  # "audio-2"
    project = Project.model_validate(
        {**project.model_dump(by_alias=True), "subtitles": [{"id": "mathtex-1", "start": 0.5, "end": 0.6}]}
    )
    pasted = clipboard.duplicate_layers(project, ["eq"])
    eq, term = new_layers(project, pasted.edit.project)
    assert eq.id == "mathtex-2"  # mathtex-1 is a subtitle's id: ids are unique across everything
    assert term.id.startswith("part-") and term.parent_id == eq.id and term.part == PartKey(tex="+1")
    assert (eq.name, term.name) == ("Euler copy", "plus one")  # only the top gets " copy"
    assert eq.spec == MATH
    assert pasted.selected == eq.id and pasted.notes == ()
    ids = [x.id for x in pasted.edit.project.layers]
    assert ids[:4] == ["eq", "term", eq.id, term.id]  # right above the original object
    assert pasted.edit.kind == "clip" and {eq.id, term.id} <= pasted.edit.layer_ids


def test_a_part_cannot_be_copied() -> None:
    with pytest.raises(ClipboardError, match="part"):
        clipboard.copy_layers(scene(), ["term"])


def test_axes_are_copied_with_their_graphs_and_references_remapped() -> None:
    project = scene()
    pasted = clipboard.duplicate_layers(project, ["ax"])
    ax, g1, g2, area = new_layers(project, pasted.edit.project)
    assert (ax.spec.type, g1.spec, g2.spec, area.spec.type) == ("Axes", SIN, PARABOLA, "Area")
    assert {g1.parent_id, g2.parent_id, area.parent_id} == {ax.id}
    assert g1.clips[0].to_layer == g2.id  # a morph between two copied layers follows them
    assert area.spec.params["graph"] == g1.id
    assert pasted.edit.project.layer("g1").clips[0].to_layer == "g2"  # the original is untouched
    assert pasted.notes == ()


def test_a_morph_between_two_copied_objects_is_remapped() -> None:
    project = morph_project()
    pasted = paste(project, ["a", "b"])
    a, b = new_layers(project, pasted.edit.project)
    assert a.clips[0].to_layer == b.id and b.lifetime.in_ is None


def test_a_morph_to_an_outside_layer_is_kept_when_that_layer_is_free() -> None:
    project = morph_project()
    target_only = Project(canvas=CANVAS, layers=[project.layer("b")])
    pasted = paste(project, ["a"], into=target_only)
    (a,) = new_layers(target_only, pasted.edit.project)
    assert a.clips[0].to_layer == "b" and a.lifetime.out is None and pasted.notes == ()


def test_a_morph_to_a_layer_already_targeted_is_left_out_and_the_copy_still_disappears() -> None:
    project = morph_project()
    pasted = clipboard.duplicate_layers(project, ["a"])
    (a,) = new_layers(project, pasted.edit.project)
    assert a.clips == [] and a.lifetime.out == pytest.approx(0.8)  # when the original's morph ends
    assert pasted.edit.project.lifetime(a.id) == project.lifetime("a")
    assert len(pasted.notes) == 1 and "Transform" in pasted.notes[0]


def test_a_morph_to_a_missing_layer_is_left_out() -> None:
    project = morph_project()
    pasted = paste(project, ["a"], into=Project(canvas=CANVAS))
    (a,) = pasted.edit.project.layers
    assert a.clips == [] and a.lifetime.out == pytest.approx(0.8) and pasted.notes


def test_an_explicit_lifetime_end_is_kept_when_a_morph_is_left_out() -> None:
    project = edits.update_layer(morph_project(), "a", lifetime=Lifetime(out=0.6)).project
    (a,) = new_layers(project, clipboard.duplicate_layers(project, ["a"]).edit.project)
    assert a.lifetime.out == 0.6


def test_a_copied_morph_target_appears_when_the_original_does() -> None:
    project = morph_project()
    pasted = clipboard.duplicate_layers(project, ["b"])
    (b,) = new_layers(project, pasted.edit.project)
    assert b.lifetime.in_ == pytest.approx(0.8)
    assert pasted.edit.project.lifetime(b.id) == project.lifetime("b")
    explicit = edits.update_layer(project, "b", lifetime=Lifetime(**{"in": 0.1})).project
    (b,) = new_layers(explicit, clipboard.duplicate_layers(explicit, ["b"]).edit.project)
    assert b.lifetime.in_ == 0.1  # an explicit start wins


def test_a_morph_target_copied_with_its_source_keeps_its_inferred_start() -> None:
    project = morph_project()
    a, b = new_layers(project, paste(project, ["a", "b"]).edit.project)
    assert b.lifetime.in_ is None and a.lifetime.out is None


def test_a_motion_path_follows_the_copy_or_stays_on_the_original() -> None:
    project = scene()
    inside = paste(project, ["sq", "c"])
    sq, c = new_layers(project, inside.edit.project)
    assert c.clips[1].params["path"] == sq.id
    (c,) = new_layers(project, clipboard.duplicate_layers(project, ["c"]).edit.project)
    assert c.clips[1].params == {"path": "sq"}  # outside the copy: the same square


def test_a_motion_clip_whose_path_is_missing_or_another_type_is_left_out() -> None:
    project = scene()
    for into in (
        Project(canvas=CANVAS),
        Project(canvas=CANVAS, layers=[Layer(id="sq", spec=TEXT)]),  # same id, not a square
    ):
        pasted = paste(project, ["c"], into=into)
        (c,) = new_layers(into, pasted.edit.project)
        assert [clip.kind for clip in c.clips] == ["FadeIn"]
        assert len(pasted.notes) == 1 and "MoveAlongPath" in pasted.notes[0]


def test_traces_and_connectors_follow_their_targets() -> None:
    project = scene()
    (tr,) = new_layers(project, clipboard.duplicate_layers(project, ["tr"]).edit.project)
    assert tr.spec.params["target"] == "c"
    (link,) = new_layers(project, clipboard.duplicate_layers(project, ["link"]).edit.project)
    assert (link.spec.params["source"], link.spec.params["target"]) == ("c", "sq")
    together = paste(project, ["c", "tr", "link"])
    c, tr, link = new_layers(project, together.edit.project)
    assert tr.spec.params["target"] == c.id
    assert (link.spec.params["source"], link.spec.params["target"]) == (c.id, "sq")


def test_a_trace_or_connector_whose_target_is_missing_is_not_pasted() -> None:
    project = scene()
    only_circle = Project(canvas=CANVAS, layers=[Layer(id="c", spec=CIRCLE)])
    with pytest.raises(ClipboardError, match="not in this project"):
        paste(project, ["link"], into=only_circle)  # the square is missing
    pasted = paste(project, ["sq", "c", "tr", "link"], into=Project(canvas=CANVAS))
    _sq, c, tr, link = new_layers(Project(), pasted.edit.project)
    assert tr.spec.params["target"] == c.id and link.spec.params["source"] == c.id
    alone = paste(project, ["c", "link"], into=Project(canvas=CANVAS))
    assert [x.spec.type for x in alone.edit.project.layers] == ["Circle"]
    assert len(alone.notes) == 2 and any("Link" in note for note in alone.notes)  # and its ride
    with pytest.raises(ClipboardError):
        paste(project, ["tr"], into=Project(canvas=CANVAS, layers=[Layer(id="c", spec=TEXT)]))


def test_an_object_on_axes_pastes_onto_its_axes_or_is_refused() -> None:
    project = scene()
    pasted = clipboard.duplicate_layers(project, ["area"])
    (area,) = new_layers(project, pasted.edit.project)
    assert area.parent_id == "ax" and area.spec.params["graph"] == "g1"
    ids = [x.id for x in pasted.edit.project.layers]
    assert ids.index(area.id) == ids.index("area") + 1  # after the axes' other objects
    with pytest.raises(ClipboardError, match="axes"):
        paste(project, ["g2"], into=Project(canvas=CANVAS))
    no_graph = Project(canvas=CANVAS, layers=[Layer(id="ax", spec=AXES)])
    with pytest.raises(ClipboardError, match="graph"):
        paste(project, ["area"], into=no_graph)


def test_names_get_copy_only_when_taken() -> None:
    project = scene()
    once = clipboard.duplicate_layers(project, ["sq"]).edit.project
    twice = clipboard.duplicate_layers(once, ["sq"]).edit.project
    assert sorted(x.name for x in twice.layers if x.spec and x.spec.type == "Square") == [
        "Square",
        "Square copy",
        "Square copy 2",
    ]
    (sq,) = paste(project, ["sq"], into=Project(canvas=CANVAS)).edit.project.layers
    assert sq.name == "Square"
    unnamed = Project(canvas=CANVAS, layers=[Layer(id="dot", spec=Spec(type="Dot"))])
    assert new_layers(unnamed, clipboard.duplicate_layers(unnamed, ["dot"]).edit.project)[0].name == ""


def test_pasted_layers_go_above_the_selected_object_or_on_top() -> None:
    project = scene()
    data = clipboard.copy_layers(project, ["sq"]).payload
    roots = [x.id for x in clipboard.paste_layers(project, data, above="term").edit.project.roots()]
    assert roots[:2] == ["eq", "square-1"]  # above the part's object
    roots = [x.id for x in clipboard.paste_layers(project, data, above=None).edit.project.roots()]
    assert roots[-1] == "square-1"
    roots = [x.id for x in clipboard.paste_layers(project, data, above="missing").edit.project.roots()]
    assert roots[-1] == "square-1"


def test_a_copy_draws_like_the_original() -> None:
    project = Project(canvas=CANVAS, layers=[scene().layer("sq"), scene().layer("c")])
    alone = Project(canvas=CANVAS, layers=[project.layer("sq")])
    pasted = clipboard.paste_layers(alone, clipboard.copy_layers(project, ["c"]).payload)
    assert_evaluators_agree(Evaluator(project), Evaluator(pasted.edit.project))
    axes = Project(canvas=CANVAS, layers=[x for x in scene().layers if x.id in ("ax", "g1", "g2", "area")])
    pasted = clipboard.paste_layers(Project(canvas=CANVAS), clipboard.copy_layers(axes, ["ax"]).payload)
    assert_evaluators_agree(Evaluator(axes), Evaluator(pasted.edit.project))


def test_copy_records_the_type_of_outside_references() -> None:
    data = clipboard.copy_layers(scene(), ["c", "link", "area"])
    assert data.payload.outside == {"sq": "Square", "ax": "Axes", "g1": "Graph"}


def test_copying_nothing_or_a_missing_layer_is_refused() -> None:
    with pytest.raises(ClipboardError):
        clipboard.copy_layers(scene(), [])
    with pytest.raises(ClipboardError):
        clipboard.copy_layers(scene(), ["nope"])


# -- the clipboard text ------------------------------------------------------------------------------


def test_the_clipboard_text_round_trips() -> None:
    data = clipboard.copy_layers(scene(), ["c"])
    text = clipboard.to_json(data)
    parsed = json.loads(text)
    assert (parsed["format"], parsed["version"], parsed["kind"]) == ("manim-studio-clipboard", 1, "layers")
    assert clipboard.from_json(text) == data
    for kind, data in (
        ("clip", clipboard.copy_clip(scene(), "c", "in")),
        ("audio", clipboard.copy_audio(scene(), "audio-1")),
        ("cue", clipboard.copy_cue(scene(), "cue-1")),
    ):
        assert data.kind == kind and clipboard.from_json(clipboard.to_json(data)) == data


@pytest.mark.parametrize(
    "text",
    [
        "",
        "hello",
        "[1, 2]",
        '{"format": "something-else", "version": 1, "kind": "cue", "payload": {}}',
        '{"format": "manim-studio-clipboard", "version": 1, "kind": "cue", "payload": {"cue": {}}}',
        '{"format": "manim-studio-clipboard", "version": 1, "kind": "dance", "payload": {}}',
    ],
)
def test_text_that_is_not_a_clipboard_is_refused(text: str) -> None:
    with pytest.raises(ClipboardError, match="nothing Manim Studio can paste"):
        clipboard.from_json(text)


def test_a_newer_clipboard_is_refused() -> None:
    data = json.loads(clipboard.to_json(clipboard.copy_cue(scene(), "cue-1")))
    data["version"] = 2
    with pytest.raises(ClipboardError, match="newer"):
        clipboard.from_json(json.dumps(data))


def test_a_payload_must_match_its_kind() -> None:
    data = json.loads(clipboard.to_json(clipboard.copy_cue(scene(), "cue-1")))
    data["kind"] = "audio"
    with pytest.raises(ClipboardError):
        clipboard.from_json(json.dumps(data))


# -- clips ---------------------------------------------------------------------------------------


def test_a_clip_pastes_with_a_fresh_id_and_its_settings() -> None:
    project = scene()
    clip = Clip(
        id="x",
        kind="Indicate",
        start=0,
        duration=0.2,
        ease=Easing(name="linear"),
        params={"color": "#00ff00"},
    )
    data = clipboard.ClipPayload(clip=clip)
    pasted = clipboard.paste_clip(project, data, "sq", 0.3)
    (new,) = pasted.edit.project.layer("sq").clips
    assert (new.id, new.kind, new.start, new.duration, new.ease, new.params) == (
        "indicate-1",
        "Indicate",
        0.3,
        0.2,
        Easing(name="linear"),
        {"color": "#00ff00"},
    )
    assert pasted.selected == new.id and pasted.edit.kind == "clip"
    again = clipboard.paste_clip(pasted.edit.project, data, "sq", 0.6)
    assert [c.id for c in again.edit.project.layer("sq").clips] == ["indicate-1", "indicate-2"]


def test_a_clip_is_refused_where_it_overlaps_or_is_not_allowed() -> None:
    project = scene()
    fade = clipboard.copy_clip(project, "c", "in").payload
    with pytest.raises(ClipboardError, match="room"):
        clipboard.paste_clip(project, fade, "c", 0.1)  # on its own FadeIn
    with_part_clip = edits.add_clip(project, "term", "Indicate", 0.0, 0.5).project
    with pytest.raises(ClipboardError, match="room"):
        clipboard.paste_clip(with_part_clip, fade, "eq", 0.1)  # over its part's clip (ADR 0012)
    with pytest.raises(ClipboardError, match="cannot go on"):
        clipboard.paste_clip(project, fade, "sq", 0.0, allowed=["Indicate"])
    with pytest.raises(ClipboardError):
        clipboard.paste_clip(project, fade, "link", 0.0)  # connectors have no clips
    write = clipboard.ClipPayload(clip=Clip(id="w", kind="AddTextLetterByLetter", start=0, duration=0.3))
    with pytest.raises(ClipboardError):
        clipboard.paste_clip(project, write, "sq", 0.0)  # Text only
    with pytest.raises(ClipboardError, match="no layer"):
        clipboard.paste_clip(project, fade, "nope", 0.0)


def test_a_morph_or_motion_clip_needs_a_valid_target_there() -> None:
    project = scene()
    ride = clipboard.copy_clip(project, "c", "ride").payload
    moved = clipboard.paste_clip(project, ride, "eq", 0.0)
    assert moved.edit.project.layer("eq").clips[0].params["path"] == "sq"
    with pytest.raises(ClipboardError, match="path"):
        clipboard.paste_clip(project, ride, "sq", 0.0)  # along itself
    with pytest.raises(ClipboardError):
        clipboard.paste_clip(project, ride, "term", 0.0)  # a part cannot travel
    with pytest.raises(ClipboardError, match="path"):
        clipboard.paste_clip(Project(canvas=CANVAS, layers=[project.layer("eq")]), ride, "eq", 0.0)
    morph = clipboard.copy_clip(morph_project(), "a", "m").payload
    with pytest.raises(ClipboardError, match="turns into"):
        clipboard.paste_clip(project, morph, "sq", 0.0)  # no "b" here
    with pytest.raises(ClipboardError):
        clipboard.paste_clip(morph_project(), morph, "b", 0.0)  # into itself
    other = Project(canvas=CANVAS, layers=[Layer(id="x", spec=SQUARE), Layer(id="b", spec=CIRCLE)])
    assert clipboard.paste_clip(other, morph, "x", 0.0).edit.project.layer("x").clips[0].to_layer == "b"


def test_duplicating_a_clip_puts_it_right_after() -> None:
    clips = [
        Clip(id="in", kind="FadeIn", start=0.0, duration=0.3),
        Clip(id="i", kind="Indicate", start=0.7, duration=0.2),
    ]
    project = Project(canvas=CANVAS, layers=[Layer(id="c", spec=CIRCLE, clips=clips)])
    pasted = clipboard.duplicate_clip(project, "c", "in")
    starts = [(c.kind, c.start) for c in pasted.edit.project.layer("c").clips]
    assert starts == [("FadeIn", 0.0), ("FadeIn", 0.3), ("Indicate", 0.7)]
    assert pasted.selected == "fadein-1"
    with pytest.raises(ClipboardError, match="room"):
        clipboard.duplicate_clip(pasted.edit.project, "c", "in")  # 0.3 is taken now
    with pytest.raises(ClipboardError, match="room"):
        clipboard.duplicate_clip(project, "c", "i")  # it would run past the end of the video
    with pytest.raises(ClipboardError):
        clipboard.duplicate_clip(morph_project(), "a", "m")  # nothing follows a morph


# -- sounds and subtitles --------------------------------------------------------------------------


def test_a_sound_pastes_at_the_playhead_with_its_trim_gain_and_fades() -> None:
    project = edits.update_audio(scene(), "audio-1", offset=0.1, gain=-3.0, fade_in=0.1, fade_out=0.2).project
    data = clipboard.copy_audio(project, "audio-1").payload
    pasted = clipboard.paste_audio(project, data, 0.7)
    new = pasted.edit.project.audio[-1]
    assert new.id == "audio-2" and pasted.selected == "audio-2"
    old = project.audio[0]
    assert (new.path, new.name, new.offset, new.duration, new.gain, new.fade_in, new.fade_out) == (
        old.path,
        old.name,
        old.offset,
        old.duration,
        old.gain,
        old.fade_in,
        old.fade_out,
    )
    assert new.start == 0.7 and pasted.edit.kind == "timing" and pasted.edit.layer_ids == frozenset()
    after = clipboard.duplicate_audio(project, "audio-1").edit.project.audio[-1]
    assert after.start == pytest.approx(old.end)


def test_a_subtitle_pastes_where_it_fits() -> None:
    project = scene()
    data = clipboard.copy_cue(project, "cue-1").payload
    pasted = clipboard.paste_cue(project, data, 0.5)
    new = next(c for c in pasted.edit.project.subtitles if c.id == pasted.selected)
    assert (new.start, new.end, new.text) == (0.5, pytest.approx(0.9), "Hello")
    with pytest.raises(ClipboardError, match="room"):
        clipboard.paste_cue(project, data, 0.2)
    with pytest.raises(ClipboardError, match="room"):
        clipboard.paste_cue(pasted.edit.project, data, 0.3)  # would run into the pasted one
    dup = clipboard.duplicate_cue(project, "cue-1").edit.project.subtitles
    assert [(c.start, c.text) for c in dup] == [(0.0, "Hello"), (0.4, "Hello")]
    with pytest.raises(ClipboardError, match="room"):
        clipboard.duplicate_cue(pasted.edit.project, "cue-1")  # the pasted one is in the way


def test_copying_a_missing_clip_sound_or_subtitle_is_refused() -> None:
    project = scene()
    for copy in (
        lambda: clipboard.copy_clip(project, "c", "nope"),
        lambda: clipboard.copy_clip(project, "nope", "in"),
        lambda: clipboard.copy_audio(project, "nope"),
        lambda: clipboard.copy_cue(project, "nope"),
    ):
        with pytest.raises(ClipboardError):
            copy()
