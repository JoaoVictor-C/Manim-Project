"""Compound sequences (ADR 0079): named clips and keys that move, retime and copy together."""

from __future__ import annotations

import numpy as np
import pytest
from pydantic import ValidationError

from manim_studio.core.editing import edits, ripple, shift_timing
from manim_studio.core.editing.sequences import (
    Members,
    dissolve_sequence,
    duplicate_sequence,
    make_sequence,
    members_from_selection,
    move_sequence,
    new_sequence_name,
    rename_sequence,
    retime_sequence,
    selection_of,
    sequence_of_clip,
    sequence_of_key,
    set_sequence_colour,
    span,
)
from manim_studio.core.engine import frame_cache
from manim_studio.core.engine.evaluator import Evaluator
from manim_studio.core.engine.python_export import to_python
from manim_studio.core.model.schema import (
    Canvas,
    Clip,
    Keyframe,
    Layer,
    Lifetime,
    Project,
    Sequence,
    SequenceClip,
    SequenceKey,
    Spec,
    Transform2D,
)
from manim_studio.render.cairo_export import make_camera, render_frame


def scene() -> Project:
    return Project(
        canvas=Canvas(width_px=320, height_px=180, fps=10, duration=10.0),
        layers=[
            Layer(
                id="a",
                spec=Spec(type="Square", style={"fill": "#3b82f6", "fill_opacity": 0.8}),
                lifetime=Lifetime(in_=1.0),
                clips=[
                    Clip(id="f", kind="FadeIn", start=1.0, duration=1.0),
                    Clip(id="i", kind="Indicate", start=5.0, duration=1.0),
                ],
                tracks={"position": [Keyframe(t=2.0, value=(0.0, 0.0)), Keyframe(t=5.5, value=(2.0, 1.0))]},
            ),
            Layer(
                id="b",
                spec=Spec(type="Circle", style={"stroke": "#f59e0b"}),
                base=Transform2D(position=(-2.0, 0.0)),
                clips=[Clip(id="w", kind="Create", start=2.0, duration=2.0)],
                tracks={"scale": [Keyframe(t=4.0, value=1.0), Keyframe(t=7.0, value=2.0)]},
            ),
        ],
    )


MEMBERS = Members(clips=(("a", "f"), ("b", "w")), keys=(("a", "position", 2.0), ("b", "scale", 4.0)))


def made(project: Project | None = None, members: Members = MEMBERS) -> Project:
    return make_sequence(project or scene(), "Intro", members).project


def test_make_a_sequence_and_its_span() -> None:
    project = made()
    (seq,) = project.sequences
    assert seq.name == "Intro" and seq.id == "sequence-1"
    assert [(r.layer, r.clip) for r in seq.clips] == [("a", "f"), ("b", "w")]
    assert [(r.layer, r.track, r.t) for r in seq.keys] == [("a", "position", 2.0), ("b", "scale", 4.0)]
    assert span(project, seq) == (1.0, 4.0)
    assert sequence_of_clip(project, "b", "w") == seq and sequence_of_clip(project, "a", "i") is None
    assert sequence_of_key(project, "a", "position", 2.0) == seq
    assert sequence_of_key(project, "a", "position", 5.5) is None
    assert new_sequence_name(project) == "Sequence 1"
    sel = selection_of(seq)
    assert sel.clips == (("a", "f"), ("b", "w"))
    assert sel.keys == (("a", 2.0, ("position",)), ("b", 4.0, ("scale",)))


