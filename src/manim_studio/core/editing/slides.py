"""Slides (ADR 0087): stop markers cut the scene into slides, for present mode and the HTML deck alike.

A slide is a range of frames ``[first, last)`` on a frame grid (the project's fps unless another is asked for,
as an export at another fps would). It ends on its stop's frame, included, and the next one starts on the frame
after it; the last slide runs to the scene's end. A stop on frame 0 is a one-frame title slide, a stop on (or past)
the last frame ends the last slide, and a slide with no frames is dropped. With no stops the whole scene is one
slide. Plain markers never cut.

``loop_window`` is the part of a slide that repeats while it waits: the stop's ``loop`` seconds before it, at
least one frame and at most the slide. No Qt, no Manim.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..model.schema import Marker, Project

EPS = 1e-6


@dataclass(frozen=True)
class Slide:
    index: int  # 0-based, in time order
    first: int  # first frame
    last: int  # one past the last frame
    fps: int
    stop: Marker | None  # None: the last slide, which runs to the end of the scene

    @property
    def start(self) -> float:
        return self.first / self.fps

    @property
    def end(self) -> float:
        """Where its frames end (the frame after the stop's starts here)."""
        return self.last / self.fps

    @property
    def stop_time(self) -> float:
        """The time of its last frame: where playback waits."""
        return (self.last - 1) / self.fps

    @property
    def frames(self) -> int:
        return self.last - self.first


def _frame(t: float, fps: int) -> int:
    return round(t * fps + EPS)


def stops(project: Project) -> list[Marker]:
    """The slide stops, in time order."""
    return [m for m in project.markers if m.slide == "stop"]


def windows(project: Project, fps: int | None = None) -> list[Slide]:
    fps = fps or project.canvas.fps
    total = round(project.canvas.duration * fps)
    out: list[Slide] = []
    first = 0
    for marker in stops(project):
        last = min(_frame(marker.t, fps), total - 1) + 1
        if last > first:
            out.append(Slide(len(out), first, last, fps, marker))
            first = last
    if total > first:
        out.append(Slide(len(out), first, total, fps, None))
    return out


def loop_window(slide: Slide) -> tuple[int, int] | None:
    """The frames ``[a, slide.last)`` that repeat while the slide waits, or None when it holds still."""
    if slide.stop is None or slide.stop.loop is None:
        return None
    count = min(max(1, _frame(slide.stop.loop, slide.fps)), slide.frames)
    return slide.last - count, slide.last


def slide_at(project: Project, t: float) -> Slide:
    """The slide whose frames include the one showing at ``t``."""
    found = windows(project)
    frame = max(0, int(t * project.canvas.fps + EPS))
    return next((s for s in found if s.first <= frame < s.last), found[-1])


def next_stop(project: Project, t: float) -> Marker | None:
    """The first stop after the frame of ``t`` (standing on a stop: the one after it)."""
    fps = project.canvas.fps
    frame = _frame(t, fps)
    return next((m for m in stops(project) if _frame(m.t, fps) > frame), None)


def previous_stop(project: Project, t: float) -> Marker | None:
    """The last stop before the frame of ``t``."""
    fps = project.canvas.fps
    frame = _frame(t, fps)
    before = [m for m in stops(project) if _frame(m.t, fps) < frame]
    return before[-1] if before else None
