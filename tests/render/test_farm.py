"""Frames drawn by several processes (ADR 0065): the same pictures, in order, whatever happens to them."""

from __future__ import annotations

import time

import av
import numpy as np
import pytest

from manim_studio import cli, lifeline
from manim_studio.core.editing import edits
from manim_studio.core.model.schema import Canvas, Clip, Keyframe, Layer, Project, Spec
from manim_studio.render import cairo_export, encoders, farm
from manim_studio.render.cairo_export import export_video, rendered_frames
from manim_studio.render.options import RenderOptions

CANVAS = Canvas(width_px=160, height_px=90, fps=10, duration=4.0, background="#202020")  # 40 frames
FRAME_BYTES = 160 * 90 * 4


def make_project() -> Project:
    return Project(
        canvas=CANVAS,
        layers=[
            Layer(
                id="a",
                spec=Spec(
                    type="Square", params={"side_length": 3}, style={"fill": "#3b82f6", "fill_opacity": 1}
                ),
                clips=[Clip(id="c", kind="GrowFromCenter", start=0, duration=3.0)],
            ),
            Layer(
                id="t",
                spec=Spec(type="Text", params={"text": "farm"}),
                clips=[Clip(id="w", kind="FadeIn", start=1.0, duration=2.0)],
            ),
        ],
    )


def draw(project: Project, first: int = 0, last: int | None = None, workers: int = 1) -> list[np.ndarray]:
    last = round(project.canvas.duration * project.canvas.fps) if last is None else last
    return [rgba.copy() for _, rgba in rendered_frames(project, first, last, workers)]


def same(a: list[np.ndarray], b: list[np.ndarray]) -> bool:
    return len(a) == len(b) and all(np.array_equal(x, y) for x, y in zip(a, b, strict=True))


def decode(path) -> list[np.ndarray]:
    with av.open(str(path)) as container:
        return [frame.to_ndarray(format="rgb24") for frame in container.decode(video=0)]


@pytest.fixture
def pools(monkeypatch):
    """Every Farm made in the test, to look at its processes afterwards."""
    made: list[farm.Farm] = []
    real = farm.Farm

    class Recording(real):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            made.append(self)

    monkeypatch.setattr(farm, "Farm", Recording)
    return made


def alive(pids: list[int]) -> list[int]:
    return [pid for pid in pids if lifeline.process_alive(pid)]


# -- how many processes ------------------------------------------------------------------


def test_one_process_when_asked_for_one_or_when_there_is_nothing_to_share() -> None:
    assert farm.plan(1, 1000, FRAME_BYTES) == 1
    assert farm.plan(8, 1, FRAME_BYTES) == 1
    assert farm.plan(None, farm.MIN_FRAMES - 1, FRAME_BYTES) == 1  # too short for the start-up to pay


def test_a_number_asked_for_is_honoured_up_to_what_the_frames_and_the_ring_allow() -> None:
    assert farm.plan(3, 1000, FRAME_BYTES) == 3
    assert farm.plan(8, 6, FRAME_BYTES) == 3  # two frames each, at least
    big = 7680 * 4320 * 4  # 8K: 127 MB a frame, two in the 256 MB ring
    assert farm.plan(4, 1000, big) == 1  # not even two processes' frames fit: the exporter draws alone


def test_auto_never_starts_more_than_the_cap_and_at_least_two_when_it_starts_any(monkeypatch) -> None:
    from manim_studio.render import resources

    monkeypatch.setattr(resources, "cores", lambda: 64)
    monkeypatch.setattr(resources, "available_memory", lambda: 64 * 2**30)
    assert farm.plan(None, 5000, FRAME_BYTES) == farm.MAX_AUTO
    monkeypatch.setattr(resources, "cores", lambda: 2)
    assert farm.plan(None, 5000, FRAME_BYTES) == 1  # one core's worth: nothing to gain
    monkeypatch.setattr(resources, "cores", lambda: 64)
    monkeypatch.setattr(resources, "available_memory", lambda: 6 * farm.WORKER_BYTES)  # half of it: three...
    assert farm.plan(None, 5000, FRAME_BYTES) == 3
    monkeypatch.setattr(resources, "available_memory", lambda: farm.WORKER_BYTES)
    assert farm.plan(None, 5000, FRAME_BYTES) == 1  # ... and not enough memory for two


# -- the frames ----------------------------------------------------------------------------