def test_make_refuses_empty_unknown_and_taken_members() -> None:
    with pytest.raises(edits.EditError, match="select"):
        make_sequence(scene(), "Empty", Members())
    with pytest.raises(edits.EditError, match="name"):
        make_sequence(scene(), "  ", MEMBERS)
    with pytest.raises(edits.EditError):
        make_sequence(scene(), "X", Members(clips=(("a", "nope"),)))
    with pytest.raises(edits.EditError):
        make_sequence(scene(), "X", Members(clips=(("zz", "f"),)))
    with pytest.raises(edits.EditError, match="no scale key"):
        make_sequence(scene(), "X", Members(keys=(("b", "scale", 5.0),)))
    project = made()
    with pytest.raises(edits.EditError, match="in 'Intro' already"):
        make_sequence(project, "Again", Members(clips=(("a", "f"),)))
    with pytest.raises(edits.EditError, match="in 'Intro' already"):
        make_sequence(project, "Again", Members(keys=(("a", "position", 2.0),)))
    with pytest.raises(ValidationError, match="two sequences"):  # the file format refuses it too
        Project.model_validate(
            {
                **project.model_dump(by_alias=True),
                "sequences": [
                    {"id": "s1", "name": "A", "clips": [{"layer": "a", "clip": "f"}]},
                    {"id": "s2", "name": "B", "clips": [{"layer": "a", "clip": "f"}]},
                ],
            }
        )


def test_members_from_the_timeline_picks() -> None:
    selection = shift_timing.Selection(clips=(("a", "f"),), keys=(("a", 5.5, None), ("b", 7.0, ("scale",))))
    members = members_from_selection(scene(), selection)
    assert members.clips == (("a", "f"),)
    assert members.keys == (("a", "position", 5.5), ("b", "scale", 7.0))


def test_dissolve_rename_and_colour() -> None:
    project = made()
    seq_id = project.sequences[0].id
    renamed = rename_sequence(project, seq_id, "Opening").project
    assert renamed.sequences[0].name == "Opening"
    coloured = set_sequence_colour(renamed, seq_id, "#22c55e").project
    assert coloured.sequences[0].colour == "#22c55e"
    with pytest.raises(edits.EditError):
        set_sequence_colour(renamed, seq_id, "green")
    with pytest.raises(edits.EditError):
        rename_sequence(project, seq_id, "")
    gone = dissolve_sequence(coloured, seq_id)
    assert gone.project.sequences == [] and gone.project.layers == project.layers
    assert gone.kind == "timing" and gone.layer_ids == frozenset()
    with pytest.raises(edits.EditError):
        dissolve_sequence(gone.project, seq_id)


def test_round_trip_and_a_file_without_sequences_saves_as_before() -> None:
    assert "sequences" not in scene().model_dump(by_alias=True)
    project = made()
    data = project.model_dump(by_alias=True)
    assert data["sequences"][0]["clips"][0] == {"layer": "a", "clip": "f"}
    assert "colour" not in data["sequences"][0]
    assert Project.model_validate_json(project.model_dump_json(by_alias=True)) == project


def test_move_shifts_every_member_and_keeps_them() -> None:
    project = made()
    edit = move_sequence(project, project.sequences[0].id, 2.0)
    a, b = edit.project.layer("a"), edit.project.layer("b")
    assert [c.start for c in a.clips] == [3.0, 5.0]  # the Indicate is not a member
    assert a.lifetime.in_ == 3.0  # the boundary clip's Appears at went with it
    assert [k.t for k in a.tracks["position"]] == [4.0, 5.5]
    assert b.clips[0].start == 4.0 and [k.t for k in b.tracks["scale"]] == [6.0, 7.0]
    seq = edit.project.sequences[0]
    assert span(edit.project, seq) == (3.0, 6.0)
    assert [(r.layer, r.track, r.t) for r in seq.keys] == [("a", "position", 4.0), ("b", "scale", 6.0)]
    assert move_sequence(project, seq.id, 0.0).project is project


