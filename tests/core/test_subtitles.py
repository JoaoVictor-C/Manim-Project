"""The subtitle track (P5a.1, ADR 0035): the model, .srt files, wrapping, drawing over the frame,
what an edit re-renders, the export's .srt and the Python export."""

from __future__ import annotations

import random
import subprocess
import sys

import av
import numpy as np
import pytest
from pydantic import ValidationError
from tests.support import max_diff

from manim_studio.core import adapter, edits, subtitles
from manim_studio.core.evaluator import Evaluator
from manim_studio.core.frame_cache import changed_layers, changed_spans
from manim_studio.core.python_export import readable_problems, to_python
from manim_studio.core.schema import Canvas, Cue, Keyframe, Layer, Project, Spec, SubtitleStyle
from manim_studio.render.cairo_export import export_video, frame_times, make_camera, render_frame

CANVAS = Canvas(width_px=320, height_px=180, fps=10, duration=4.0)
STYLE = SubtitleStyle()


def project(*cues: Cue, style: SubtitleStyle = STYLE, layers=()) -> Project:
    return Project(canvas=CANVAS, layers=list(layers), subtitles=list(cues), subtitle_style=style)


def cue(cue_id: str, start: float, end: float, text: str) -> Cue:
    return Cue(id=cue_id, start=start, end=end, text=text)


HELLO = cue("cue-1", 0.5, 2.0, "Hello there")
WORLD = cue("cue-2", 2.5, 3.6, "A second line")


# -- the model -----------------------------------------------------------------------------


def test_cues_form_one_lane_in_time_order() -> None:
    p = project(WORLD, HELLO)
    assert [c.id for c in p.subtitles] == ["cue-1", "cue-2"]
    with pytest.raises(ValidationError, match="overlap"):
        project(HELLO, cue("cue-3", 1.5, 3.0, "late"))
    with pytest.raises(ValidationError, match="end after"):
        cue("x", 1.0, 1.0, "")
    with pytest.raises(ValidationError, match="duplicate"):
        project(cue("dot", 0, 1, "a"), layers=[Layer(id="dot", spec=Spec(type="Dot"))])


def test_files_without_subtitles_save_as_before() -> None:
    plain = Project(canvas=CANVAS)
    assert {"subtitles", "subtitle_style"}.isdisjoint(plain.model_dump(by_alias=True))
    styled = project(HELLO, style=SubtitleStyle(font_size=30, burn_in=False))
    again = Project.model_validate_json(styled.model_dump_json(by_alias=True))
    assert again == styled and again.subtitle_style.font_size == 30


def test_subtitle_edits_drop_no_frame_and_layer_edits_keep_the_subtitles() -> None:
    base = project(layers=[Layer(id="dot", spec=Spec(type="Dot"))])
    added = edits.add_cue(base, 0.5, 2.0, "Hello")
    assert added.kind == "timing" and added.layer_ids == frozenset()
    assert added.project.subtitles == [Cue(id="cue-1", start=0.5, end=2.0, text="Hello")]
    assert changed_layers(base, added.project) == set()  # not "every frame"
    renamed = edits.update_cue(added.project, "cue-1", text="Hi")
    assert renamed.project.subtitles[0].text == "Hi"
    moved_dot = edits.update_layer(renamed.project, "dot", name="Dot")
    assert moved_dot.project.subtitles == renamed.project.subtitles
    with_sound = edits.add_audio(moved_dot.project, "x.wav", 0.0, 1.0)
    assert with_sound.project.subtitles == renamed.project.subtitles
    styled = edits.set_subtitle_style(with_sound.project, font_size=32)
    assert styled.project.subtitle_style.font_size == 32 and styled.project.audio
    with pytest.raises(ValidationError):
        edits.update_cue(edits.add_cue(styled.project, 2.0, 3.0).project, "cue-2", start=1.5)
    assert edits.remove_cue(styled.project, "cue-1").project.subtitles == []
    with pytest.raises(edits.EditError):
        edits.remove_cue(base, "cue-1")
    imported = edits.set_subtitles(base, [HELLO, WORLD]).project
    assert [c.id for c in imported.subtitles] == ["cue-1", "cue-2"]