@pytest.mark.slow
def test_frames_from_render_processes_are_the_serial_frames_bit_for_bit(pools) -> None:
    project = make_project()
    serial = draw(project)
    assert len(serial) == 40
    assert same(draw(project, workers=2), serial)
    assert len(pools) == 1 and pools[0].next_frame == 40


@pytest.mark.slow
def test_a_range_that_does_not_start_at_zero(pools) -> None:
    project = make_project()
    assert same(draw(project, 7, 33, workers=3), draw(project, 7, 33))


@pytest.mark.slow
def test_a_label_pinned_to_a_moving_object_is_drawn_alike_by_the_processes(pools) -> None:
    """ADR 0075: the pin is evaluated per frame, so any process draws it where the serial export does."""
    project = make_project()
    moving = project.layers[0].model_copy(
        update={
            "tracks": {"position": [Keyframe(t=0.0, value=(-2.0, 0.0)), Keyframe(t=4.0, value=(2.0, 1.0))]}
        }
    )
    project = edits.pin_label(
        project.model_copy(update={"layers": [moving, project.layers[1]]}), "t", "a"
    ).project
    assert same(draw(project, workers=2), draw(project))


@pytest.mark.slow
def test_a_following_camera_with_its_background_is_drawn_alike_by_the_processes(pools) -> None:
    """ADR 0083: the camera's size keys, followed target and background reach every process."""
    project = make_project()
    moving = project.layers[0].model_copy(
        update={
            "tracks": {"position": [Keyframe(t=0.0, value=(-2.0, 0.0)), Keyframe(t=4.0, value=(2.0, 1.0))]}
        }
    )
    camera = Layer(
        id="camera",
        spec=Spec(
            type="Camera", params={"background": "#400000", "follow": "a", "follow_offset": [0.5, 0.0]}
        ),
        tracks={"scale": [Keyframe(t=0.0, value=1.0), Keyframe(t=4.0, value=2.0)]},
    )
    project = project.model_copy(update={"layers": [moving, project.layers[1], camera]})
    serial = draw(project)
    assert tuple(serial[0][0, 0, :3]) == (0x40, 0, 0)  # the camera's background, not the canvas's
    assert same(draw(project, workers=2), serial)
    assert len(pools) == 1 and pools[0].next_frame == 40


@pytest.mark.slow
def test_the_ring_is_reused_when_it_is_smaller_than_the_video(monkeypatch, pools) -> None:
    """Backpressure: workers wait for a free slot, the encoder frees them in order, and nothing is lost."""
    monkeypatch.setattr(farm, "RING_BYTES", 6 * FRAME_BYTES)
    project = make_project()
    assert same(draw(project, workers=2), draw(project))
    assert pools[0]._slots == 6


def test_the_exporter_goes_on_by_itself_from_the_frame_a_failed_farm_reached(monkeypatch) -> None:
    class Failing:
        """A farm whose processes die after 12 frames."""

        def __init__(self, project, first, last, workers, cache_dir, *, trust_code=False) -> None:
            self.first, self.last, self.next_frame, self.closed = first, last, first, False
            self.serial = iter(cairo_export.rendered_frames(project, first, last, 1))

        def frames(self):
            for _ in range(12):
                index, rgba = next(self.serial)
                self.next_frame = index + 1
                yield index, rgba
            raise farm.FarmError("render process 0 stopped")

        def close(self) -> None:
            self.closed = True

    made = []

    def build(*args, **kwargs):
        made.append(Failing(*args, **kwargs))
        return made[0]

    monkeypatch.setattr(farm, "Farm", build)
    project = make_project()
    serial = draw(project)
    assert same(draw(project, workers=2), serial)
    assert made[0].closed


@pytest.mark.slow
def test_a_render_process_that_is_killed_mid_export_costs_nothing_but_time(pools) -> None:
    project = make_project()
    expected = draw(project)
    frames = rendered_frames(project, 0, 40, 2)
    got = [next(frames)[1].copy() for _ in range(8)]
    victim = pools[0]._workers[0].process.pid
    lifeline.kill_tree(victim)
    got += [rgba.copy() for _, rgba in frames]
    assert same(got, expected)
    assert not alive([w.process.pid for w in pools[0]._workers]), "a render process outlived the export"


@pytest.mark.slow
def test_abandoning_the_frames_ends_every_render_process(pools) -> None:
    project = make_project()
    frames = rendered_frames(project, 0, 40, 2)
    next(frames)
    pids = [w.process.pid for w in pools[0]._workers]
    pids += [d for pid in list(pids) for d in lifeline.descendants(pid)]
    frames.close()
    assert lifeline.wait_gone(pids, timeout=15), "render processes were left running"


