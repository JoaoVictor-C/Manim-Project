"""How long the scene is (P7.1): by hand, or growing with what it holds.

The scene's length (``Canvas.duration``) can be set by hand (Scene settings, the end on the
ruler). With ``Canvas.grow_with_content`` (the default) it also grows by itself to cover
anything an edit places past the end - a clip, a key, a sound, a subtitle, a marker, an
object's explicit end - as part of that same edit. It never shrinks by itself: a scene that
shrank would cut an ending silently; ``fit_to_content`` trims it on request.
"""

from __future__ import annotations

import math
from collections.abc import Iterable

from .schema import Project

EPSILON = 1e-9


def content_end(project: Project, more: Iterable[float] = ()) -> float:
    """When the last thing in the scene ends or appears (0 when nothing is timed). ``more``: ends
    only the window knows, such as how long a code layer's rendered animation runs."""
    ends = [0.0, *more]
    for layer in project.layers:
        if layer.lifetime.in_ is not None:
            ends.append(layer.lifetime.in_)  # an object that stays to the end still has to appear
        ends += [clip.start + clip.duration for clip in layer.clips]
        ends += [key.t for track in layer.tracks.values() for key in track]
        if layer.lifetime.out is not None:
            ends.append(layer.lifetime.out)
    ends += [sound.start + sound.duration for sound in project.audio]
    ends += [cue.end for cue in project.subtitles]
    ends += [marker.t for marker in project.markers]
    return max(ends)


def _whole_frames(t: float, fps: int) -> float:
    """``t`` rounded up to a whole frame (never below one frame)."""
    return max(math.ceil(t * fps - EPSILON), 1) / fps


def grow_to_fit(project: Project) -> Project:
    """The project, longer if something ends past its end and it grows with its content."""
    canvas = project.canvas
    if not canvas.grow_with_content:
        return project
    end = content_end(project)
    if end <= canvas.duration + EPSILON:
        return project
    return project.model_copy(
        update={"canvas": canvas.model_copy(update={"duration": _whole_frames(end, canvas.fps)})}
    )


def fit_to_content(project: Project, more: Iterable[float] = ()) -> Project:
    """The project trimmed (or grown) to end where its content ends; unchanged when nothing in
    it is timed (only objects there from the start, with no animation, sound or subtitle)."""
    canvas = project.canvas
    end = content_end(project, more)
    if end <= EPSILON:
        return project
    length = _whole_frames(end, canvas.fps)
    return project.model_copy(update={"canvas": canvas.model_copy(update={"duration": length})})


def set_length(project: Project, duration: float) -> Project:
    """The scene set to ``duration`` by hand: a length shorter than the content also stops the
    scene growing with it, otherwise the next edit would grow it back."""
    canvas = project.canvas
    update: dict = {"duration": duration}
    if canvas.grow_with_content and duration < content_end(project) - EPSILON:
        update["grow_with_content"] = False
    return project.model_copy(update={"canvas": canvas.model_validate({**canvas.model_dump(), **update})})
