"""Render options (P6b.5, ADR 0042): sizes, the frame window, the sound and .srt cut to it, and
real exports through ``export_video`` and ``manim-studio render`` flags."""

from __future__ import annotations

import av
import numpy as np
import pytest

from manim_studio import cli
from manim_studio.core.engine.evaluator import Evaluator
from manim_studio.core.model.schema import AudioClip, Canvas, Clip, Cue, Layer, Project, Spec, SubtitleStyle
from manim_studio.core.sound import audio
from manim_studio.render.cairo_export import export_video, frame_times, make_camera, render_frame
from manim_studio.render.options import (
    OptionsError,
    RenderOptions,
    apply_options,
    audio_window,
    even,
    frame_window,
    parse_size,
    preset_sizes,
    size_for_height,
    window_cues,
)

CANVAS = Canvas(width_px=160, height_px=90, fps=10, duration=2.0, background="#202020")


def project(**fields) -> Project:
    layers = [
        Layer(
            id="a",
            spec=Spec(type="Square", params={"side_length": 4}, style={"fill": "#3b82f6", "fill_opacity": 1}),
            clips=[Clip(id="c", kind="GrowFromCenter", start=0, duration=2.0)],
        )
    ]
    return Project(canvas=fields.pop("canvas", CANVAS), layers=layers, **fields)


def decode(path) -> list[np.ndarray]:
    with av.open(str(path)) as container:
        return [frame.to_ndarray(format="rgb24") for frame in container.decode(video=0)]


# -- sizes -----------------------------------------------------------------------------


def test_even_rounds_to_the_nearest_even_number_and_never_below_two() -> None:
    assert [even(v) for v in (853.33, 854, 855, 1, 0)] == [854, 854, 856, 2, 2]


def test_parse_size() -> None:
    assert parse_size("1280x720") == (1280, 720)
    assert parse_size("161X91") == (162, 92)  # H.264 4:2:0 needs even sides
    for bad in ("1280", "axb", "0x10", "-4x4", "1x2x3"):
        with pytest.raises(OptionsError):
            parse_size(bad)


def test_presets_keep_the_canvas_aspect_ratio_with_even_sides() -> None:
    sixteen_nine = preset_sizes(Canvas(width_px=1920, height_px=1080))
    assert sixteen_nine["480p"] == (854, 480) and sixteen_nine["1080p"] == (1920, 1080)
    assert sixteen_nine["2160p"] == (3840, 2160) and list(sixteen_nine) == [
        "480p",
        "720p",
        "1080p",
        "1440p",
        "2160p",
    ]
    assert size_for_height(Canvas(width_px=640, height_px=480), 720) == (960, 720)  # 4:3
    assert size_for_height(Canvas(width_px=161, height_px=91), 720) == (1274, 720)  # odd canvas
    assert all(
        w % 2 == 0 and h % 2 == 0 for w, h in preset_sizes(Canvas(width_px=333, height_px=77)).values()
    )


# -- options and canvas ------------------------------------------------------------------


def test_options_are_validated() -> None:
    for bad in (
        {"width": 100},
        {"width": 1, "height": 1},
        {"fps": 0},
        {"crf": 52},
        {"crf": -1},
        {"subtitles": "yes"},
    ):
        with pytest.raises(OptionsError):
            RenderOptions(**bad)


def test_options_become_cli_flags_and_defaults_leave_none() -> None:
    assert RenderOptions().to_args() == []
    options = RenderOptions(width=854, height=480, fps=24, start=0.5, end=1.5, crf=28, subtitles="srt")
    assert options.to_args() == [
        "--size",
        "854x480",
        "--fps",
        "24",
        "--start",
        "0.5",
        "--end",
        "1.5",
        "--crf",
        "28",
        "--subtitles",
        "srt",
    ]
    parsed = cli.build_parser().parse_args(["render", "p.json", "o.mp4", *options.to_args()])
    assert (parsed.size, parsed.fps, parsed.start, parsed.end, parsed.crf, parsed.subtitles) == (
        "854x480",
        24,
        0.5,
        1.5,
        28,
        "srt",
    )


def test_apply_options_sets_size_and_fps_and_keeps_the_framing() -> None:
    base = Canvas(width_px=160, height_px=90, fps=10, duration=2.0, frame_height=6.0)
    out = apply_options(project(canvas=base), RenderOptions(width=321, height=181, fps=25)).canvas
    assert (out.width_px, out.height_px, out.fps) == (322, 182, 25)
    assert out.duration == 2.0 and out.frame_height == 6.0 and out.background == base.background
    same = apply_options(project(canvas=base), RenderOptions())
    assert same.canvas == base and same.subtitle_style == SubtitleStyle()