def test_move_refuses_what_the_schema_refuses_and_grows_the_scene() -> None:
    project = made(members=Members(clips=(("a", "f"),)))
    with pytest.raises(edits.EditError, match="overlap"):
        move_sequence(project, project.sequences[0].id, 4.0)  # onto the Indicate at 5 s
    late = made(members=Members(clips=(("a", "i"),), keys=(("b", "scale", 7.0),)))
    grown = move_sequence(late, late.sequences[0].id, 6.0).project
    assert grown.layer("b").tracks["scale"][-1].t == 13.0
    assert grown.canvas.duration == 13.0
    assert span(grown, grown.sequences[0]) == (11.0, 13.0)
    keys = made(members=Members(keys=(("b", "scale", 7.0),)))
    early = move_sequence(keys, keys.sequences[0].id, -100.0).project  # never below 0 s
    assert span(early, early.sequences[0]) == (0.0, 0.0)


def test_retime_scales_about_the_start() -> None:
    project = made()  # 1 s .. 4 s
    edit = retime_sequence(project, project.sequences[0].id, 4.5)  # x1.5 about 1 s
    a, b = edit.project.layer("a"), edit.project.layer("b")
    assert [(c.id, c.start, c.duration) for c in a.clips] == [("f", 1.0, 1.5), ("i", 5.0, 1.0)]
    assert a.lifetime.in_ == 1.0
    assert (b.clips[0].start, b.clips[0].duration) == (2.5, 3.0)
    assert [k.t for k in a.tracks["position"]] == [2.5, 5.5]  # the 5.5 s key is not a member
    assert [k.t for k in b.tracks["scale"]] == [5.5, 7.0]
    seq = edit.project.sequences[0]
    assert span(edit.project, seq) == pytest.approx((1.0, 5.5))
    assert [(r.layer, r.track, r.t) for r in seq.keys] == [("a", "position", 2.5), ("b", "scale", 5.5)]
    assert edit.kind == "transform"


def test_retime_refuses_bad_lengths_and_collisions_with_the_reason() -> None:
    project = made()
    seq_id = project.sequences[0].id
    with pytest.raises(edits.EditError, match="above 0"):
        retime_sequence(project, seq_id, 0.0)
    with pytest.raises(edits.EditError, match="one frame"):
        retime_sequence(project, seq_id, 6.0)  # the scale key at 4 s would land on the one at 7 s
    keys = make_sequence(scene(), "Keys", Members(keys=(("a", "position", 2.0), ("a", "position", 5.5))))
    with pytest.raises(edits.EditError, match="one frame"):
        retime_sequence(keys.project, keys.project.sequences[0].id, 0.01)
    one = make_sequence(scene(), "One", Members(keys=(("a", "position", 2.0),))).project
    with pytest.raises(edits.EditError, match="no time"):
        retime_sequence(one, one.sequences[0].id, 2.0)
    fade = make_sequence(scene(), "Fade", Members(clips=(("a", "f"),), keys=(("a", "position", 5.5),)))
    with pytest.raises(edits.EditError, match="overlap"):  # the FadeIn would run over the Indicate
        retime_sequence(fade.project, fade.project.sequences[0].id, 22.5)


def test_duplicate_copies_clips_and_keys_as_a_new_sequence() -> None:
    project = made(members=Members(clips=(("b", "w"),), keys=(("b", "scale", 4.0), ("a", "position", 2.0))))
    seq_id = project.sequences[0].id
    edit = duplicate_sequence(project, seq_id, 7.0)
    new = edit.project
    assert len(new.sequences) == 2
    copy = new.sequences[1]
    assert copy.name == "Intro copy"
    assert copy.id != seq_id
    b = new.layer("b")
    assert [c.id for c in b.clips] == ["w", "create-1"]
    assert b.clips[1].start == 7.0 and b.clips[1].duration == 2.0
    assert [k.t for k in b.tracks["scale"]] == [4.0, 7.0, 9.0]
    assert [k.t for k in new.layer("a").tracks["position"]] == [2.0, 5.5, 7.0]
    assert span(new, copy) == (7.0, 9.0)
    assert new.sequences[0] == project.sequences[0]  # the original is untouched
    with pytest.raises(edits.EditError, match="already has a"):
        duplicate_sequence(project, seq_id, 5.0)  # the copied scale key would land on the 7 s key
    with pytest.raises(edits.EditError, match="overlap"):
        duplicate_sequence(project, seq_id, 3.0)  # the copied Create on top of the original
    with pytest.raises(edits.EditError):
        duplicate_sequence(project, seq_id, -1.0)


