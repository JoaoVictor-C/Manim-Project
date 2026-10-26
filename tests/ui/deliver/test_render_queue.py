"""The render queue's state machine (P6b.5, ADR 0042): no Qt, no processes."""

from __future__ import annotations

from pathlib import Path

from manim_studio.core.model.schema import Canvas, Layer, Project, Spec
from manim_studio.render.options import RenderOptions
from manim_studio.ui.deliver.render_queue import RenderQueue, Status, unique_output

PROJECT = Project(
    canvas=Canvas(width_px=160, height_px=90, fps=10, duration=2.0),
    layers=[Layer(id="a", spec=Spec(type="Dot"))],
)


def queue_of(*names: str) -> tuple[RenderQueue, list]:
    queue = RenderQueue()
    return queue, [queue.add(PROJECT, RenderOptions(), Path(f"out/{name}.mp4")) for name in names]


def test_a_new_job_is_queued_with_the_snapshot_options_and_trust() -> None:
    queue = RenderQueue()
    options = RenderOptions(start=0.5, end=1.5)
    job = queue.add(PROJECT, options, Path("out/a.mp4"), trust=True)
    assert (job.status, job.project, job.options, job.trust) == (Status.QUEUED, PROJECT, options, True)
    assert job.id == 1 and queue.add(PROJECT, options, Path("out/b.mp4")).id == 2
    assert queue.get(2).output == Path("out/b.mp4") and queue.get(9) is None


def test_the_output_is_an_mp4() -> None:
    queue = RenderQueue()
    assert queue.add(PROJECT, RenderOptions(), Path("out/video")).output == Path("out/video.mp4")
    assert queue.add(PROJECT, RenderOptions(), Path("out/clip.mov")).output == Path("out/clip.mp4")


def test_a_pending_output_path_gets_a_number_but_a_finished_one_does_not() -> None:
    queue, (a, b) = queue_of("v", "v")
    assert (a.output, b.output) == (Path("out/v.mp4"), Path("out/v (2).mp4"))
    assert queue.add(PROJECT, RenderOptions(), Path("OUT/V.mp4")).output == Path("OUT/V (3).mp4")  # any case
    queue.start()
    queue.finish(a, Path("out/v.mp4"))
    assert queue.add(PROJECT, RenderOptions(), Path("out/v.mp4")).output == Path("out/v.mp4")  # a is done
    assert unique_output(Path("x.mp4"), set()) == Path("x.mp4")
    assert unique_output(Path("x.mp4"), {Path("x.mp4"), Path("x (2).mp4")}) == Path("x (3).mp4")


def test_nothing_runs_until_start_and_then_the_jobs_run_in_order() -> None:
    queue, (a, b, c) = queue_of("a", "b", "c")
    assert queue.advance() is None and not queue.busy  # not started
    assert queue.start() is a and a.status is Status.RENDERING and queue.current is a
    assert queue.advance() is None and queue.start() is None  # one at a time
    queue.finish(a, Path("a.mp4"))
    assert queue.advance() is b and b.status is Status.RENDERING and c.status is Status.QUEUED
    queue.fail(b, "boom")
    assert queue.advance() is c
    queue.finish(c, Path("c.mp4"), "in use")
    assert queue.advance() is None and not queue.active and not queue.busy
    assert (a.status, b.status, c.status) == (Status.DONE, Status.FAILED, Status.DONE)
    assert (b.message, c.message, a.result, c.result) == ("boom", "in use", Path("a.mp4"), Path("c.mp4"))


def test_start_with_nothing_queued_does_nothing() -> None:
    queue = RenderQueue()
    assert queue.start() is None and not queue.active


def test_jobs_added_while_the_queue_runs_are_picked_up() -> None:
    queue, (a,) = queue_of("a")
    queue.start()
    late = queue.add(PROJECT, RenderOptions(), Path("late.mp4"))
    queue.finish(a, Path("a.mp4"))
    assert queue.advance() is late


def test_a_job_added_after_the_queue_ran_dry_waits_for_start() -> None:
    queue, (a,) = queue_of("a")
    queue.start()
    queue.finish(a, Path("a.mp4"))
    assert queue.advance() is None and not queue.active
    queue.add(PROJECT, RenderOptions(), Path("b.mp4"))
    assert queue.advance() is None
    assert queue.start().output == Path("b.mp4")


def test_progress_and_percent() -> None:
    queue, (a,) = queue_of("a")
    assert a.percent == 0
    queue.progress(a, 3, 12)  # not rendering yet: ignored
    assert (a.frame, a.total) == (0, 0)
    queue.start()
    queue.progress(a, 3, 12)
    assert (a.frame, a.total, a.percent) == (3, 12, 25)
    queue.finish(a, Path("a.mp4"))
    assert a.percent == 100 and a.finished


def test_cancelling_a_queued_job_skips_it() -> None:
    queue, (a, b, c) = queue_of("a", "b", "c")
    queue.start()
    assert queue.cancel(b) is False and b.status is Status.CANCELLED  # was not rendering
    queue.finish(a, Path("a.mp4"))
    assert queue.advance() is c


def test_cancelling_the_rendering_job_reports_it_and_the_queue_goes_on() -> None:
    queue, (a, b) = queue_of("a", "b")
    queue.start()
    assert queue.cancel(a) is True and a.status is Status.CANCELLED and not queue.busy
    queue.fail(a, "late signal from the killed process")  # ignored: it is cancelled
    queue.finish(a, Path("a.mp4"))
    assert a.status is Status.CANCELLED and a.result is None
    assert queue.advance() is b
    assert queue.cancel(a) is False  # already cancelled


def test_cancel_all_stops_the_queue() -> None:
    queue, (a, b, c) = queue_of("a", "b", "c")
    queue.start()
    queue.finish(a, Path("a.mp4"))
    queue.advance()  # b renders
    assert queue.cancel_all() is True
    assert (a.status, b.status, c.status) == (Status.DONE, Status.CANCELLED, Status.CANCELLED)
    assert not queue.active and queue.advance() is None
    assert RenderQueue().cancel_all() is False


def test_remove_refuses_a_rendering_job() -> None:
    queue, (a, b) = queue_of("a", "b")
    queue.start()
    assert queue.remove(a) is False and a in queue.jobs
    assert queue.remove(b) is True and queue.jobs == [a]
    assert queue.remove(b) is False  # already gone
    queue.cancel(a)
    assert queue.remove(a) is True and queue.jobs == []


def test_clear_finished_keeps_pending_jobs() -> None:
    queue, (a, b, c, d) = queue_of("a", "b", "c", "d")
    queue.start()
    queue.finish(a, Path("a.mp4"))
    queue.advance()
    queue.fail(b, "x")
    queue.advance()
    queue.cancel(c)
    assert queue.clear_finished() == 3 and queue.jobs == [d]
    assert queue.clear_finished() == 0


def test_a_job_summarises_what_it_renders_from_its_own_snapshot() -> None:
    queue = RenderQueue()
    job = queue.add(PROJECT, RenderOptions(width=80, height=46, fps=5, start=0.5, end=1.5), Path("a.mp4"))
    assert job.summary == "80x46 5 fps, 0.60-1.60 s"  # 0.5 s at 5 fps is frame 3 (halves go up)
    assert queue.add(PROJECT, RenderOptions(), Path("b.mp4")).summary == "160x90 10 fps, 0.00-2.00 s"