@pytest.mark.parametrize("mode, burn_in", [("burn", True), ("srt", False), ("none", False), (None, True)])
def test_apply_options_sets_burn_in_from_the_subtitle_mode(mode, burn_in) -> None:
    out = apply_options(project(), RenderOptions(subtitles=mode))
    assert out.subtitle_style.burn_in is burn_in  # None: the style's own (burned in by default)
    off = project(subtitle_style=SubtitleStyle(burn_in=False))
    assert apply_options(off, RenderOptions()).subtitle_style.burn_in is False


# -- the frame window ----------------------------------------------------------------------


def test_the_window_is_the_whole_scene_by_default() -> None:
    assert frame_window(CANVAS, RenderOptions()) == (0, 20)
    assert frame_window(CANVAS, RenderOptions(fps=30)) == (0, 60)


def test_the_window_rounds_both_ends_to_the_frame_grid() -> None:
    assert frame_window(CANVAS, RenderOptions(start=0.5, end=1.25)) == (5, 13)  # 12.5 -> 13: halves go up
    wide = Canvas(width_px=160, height_px=90, fps=24, duration=4.0)
    assert frame_window(wide, RenderOptions(start=1.01, end=2.02)) == (24, 48)
    assert frame_window(wide, RenderOptions(fps=30, start=1.01, end=2.02)) == (30, 61)
    assert frame_window(CANVAS, RenderOptions(start=1.5)) == (15, 20)  # to the end
    assert frame_window(CANVAS, RenderOptions(fps=5, start=0.5, end=1.5)) == (3, 8)  # not Python's 2 and 8


def test_the_end_is_clamped_to_the_scene() -> None:
    assert frame_window(CANVAS, RenderOptions(start=1.0, end=99.0)) == (10, 20)


@pytest.mark.parametrize(
    "fields, fps, message",
    [
        ({"start": 2.0}, 10, "after the scene ends"),
        ({"start": 3.0, "end": 4.0}, 10, "after the scene ends"),
        ({"start": 1.0, "end": 1.0}, 10, "must end after"),
        ({"start": 1.0, "end": 0.5}, 10, "must end after"),
        ({"start": 0.04, "end": 0.05}, 24, "shorter than one frame at 24 fps"),
        ({"start": -1.0}, 10, "before 0"),
    ],
)
def test_an_empty_range_is_refused_with_a_message(fields, fps, message) -> None:
    with pytest.raises(OptionsError, match=message):
        frame_window(CANVAS, RenderOptions(fps=fps, **fields))
    assert frame_window(CANVAS, RenderOptions(fps=30, start=0.04, end=0.05)) == (1, 2)  # one frame at 30


# -- cutting sound and subtitles --------------------------------------------------------------


def test_cues_are_shifted_clipped_and_dropped_outside() -> None:
    cues = [
        Cue(id="a", start=0.0, end=1.0, text="before"),
        Cue(id="b", start=1.5, end=3.5, text="straddles both edges"),
        Cue(id="c", start=4.0, end=5.0, text="inside"),
        Cue(id="d", start=6.0, end=7.0, text="after"),
    ]
    out = window_cues(cues, 2.0, 4.5)
    assert [(c.id, c.start, c.end) for c in out] == [("b", 0.0, 1.5), ("c", 2.0, 2.5)]
    assert out[0].text == "straddles both edges"
    assert [c.id for c in window_cues(cues, 1.0, 1.5)] == []  # between cues: nothing


def test_the_sound_is_cut_at_the_window_and_padded_with_silence() -> None:
    ramp = np.tile(np.arange(10 * audio.RATE, dtype=np.float32), (2, 1))  # each sample holds its index
    cut = audio_window(ramp, 5, 15, 10)  # frames 5..15 at 10 fps = seconds 0.5 to 1.5
    assert cut.shape == (2, audio.RATE) and cut[0, 0] == audio.RATE // 2 and cut.flags["C_CONTIGUOUS"]
    short = audio_window(ramp[:, :100], 0, 20, 10)  # a mix shorter than the video: silence after it
    assert short.shape == (2, 2 * audio.RATE) and short[0, 99] == 99 and not short[:, 100:].any()


# -- real exports -----------------------------------------------------------------------------