def test_a_new_cue_goes_at_the_playhead_until_the_next_one() -> None:
    p = project(HELLO, WORLD)
    assert subtitles.place_cue(p, 0.0) == (0.0, 0.5)  # stops at the next cue
    assert subtitles.place_cue(p, 1.0) == (2.0, 2.5)  # inside a cue: after it
    assert subtitles.place_cue(p, 3.8) == pytest.approx((3.8, 4.0))  # stops at the end
    assert subtitles.place_cue(project(cue("a", 0, 4.0, "all")), 1.0) is None  # no room
    assert subtitles.place_cue(Project(canvas=CANVAS), 1.0) == (1.0, 3.0)  # 2 s by default


# -- .srt files ----------------------------------------------------------------------------


SRT = (
    "\ufeff1\r\n00:00:00,500 --> 00:00:02,000\r\nHello <i>there</i>\r\n\r\n"
    "00:00:01.900 --> 00:00:03.250\r\n{\\an8}Overlapping, generated\r\nsecond line\r\n\r\n"
    "garbage without times\r\n\r\n"
    "7\r\n00:01:02,5 --> 00:01:04,000\r\nLate\r\n"
)


def test_srt_files_are_read_tolerantly_and_written_back() -> None:
    cues = subtitles.read_srt(SRT)
    assert [(c.id, c.start, c.end, c.text) for c in cues] == [
        ("cue-1", 0.5, 1.9, "Hello there"),  # trimmed to where the next one starts
        ("cue-2", 1.9, 3.25, "Overlapping, generated\nsecond line"),
        ("cue-3", 62.5, 64.0, "Late"),
    ]
    text = subtitles.write_srt(cues)
    assert text.startswith("1\n00:00:00,500 --> 00:00:01,900\nHello there\n\n2\n")
    assert subtitles.read_srt(text) == cues
    assert subtitles.write_srt([]) == ""


# -- wrapping and drawing ------------------------------------------------------------------------


def test_long_lines_wrap_between_words_and_keep_their_own_breaks() -> None:
    style = SubtitleStyle(max_width=9.0)  # 50 characters a line at size 26
    words = "The derivative measures how fast a function changes at a single instant in time"
    lines = subtitles.wrap(words, style)
    assert len(lines) == 2 and all(len(line) <= 50 for line in lines) and " ".join(lines) == words
    assert subtitles.wrap("one\ntwo", style) == ["one", "two"]
    assert subtitles.wrap("   ", style) == []
    bigger = SubtitleStyle(max_width=9.0, font_size=52)
    assert len(subtitles.wrap(words, bigger)) == 4  # half the characters a line


def test_a_line_of_wide_letters_is_shrunk_to_fit() -> None:
    style = SubtitleStyle(max_width=6.0)
    built = adapter.subtitle_mobject("W" * 33, style)  # one word: no break possible
    assert built.width <= 6.0 + 0.5 + 1e-6  # the band's padding around the text
    assert built[1].width == pytest.approx(6.0)
    centre = built.get_center()
    assert centre[1] == pytest.approx(STYLE.y) and centre[0] == pytest.approx(0)


def test_the_subtitle_is_drawn_over_the_layers_but_is_not_a_layer() -> None:
    square = Layer(id="sq", spec=Spec(type="Square", params={"side_length": 8}, style={"fill": "#ef4444"}))
    p = project(HELLO, layers=[square])
    evaluator = Evaluator(p)
    assert [layer_id for layer_id, _ in evaluator.frame_layers(1.0)] == ["sq"]
    drawn = evaluator.frame(1.0)
    assert len(drawn) == 2 and drawn[-1] is evaluator.overlay(1.0)[0]
    assert evaluator.overlay(0.2) == [] and evaluator.overlay(2.2) == []
    hidden = p.model_copy(update={"subtitle_style": SubtitleStyle(burn_in=False)})
    assert Evaluator(hidden).overlay(1.0) == []
    assert Evaluator(project(cue("e", 0, 1, "  "))).overlay(0.5) == []


def test_subtitles_fade_in_and_out() -> None:
    evaluator = Evaluator(project(HELLO))
    band_opacity = STYLE.band_opacity
    for t, alpha in ((0.5, 0.0), (0.5 + STYLE.fade / 2, 0.5), (1.0, 1.0), (2.0 - STYLE.fade / 2, 0.5)):
        band, text = evaluator.overlay(t)[0]
        assert band.get_fill_opacity() == pytest.approx(band_opacity * alpha, abs=1e-6), t
        assert text[0].get_fill_opacity() == pytest.approx(alpha, abs=1e-6), t


