"""Resumable exports (ADR 0081): segments in a work folder, joined at the end, resumed after a stop."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import av
import numpy as np
import pytest

from manim_studio import cli
from manim_studio.core.model.schema import AudioClip, Canvas, Clip, Layer, Project, Spec
from manim_studio.core.sound import audio
from manim_studio.render import cairo_export, encoders, resume
from manim_studio.render.cairo_export import export_video, partial_path
from manim_studio.render.options import OptionsError, RenderOptions

CANVAS = Canvas(width_px=160, height_px=90, fps=10, duration=3.5, background="#202020")  # 35 frames


def make_project(fill: str = "#3b82f6", **fields) -> Project:
    layer = Layer(
        id="a",
        spec=Spec(type="Square", params={"side_length": 4}, style={"fill": fill, "fill_opacity": 1}),
        clips=[Clip(id="c", kind="GrowFromCenter", start=0, duration=3.0)],
    )
    return Project(canvas=CANVAS, layers=[layer], **fields)


PROJECT = make_project()
SEGMENTED = RenderOptions(segment_seconds=1, jobs=1, encoder="cpu")  # 4 segments: 10, 10, 10 and 5 frames


class StopError(Exception):
    """Stands for a crash or a kill part way through."""


def decode(path) -> list[np.ndarray]:
    with av.open(str(path)) as container:
        return [frame.to_ndarray(format="rgb24") for frame in container.decode(video=0)]


def same_video(a, b, tolerance: float = 1.5) -> None:
    """Frame for frame alike: as many, each close on average (both are lossy H.264)."""
    x, y = decode(a), decode(b)
    assert len(x) == len(y)
    for k, (p, q) in enumerate(zip(x, y, strict=True)):
        assert np.abs(p.astype(int) - q.astype(int)).mean() < tolerance, f"frame {k}"


@pytest.fixture
def counted(monkeypatch):
    """How many frames this process draws."""
    drawn = [0]
    real = cairo_export.render_frame

    def render_frame(*args, **kwargs):
        drawn[0] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(cairo_export, "render_frame", render_frame)
    return drawn


def stop_at(frame: int):
    def progress(done: int, _total: int) -> None:
        if done == frame:
            raise StopError

    return progress


def interrupt(out, project: Project = PROJECT, options: RenderOptions = SEGMENTED, at: int = 25) -> None:
    """An export stopped at frame ``at`` (25: in the third segment, two done)."""
    with pytest.raises(StopError):
        export_video(project, out, stop_at(at), options=options)


@pytest.fixture(scope="module")
def single_pass(tmp_path_factory):
    """The reference: the same export in one pass (segments of 10 s, longer than the video)."""
    out = tmp_path_factory.mktemp("single") / "single.mp4"
    return export_video(PROJECT, out, options=RenderOptions(jobs=1, encoder="cpu")).path


# -- the plan ------------------------------------------------------------------------------------


def test_segments_cover_the_window_and_short_exports_are_not_segmented() -> None:
    assert resume.segment_frames(1, 10) == 10 and resume.segment_frames(0.01, 10) == 1
    assert resume.spans(0, 35, 10) == [(0, 0, 10), (1, 10, 20), (2, 20, 30), (3, 30, 35)]
    assert resume.spans(5, 25, 10) == [(0, 5, 15), (1, 15, 25)]
    assert resume.segmented(0, 20, 10) and not resume.segmented(0, 19, 10)
    assert resume.work_dir(Path("out/clip.mp4")).name == "clip.export"


def test_the_segment_length_is_an_option() -> None:
    assert RenderOptions().segment_seconds == 10
    assert RenderOptions(segment_seconds=2.5).to_args() == ["--segment-seconds", "2.5"]
    assert RenderOptions().to_args() == []
    with pytest.raises(OptionsError):
        RenderOptions(segment_seconds=0)


def test_the_keys_name_the_project_and_what_changes_the_pixels() -> None:
    assert resume.project_key(PROJECT) == resume.project_key(make_project())
    assert resume.project_key(PROJECT) != resume.project_key(make_project("#ff0000"))
    key = resume.options_key(SEGMENTED)
    assert key == resume.options_key(RenderOptions(segment_seconds=1, jobs=4, encoder="cpu"))  # not jobs
    assert key != resume.options_key(RenderOptions(segment_seconds=1, jobs=1, encoder="cpu", crf=23))
    assert key != resume.options_key(SEGMENTED, trust=True)
    assert key == resume.options_key(RenderOptions(segment_seconds=1.0, jobs=1, encoder="cpu"))


# -- segmented exports ---------------------------------------------------------------------------------


def test_a_segmented_export_equals_the_single_pass_one(tmp_path, single_pass) -> None:
    calls = []
    out = tmp_path / "seg.mp4"
    result = export_video(PROJECT, out, lambda done, total: calls.append((done, total)), options=SEGMENTED)
    assert result.path == out and result.how == "CPU (x264)"
    assert calls == [(i, 35) for i in range(1, 36)]
    same_video(out, single_pass)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["seg.mp4"]  # the work folder is removed


def test_a_short_export_is_rendered_in_one_pass(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(cairo_export, "_encode_segments", lambda *a, **k: pytest.fail("segmented"))
    options = RenderOptions(segment_seconds=2, jobs=1)  # 35 frames are 1.75 segments
    export_video(PROJECT, tmp_path / "one.mp4", options=options)


def test_an_interrupted_export_resumes_with_the_missing_segments_only(tmp_path, counted, single_pass) -> None:
    out = tmp_path / "v.mp4"
    interrupt(out)
    work = resume.work_dir(out)
    state = resume.load(work)
    assert sorted(state.segments) == [0, 1] and state.codec == "libx264"
    assert sorted(p.name for p in work.iterdir()) == ["segment_0000.mp4", "segment_0001.mp4", "state.json"]
    assert not out.exists() and not partial_path(out).exists()
    assert resume.pending(PROJECT, SEGMENTED, out) == resume.Pending(work, 2, 4)

    counted[0] = 0
    calls = []
    export_video(PROJECT, out, lambda done, total: calls.append(done), options=SEGMENTED)
    assert counted[0] == 15  # segments 2 and 3
    assert calls == list(range(21, 36))
    same_video(out, single_pass)
    assert not work.exists()


def test_a_changed_project_starts_again(tmp_path, counted) -> None:
    out = tmp_path / "v.mp4"
    interrupt(out)
    other = make_project("#ef4444")
    assert resume.pending(other, SEGMENTED, out) is None
    assert resume.pending(PROJECT, RenderOptions(segment_seconds=1, jobs=1, crf=23), out) is None
    counted[0] = 0
    export_video(other, out, options=SEGMENTED)
    assert counted[0] == 35
    assert not resume.work_dir(out).exists()


@pytest.mark.parametrize("damage", ["changed", "missing"])
def test_a_damaged_segment_is_rendered_again(tmp_path, counted, single_pass, damage) -> None:
    out = tmp_path / "v.mp4"
    interrupt(out)
    segment = resume.work_dir(out) / "segment_0000.mp4"
    if damage == "missing":
        segment.unlink()
    else:
        data = bytearray(segment.read_bytes())
        data[len(data) // 2] ^= 0xFF  # same size, other contents: only the hash tells
        segment.write_bytes(bytes(data))
    counted[0] = 0
    export_video(PROJECT, out, options=SEGMENTED)
    assert counted[0] == 25  # segment 0 again, then 2 and 3
    same_video(out, single_pass)


def test_fresh_discards_the_finished_segments(tmp_path, counted) -> None:
    out = tmp_path / "v.mp4"
    interrupt(out)
    counted[0] = 0
    export_video(PROJECT, out, options=SEGMENTED, fresh=True)
    assert counted[0] == 35


def test_a_half_written_segment_and_an_unreadable_state_are_not_trusted(tmp_path, counted) -> None:
    out = tmp_path / "v.mp4"
    interrupt(out)
    work = resume.work_dir(out)
    (work / "segment_0002.mp4.tmp").write_bytes(b"half")
    counted[0] = 0
    export_video(PROJECT, out, options=SEGMENTED)
    assert counted[0] == 15 and not work.exists()

    interrupt(out)
    (work / "state.json").write_text("{not json", encoding="utf-8")
    assert resume.pending(PROJECT, SEGMENTED, out) is None
    counted[0] = 0
    export_video(PROJECT, out, options=SEGMENTED)
    assert counted[0] == 35


def test_a_failed_export_keeps_its_segments(tmp_path, monkeypatch) -> None:
    out = tmp_path / "v.mp4"
    real = cairo_export.render_frame
    drawn = [0]

    def render_frame(*args, **kwargs):
        drawn[0] += 1
        if drawn[0] == 15:
            raise RuntimeError("render failed")
        return real(*args, **kwargs)

    monkeypatch.setattr(cairo_export, "render_frame", render_frame)
    with pytest.raises(RuntimeError):
        export_video(PROJECT, out, options=SEGMENTED)
    assert sorted(resume.load(resume.work_dir(out)).segments) == [0]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["v.export"]


def test_the_sound_is_added_under_the_joined_video(tmp_path) -> None:
    wav = tmp_path / "block.wav"
    audio.write_wav(np.full((2, audio.RATE), 0.5, np.float32), wav)
    project = make_project(audio=[AudioClip(id="k", path=str(wav), start=1.5, duration=1.0)])
    out = tmp_path / "v.mp4"
    interrupt(out, project)
    assert resume.load(resume.work_dir(out)).audio
    export_video(project, out, options=SEGMENTED)
    with av.open(str(out)) as container:
        track = np.concatenate([f.to_ndarray() for f in container.decode(audio=0)], axis=1)
    assert int(np.argmax(np.abs(track[0]) > 0.1)) / audio.RATE == pytest.approx(1.5, abs=0.06)
    assert track.shape[1] / audio.RATE == pytest.approx(3.5, abs=0.1)
    assert len(decode(out)) == 35


def test_a_range_is_segmented_from_its_first_frame(tmp_path) -> None:
    options = RenderOptions(segment_seconds=1, jobs=1, encoder="cpu", start=0.5, end=3.0)  # frames 5-30
    out = tmp_path / "r.mp4"
    with pytest.raises(StopError):
        export_video(PROJECT, out, stop_at(15), options=options)
    assert [(s.first, s.last) for s in resume.load(resume.work_dir(out)).segments.values()] == [(5, 15)]
    export_video(PROJECT, out, options=options)
    reference = export_video(PROJECT, tmp_path / "ref.mp4", options=RenderOptions(jobs=1, start=0.5, end=3.0))
    same_video(out, reference.path)


def test_the_graphics_card_encodes_segments_that_join(tmp_path) -> None:
    if not encoders.gpu_listed():
        pytest.skip("no NVENC in this PyAV")
    gpu = RenderOptions(segment_seconds=1, jobs=1, encoder="gpu")
    out = tmp_path / "g.mp4"
    result = export_video(PROJECT, out, options=gpu)
    if "NVENC" not in result.how:
        pytest.skip("the graphics card cannot encode here")
    single = export_video(PROJECT, tmp_path / "s.mp4", options=RenderOptions(jobs=1, encoder="gpu"))
    same_video(out, single.path, tolerance=2.0)
    with pytest.raises(StopError):
        export_video(PROJECT, tmp_path / "h.mp4", stop_at(25), options=gpu)
    assert resume.load(resume.work_dir(tmp_path / "h.mp4")).codec == "h264_nvenc"
    same_video(export_video(PROJECT, tmp_path / "h.mp4", options=gpu).path, single.path, tolerance=2.0)


def test_a_recorded_encoder_that_will_not_open_starts_again(tmp_path, counted, monkeypatch) -> None:
    out = tmp_path / "v.mp4"
    interrupt(out)
    work = resume.work_dir(out)
    state = resume.load(work)
    state.codec, state.label = "h264_nvenc", "GPU (NVENC)"
    resume.save(work, state)
    real = cairo_export._open_video

    def refuse(path, project, encoder, *args):
        if encoder.hardware:
            raise ValueError("no card")
        return real(path, project, encoder, *args)

    monkeypatch.setattr(cairo_export, "_open_video", refuse)
    counted[0] = 0
    result = export_video(PROJECT, out, options=SEGMENTED)
    assert result.how == "CPU (x264)" and counted[0] == 1 + 35  # the frame that found out, then all
    assert len(decode(out)) == 35


# -- old work folders ------------------------------------------------------------------------------------


def test_old_work_folders_beside_the_video_are_removed(tmp_path) -> None:
    old = tmp_path / "old.export"
    old.mkdir()
    (old / "state.json").write_text("{}", encoding="utf-8")
    (old / "segment_0000.mp4").write_bytes(b"x")
    recent = tmp_path / "recent.export"
    recent.mkdir()
    (recent / "state.json").write_text("{}", encoding="utf-8")
    stranger = tmp_path / "stranger.export"  # not ours: no state.json
    stranger.mkdir()
    (stranger / "notes.txt").write_text("keep", encoding="utf-8")
    week_ago = time.time() - resume.MAX_AGE - 60
    for folder in (old, stranger):
        for path in folder.iterdir():
            os.utime(path, (week_ago, week_ago))
    export_video(PROJECT, tmp_path / "v.mp4", options=SEGMENTED)
    assert not old.exists() and recent.exists() and (stranger / "notes.txt").exists()


def test_discard_removes_only_what_an_export_writes(tmp_path) -> None:
    work = tmp_path / "x.export"
    work.mkdir()
    for name in ("state.json", "state.json.tmp", "segment_0003.mp4", "segment_0004.mp4.tmp"):
        (work / name).write_bytes(b"x")
    resume.discard(work)
    assert not work.exists()
    work.mkdir()
    (work / "mine.txt").write_text("keep", encoding="utf-8")
    (work / "segment_0000.mp4").write_bytes(b"x")
    resume.discard(work)
    assert [p.name for p in work.iterdir()] == ["mine.txt"]


def test_the_state_file_round_trips(tmp_path) -> None:
    state = resume.State("p", "o", 0, 35, 10, 10, False, "libx264", "CPU (x264)")
    state.segments[1] = resume.Segment(1, 10, 20, "segment_0001.mp4", "ab", 3)
    resume.save(tmp_path, state)
    assert resume.load(tmp_path) == state
    assert json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))["format"] == resume.FORMAT
    assert not (tmp_path / "state.json.tmp").exists()


# -- the command line ----------------------------------------------------------------------------------


def test_the_cli_resumes_by_default_and_fresh_starts_again(tmp_path, capsys, counted) -> None:
    project_file = tmp_path / "p.json"
    project_file.write_text(PROJECT.model_dump_json(by_alias=True), encoding="utf-8")
    out = tmp_path / "v.mp4"
    flags = ["--segment-seconds", "1", "--jobs", "1", "--encoder", "cpu"]
    interrupt(out)
    capsys.readouterr()
    counted[0] = 0
    assert cli.main(["render", str(project_file), str(out), *flags, "--progress", "json"]) == 0
    printed = capsys.readouterr().out.splitlines()
    lines = [json.loads(line) for line in printed if line.startswith("{")]
    assert lines[0] == {"stage": "Resuming: 2 of 4 segments already rendered", "resumed": 2, "segments": 4}
    assert lines[1] == {"frame": 21, "total": 35} and lines[-1] == {"done": str(out)}
    assert counted[0] == 15 and not resume.work_dir(out).exists()

    interrupt(out)
    counted[0] = 0
    assert cli.main(["render", str(project_file), str(out), *flags, "--fresh"]) == 0
    assert "Resuming" not in capsys.readouterr().out and counted[0] == 35