def test_a_range_renders_exactly_those_frames(tmp_path) -> None:
    proj = project()
    out = export_video(proj, tmp_path / "r.mp4", options=RenderOptions(start=0.5, end=1.3)).path
    frames = decode(out)
    assert len(frames) == 8  # frames 5..12 of 20
    camera, evaluator = make_camera(proj.canvas), Evaluator(proj)
    for k, decoded in enumerate(frames):
        expected = render_frame(camera, evaluator.frame((5 + k) / 10))[:, :, :3].astype(int)
        assert np.abs(decoded.astype(int) - expected).mean() < 4, f"frame {k}"
    assert frame_times(proj.canvas, 5, 13) == pytest.approx([0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2])


def test_progress_counts_the_frames_of_the_range(tmp_path) -> None:
    calls = []
    export_video(
        project(),
        tmp_path / "p.mp4",
        progress=lambda done, total: calls.append((done, total)),
        options=RenderOptions(start=1.0),
    )
    assert calls == [(i, 10) for i in range(1, 11)]


def test_size_and_fps_change_the_video(tmp_path) -> None:
    out = export_video(project(), tmp_path / "s.mp4", options=RenderOptions(width=80, height=46, fps=5)).path
    frames = decode(out)
    assert len(frames) == 10 and frames[0].shape == (46, 80, 3)
    with av.open(str(out)) as container:
        assert float(container.streams.video[0].average_rate) == 5.0


def test_an_odd_size_is_made_even(tmp_path) -> None:
    out = export_video(project(), tmp_path / "o.mp4", options=RenderOptions(width=81, height=47)).path
    assert decode(out)[0].shape == (48, 82, 3)


def test_a_higher_crf_makes_a_smaller_file(tmp_path) -> None:
    sizes = {
        crf: export_video(project(), tmp_path / f"q{crf}.mp4", options=RenderOptions(crf=crf))
        .path.stat()
        .st_size
        for crf in (0, 18, 51)
    }
    assert sizes[0] > sizes[18] > sizes[51]


def test_an_empty_range_writes_nothing(tmp_path) -> None:
    with pytest.raises(OptionsError):
        export_video(project(), tmp_path / "x.mp4", options=RenderOptions(start=5.0))
    assert not list(tmp_path.iterdir())


def cues() -> list[Cue]:
    return [Cue(id="s1", start=0.2, end=0.8, text="one"), Cue(id="s2", start=1.2, end=1.8, text="two")]


def test_the_srt_follows_the_subtitle_mode(tmp_path) -> None:
    proj = project(subtitles=cues())
    assert export_video(proj, tmp_path / "default.mp4").path.with_suffix(".srt").exists()
    assert (
        export_video(proj, tmp_path / "burn.mp4", options=RenderOptions(subtitles="burn"))
        .path.with_suffix(".srt")
        .exists()
    )
    assert (
        export_video(proj, tmp_path / "srt.mp4", options=RenderOptions(subtitles="srt"))
        .path.with_suffix(".srt")
        .exists()
    )
    none = export_video(proj, tmp_path / "none.mp4", options=RenderOptions(subtitles="none")).path
    assert not none.with_suffix(".srt").exists()


def test_burned_in_subtitles_are_drawn_only_when_asked(tmp_path) -> None:
    proj = project(subtitles=[Cue(id="s", start=0.0, end=2.0, text="HELLO HELLO HELLO")])
    burned = decode(export_video(proj, tmp_path / "b.mp4", options=RenderOptions(subtitles="burn")).path)
    clean = decode(export_video(proj, tmp_path / "c.mp4", options=RenderOptions(subtitles="srt")).path)
    band = slice(-14, None)  # the bottom of the frame, where the subtitle band is
    assert np.abs(burned[10][band].astype(int) - clean[10][band].astype(int)).mean() > 2


def test_a_ranged_srt_is_shifted_and_clipped(tmp_path) -> None:
    proj = project(subtitles=cues())
    out = export_video(proj, tmp_path / "w.mp4", options=RenderOptions(start=0.5, end=1.5)).path
    text = out.with_suffix(".srt").read_text(encoding="utf-8")
    assert "00:00:00,000 --> 00:00:00,300" in text and "one" in text  # 0.5-0.8 of cue one
    assert "00:00:00,700 --> 00:00:01,000" in text and "two" in text  # 1.2-1.5 of cue two
    outside = export_video(proj, tmp_path / "x.mp4", options=RenderOptions(start=0.9, end=1.1)).path
    assert not outside.with_suffix(".srt").exists()  # no cue in the range: no file