# -- exports --------------------------------------------------------------------------------


@pytest.mark.slow
def test_an_export_drawn_by_render_processes_decodes_to_the_serial_export(tmp_path) -> None:
    project = make_project()
    one = export_video(project, tmp_path / "one.mp4", options=RenderOptions(jobs=1, encoder="cpu"))
    two = export_video(project, tmp_path / "two.mp4", options=RenderOptions(jobs=2, encoder="cpu"))
    assert one.how == "CPU (x264)" and two.how == "CPU (x264), 2 render processes"
    assert same(decode(two.path), decode(one.path))  # same pixels in, same encoder: same video


@pytest.mark.slow
def test_progress_counts_every_frame_once_in_order(tmp_path) -> None:
    calls = []
    export_video(
        make_project(),
        tmp_path / "p.mp4",
        progress=lambda done, total: calls.append((done, total)),
        options=RenderOptions(jobs=2, encoder="cpu"),
    )
    assert calls == [(i, 40) for i in range(1, 41)]


def test_a_card_that_cannot_open_falls_back_to_x264_before_anything_is_written(tmp_path, monkeypatch) -> None:
    broken = encoders.Encoder(
        "libx264", {"preset": "no-such-preset"}, "yuv420p", "GPU (broken)", hardware=True
    )
    monkeypatch.setattr(encoders, "candidates", lambda *args, **kwargs: [broken, encoders.x264(18)])
    done = export_video(make_project(), tmp_path / "v.mp4", options=RenderOptions(jobs=1, encoder="gpu"))
    assert done.how == "CPU (x264)"
    assert len(decode(done.path)) == 40


def test_x264_failing_is_the_exports_failure(tmp_path, monkeypatch) -> None:
    broken = encoders.Encoder("libx264", {"preset": "no-such-preset"}, "yuv420p", "CPU (x264)")
    monkeypatch.setattr(encoders, "candidates", lambda *args, **kwargs: [broken])
    with pytest.raises(ValueError):
        export_video(make_project(), tmp_path / "v.mp4", options=RenderOptions(jobs=1))
    assert not list(tmp_path.glob("*.mp4")), "a partial video was left behind"


@pytest.mark.skipif(not encoders.gpu_listed(), reason="this PyAV has no NVENC encoder")
def test_the_card_encodes_a_video_that_looks_like_the_frames(tmp_path) -> None:
    """Only where an NVIDIA card is there to open; elsewhere the export falls back and says so."""
    project = make_project()
    done = export_video(project, tmp_path / "gpu.mp4", options=RenderOptions(jobs=1, encoder="gpu"))
    frames = decode(done.path)
    assert len(frames) == 40
    expected = draw(project)
    pairs = zip(frames, expected, strict=True)
    mean = np.mean([np.abs(a.astype(int) - b[:, :, :3].astype(int)).mean() for a, b in pairs])
    assert mean < 6  # compression only: the same picture whichever encoder made it
    if done.how.startswith("GPU"):
        assert done.how == "GPU (NVENC)"
    else:
        assert done.how == "CPU (x264)"  # no card (or its session limit): the fallback, which must still work


def test_cli_flags_reach_the_export_and_the_report_says_how(tmp_path, capsys) -> None:
    source = tmp_path / "p.json"
    source.write_text(make_project().model_dump_json(by_alias=True), encoding="utf-8")
    out = tmp_path / "out.mp4"
    code = cli.main(
        [
            "render",
            str(source),
            str(out),
            "--jobs",
            "1",
            "--encoder",
            "cpu",
            "--cache-dir",
            str(tmp_path / "c"),
        ]
    )
    assert code == 0
    assert "(CPU (x264))" in capsys.readouterr().out
    assert len(decode(out)) == 40


def test_cli_refuses_a_bad_jobs_number(tmp_path, capsys) -> None:
    source = tmp_path / "p.json"
    source.write_text(make_project().model_dump_json(by_alias=True), encoding="utf-8")
    assert cli.main(["render", str(source), str(tmp_path / "o.mp4"), "--jobs", "0"]) != 0
    assert "jobs must be between" in capsys.readouterr().err


def test_a_probe_estimates_the_cost_of_a_frame_and_a_light_scene_stays_serial() -> None:
    started = time.perf_counter()
    assert cairo_export.farm_pays(make_project(), 0, 40) is False  # 40 tiny frames: well under MIN_SECONDS
    assert time.perf_counter() - started < 30