def test_frames_with_subtitles_are_the_same_in_any_order() -> None:
    moving = Layer(
        id="dot",
        spec=Spec(type="Dot"),
        tracks={"position": [Keyframe(t=0, value=(-3.0, 0.0)), Keyframe(t=4, value=(3.0, 0.0))]},
    )
    p = project(HELLO, WORLD, layers=[moving])
    camera = make_camera(CANVAS)
    times = frame_times(CANVAS)
    played = [render_frame(camera, Evaluator(p).frame(t)) for t in times]
    evaluator = Evaluator(p)
    for i in random.Random(2).sample(range(len(times)), len(times)):
        assert max_diff(render_frame(camera, evaluator.frame(times[i])), played[i]) == 0, times[i]
    assert max_diff(played[10], played[2]) > 50  # something was drawn at 1.0 s that 0.2 s lacks


# -- what an edit re-renders -----------------------------------------------------------------------


def test_render_ahead_redraws_only_the_edited_cues() -> None:
    p = project(HELLO, WORLD)
    retext = edits.update_cue(p, "cue-2", text="Changed").project
    assert changed_spans(p, retext) == [(2.5, 3.6)]
    moved = edits.update_cue(p, "cue-1", start=0.2, end=1.0).project
    assert changed_spans(p, moved) == [(0.2, 2.0)]  # old and new spans
    restyled = edits.set_subtitle_style(p, colour="#facc15").project
    assert changed_spans(p, restyled) == [(0.5, 2.0), (2.5, 3.6)]
    layer = edits.add_layer(p, Spec(type="Dot"), layer_id="dot").project
    assert changed_spans(p, layer) == [(0.0, float("inf"))]  # a layer's own lifetime, not the cues


# -- export ------------------------------------------------------------------------------------


def test_the_export_burns_subtitles_in_and_writes_an_srt_beside_the_video(tmp_path) -> None:
    p = project(HELLO, WORLD)
    out = tmp_path / "talk.mp4"
    export_video(p, out)
    assert (tmp_path / "talk.srt").read_text(encoding="utf-8") == subtitles.write_srt(p.subtitles)
    with av.open(str(out)) as container:
        frames = [f.to_ndarray(format="rgb24") for f in container.decode(video=0)]
    camera = make_camera(CANVAS)
    for t in (1.0, 3.0):
        i = round(t * CANVAS.fps)
        expected = render_frame(camera, Evaluator(p).frame(t))[:, :, :3].astype(int)
        assert np.abs(frames[i].astype(int) - expected).mean() < 2, t
        assert np.abs(frames[i].astype(int) - frames[0].astype(int)).sum() > 0  # not a blank frame
    hidden = p.model_copy(update={"subtitle_style": SubtitleStyle(burn_in=False)})
    export_video(hidden, tmp_path / "clean.mp4")
    assert (tmp_path / "clean.srt").exists()
    with av.open(str(tmp_path / "clean.mp4")) as container:
        clean = [f.to_ndarray(format="rgb24") for f in container.decode(video=0)]
    assert max(int(np.abs(f.astype(int) - clean[0].astype(int)).max()) for f in clean) <= 2  # nothing drawn


def test_python_exports_carry_the_subtitles() -> None:
    burned = project(HELLO)
    assert readable_problems(burned) == ["subtitles: burned into the frames"]
    sidecar = burned.model_copy(update={"subtitle_style": SubtitleStyle(burn_in=False)})
    export = to_python(sidecar, "Talk")
    assert export.readable
    assert "self.add_subcaption('Hello there', duration=1.5, offset=0.5)" in export.code


@pytest.mark.slow
def test_manim_renders_the_same_srt(tmp_path) -> None:
    for name, style in (("Exact", STYLE), ("Readable", SubtitleStyle(burn_in=False))):
        p = project(HELLO, WORLD, style=style, layers=[Layer(id="dot", spec=Spec(type="Dot"))])
        scene = tmp_path / f"{name.lower()}.py"
        scene.write_text(to_python(p, name).code, encoding="utf-8")
        done = subprocess.run(
            [sys.executable, "-m", "manim", "render", str(scene), name, "--media_dir", str(tmp_path / name)],
            capture_output=True,
            text=True,
            cwd=tmp_path,
        )
        assert done.returncode == 0, done.stderr[-2000:]
        srt = next((tmp_path / name).rglob(f"{name}.srt")).read_text(encoding="utf-8")
        assert subtitles.read_srt(srt) == p.subtitles, name