def decoded_track(path) -> np.ndarray:
    with av.open(str(path)) as container:
        return np.concatenate([f.to_ndarray() for f in container.decode(audio=0)], axis=1)


def test_the_sound_of_a_range_starts_when_the_picture_does(tmp_path) -> None:
    """A sound at 0.5 s plays at 0.2 s in a video that starts at 0.3 s (AAC adds ~21 ms of priming)."""
    wav = tmp_path / "block.wav"
    audio.write_wav(np.full((2, audio.RATE), 0.5, np.float32), wav)
    sound = AudioClip(id="k", path=str(wav), start=0.5, duration=1.0)
    proj = project(audio=[sound])

    def onset(options: RenderOptions, name: str) -> float:
        track = decoded_track(export_video(proj, tmp_path / name, options=options).path)
        return int(np.argmax(np.abs(track[0]) > 0.1)) / audio.RATE

    assert onset(RenderOptions(), "whole.mp4") == pytest.approx(0.5, abs=0.06)
    assert onset(RenderOptions(start=0.3, end=1.9), "cut.mp4") == pytest.approx(0.2, abs=0.06)
    track = decoded_track(
        export_video(proj, tmp_path / "len.mp4", options=RenderOptions(start=0.3, end=0.9)).path
    )
    assert track.shape[1] / audio.RATE == pytest.approx(0.6, abs=0.1)  # the sound is as long as the picture


# -- the command line ---------------------------------------------------------------------------


def write_project(tmp_path, proj: Project):
    path = tmp_path / "p.json"
    path.write_text(proj.model_dump_json(by_alias=True), encoding="utf-8")
    return path


def test_cli_render_with_options(tmp_path, capsys) -> None:
    path, out = write_project(tmp_path, project()), tmp_path / "o.mp4"
    args = ["--size", "81x47", "--fps", "5", "--start", "0.4", "--end", "1.4", "--crf", "30"]
    assert cli.main(["render", str(path), str(out), *args]) == 0
    frames = decode(out)
    assert len(frames) == 5 and frames[0].shape == (48, 82, 3)


@pytest.mark.parametrize(
    "args, message",
    [
        (["--size", "big"], "size must look like"),
        (["--fps", "0"], "fps must be at least 1"),
        (["--crf", "99"], "between 0 and 51"),
        (["--start", "5"], "after the scene ends"),
        (["--start", "1", "--end", "0.5"], "must end after"),
    ],
)
def test_cli_render_refuses_bad_options_with_exit_2(tmp_path, capsys, args, message) -> None:
    path, out = write_project(tmp_path, project()), tmp_path / "o.mp4"
    assert cli.main(["render", str(path), str(out), *args]) == 2
    assert message in capsys.readouterr().err and not out.exists()


def test_cli_subtitles_none_writes_no_srt(tmp_path) -> None:
    path = write_project(tmp_path, project(subtitles=cues()))
    assert cli.main(["render", str(path), str(tmp_path / "a.mp4"), "--subtitles", "none"]) == 0
    assert not (tmp_path / "a.srt").exists()
    assert cli.main(["render", str(path), str(tmp_path / "b.mp4"), "--subtitles", "srt"]) == 0
    assert (tmp_path / "b.srt").exists()


@pytest.mark.slow
def test_code_layers_are_rendered_at_the_size_being_exported(tmp_path) -> None:
    """A code layer's frames are cached per canvas size; the CLI renders them at the export's size."""
    from manim_studio.core.code.code_cache import CodeCache
    from manim_studio.core.engine.evaluator import code_key

    code = "class A(Scene):\n    def construct(self):\n        self.add(Dot())\n        self.wait(0.5)\n"
    layer = Layer(id="code", spec=Spec(type="Code", params={"code": code}))
    original = Project(canvas=Canvas(width_px=160, height_px=90, fps=10, duration=1.0), layers=[layer])
    path, cache = write_project(tmp_path, original), tmp_path / "cache"
    args = ["--cache-dir", str(cache), "--trust-code", "--size", "80x46"]
    assert cli.main(["render", str(path), str(tmp_path / "o.mp4"), *args]) == 0
    sized = apply_options(original, RenderOptions(width=80, height=46))
    frames = CodeCache(cache / "code")
    assert frames.has(code_key(sized, layer)) and not frames.has(code_key(original, layer))
    assert decode(tmp_path / "o.mp4")[0].shape == (46, 80, 3)