def test_members_stay_valid_when_members_are_deleted() -> None:
    project = made()
    seq_id = project.sequences[0].id
    one = edits.remove_clip(project, "a", "f").project
    assert [(r.layer, r.clip) for r in one.sequences[0].clips] == [("b", "w")]
    no_b = edits.remove_layers(one, ["b"]).project
    (seq,) = no_b.sequences
    assert (
        seq.id == seq_id and seq.clips == [] and [(r.layer, r.track) for r in seq.keys] == [("a", "position")]
    )
    nothing = edits.remove_keys(no_b, "a", 2.0).project
    assert nothing.sequences == []  # left empty: gone, in the same edit (one undo step)
    # deleting several picks at once, as the timeline's Delete does
    picked = shift_timing.remove_items(project, shift_timing.Selection(clips=(("a", "f"), ("b", "w"))))
    assert picked.project.sequences[0].clips == []


def test_moving_a_member_key_alone_keeps_it_in_the_sequence() -> None:
    project = made()
    moved = edits.retime_keys(project, "a", 2.0, 2.5).project
    assert ("a", "position", 2.5) in {(r.layer, r.track, r.t) for r in moved.sequences[0].keys}
    shifted = shift_timing.shift_timing(
        project, shift_timing.Selection(keys=(("b", 4.0, None),)), 0.5
    ).project
    assert ("b", "scale", 4.5) in {(r.layer, r.track, r.t) for r in shifted.sequences[0].keys}
    whole = shift_timing.shift_timing(project, shift_timing.Selection(layers=("a",)), 1.0).project
    assert ("a", "position", 3.0) in {(r.layer, r.track, r.t) for r in whole.sequences[0].keys}
    rippled = ripple.ripple(project, 0.5, 1.0).project
    assert span(rippled, rippled.sequences[0]) == (2.0, 5.0)
    # a duplicated clip is not a member: its copy is a clip of its own
    assert sequence_of_clip(project, "a", "i") is None


def test_unknown_members_in_a_file_are_dropped_on_load() -> None:
    data = scene().model_dump(by_alias=True)
    data["sequences"] = [
        Sequence(
            id="s",
            name="Old",
            clips=[SequenceClip(layer="a", clip="f"), SequenceClip(layer="gone", clip="x")],
            keys=[SequenceKey(layer="a", track="scale", t=1.0)],
        ).model_dump(),
        Sequence(id="t", name="Empty", clips=[SequenceClip(layer="gone", clip="x")]).model_dump(),
    ]
    project = Project.model_validate(data)
    assert [(s.id, [(r.layer, r.clip) for r in s.clips], s.keys) for s in project.sequences] == [
        ("s", [("a", "f")], [])
    ]


def test_sequences_change_no_frame_and_no_cached_span() -> None:
    plain = scene()
    grouped = made(plain)
    assert frame_cache.changed_spans(plain, grouped) == []
    assert frame_cache.changed_layers(plain, grouped) == set()
    edit = make_sequence(plain, "Intro", MEMBERS)
    assert edit.kind == "timing" and edit.layer_ids == frozenset()
    for t in (0.0, 1.5, 3.0):
        before = render_frame(make_camera(plain.canvas), Evaluator(plain).frame(t))
        after = render_frame(make_camera(grouped.canvas), Evaluator(grouped).frame(t))
        assert np.array_equal(before, after)
    assert to_python(plain, "Seq").code == to_python(grouped, "Seq").code


def one_layer_sequence() -> Project:
    """Several clips and keys on ONE layer, appearing at 1 s and disappearing at 4 s (the first clip's start
    and the last one's end), with a key before the layer appears so the sequence starts before the layer."""
    layer = Layer(
        id="m",
        spec=Spec(type="Square"),
        lifetime=Lifetime(in_=1.0, out=4.0),
        clips=[
            Clip(id="c1", kind="FadeIn", start=1.0, duration=1.0),
            Clip(id="c2", kind="Indicate", start=2.0, duration=1.0),
            Clip(id="c3", kind="Indicate", start=3.0, duration=1.0),
        ],
        tracks={
            "rotation": [
                Keyframe(t=0.0, value=0.0),
                Keyframe(t=2.0, value=45.0),
                Keyframe(t=4.0, value=90.0),
            ],
        },
    )
    project = Project(canvas=Canvas(width_px=320, height_px=180, fps=10, duration=12.0), layers=[layer])
    members = Members(
        clips=(("m", "c1"), ("m", "c2"), ("m", "c3")),
        keys=(("m", "rotation", 0.0), ("m", "rotation", 2.0), ("m", "rotation", 4.0)),
    )
    return make_sequence(project, "Run", members).project


def lifetimes(project: Project) -> dict:
    layer = project.layer("m")
    return {
        "in": layer.lifetime.in_,
        "out": layer.lifetime.out,
        "clips": [(c.id, c.start, c.duration) for c in layer.clips],
        "keys": [(k.t, k.value) for k in layer.tracks["rotation"]],
    }


@pytest.mark.parametrize("length", [8.0, 2.0, 6.0])
def test_retiming_several_clips_on_one_layer_scales_each_and_the_lifetime_once(length: float) -> None:
    project = one_layer_sequence()
    seq_id = project.sequences[0].id
    before = project.model_dump(by_alias=True)
    factor = length / 4.0  # the sequence lasts 0 s .. 4 s
    edit = retime_sequence(project, seq_id, length)
    assert project.model_dump(by_alias=True) == before  # the edit never touches the project it was given
    after = lifetimes(edit.project)
    assert after["clips"] == [
        (cid, pytest.approx(start * factor), pytest.approx(factor))
        for cid, start in (("c1", 1.0), ("c2", 2.0), ("c3", 3.0))
    ]
    # Appears at / Disappears at sat on the first clip's start and the last clip's end: scaled with them once
    assert after["in"] == pytest.approx(1.0 * factor)
    assert after["out"] == pytest.approx(4.0 * factor)
    assert [t for t, _ in after["keys"]] == pytest.approx([0.0, 2.0 * factor, 4.0 * factor], abs=0.05)
    seq = edit.project.sequences[0]
    assert [r.t for r in seq.keys] == [k for k, _ in after["keys"]]  # the sequence follows its keys
    assert span(edit.project, seq) == pytest.approx((0.0, length), abs=0.05)
    # and the scaled sequence scales back to what it was (undo restores the snapshot; this checks the maths)
    back = retime_sequence(edit.project, seq_id, 4.0).project
    assert lifetimes(back)["in"] == pytest.approx(1.0) and lifetimes(back)["out"] == pytest.approx(4.0)
    assert [c[1:] for c in lifetimes(back)["clips"]] == [
        (pytest.approx(1.0), pytest.approx(1.0)),
        (pytest.approx(2.0), pytest.approx(1.0)),
        (pytest.approx(3.0), pytest.approx(1.0)),
    ]


def test_moving_several_clips_on_one_layer_carries_the_lifetime_once() -> None:
    project = one_layer_sequence()
    before = project.model_dump(by_alias=True)
    edit = move_sequence(project, project.sequences[0].id, 2.0)
    assert project.model_dump(by_alias=True) == before
    after = lifetimes(edit.project)
    assert [(cid, start) for cid, start, _ in after["clips"]] == [("c1", 3.0), ("c2", 4.0), ("c3", 5.0)]
    assert (after["in"], after["out"]) == (3.0, 6.0)
    assert [t for t, _ in after["keys"]] == [2.0, 4.0, 6.0]
    assert span(edit.project, edit.project.sequences[0]) == (2.0, 6.0)
