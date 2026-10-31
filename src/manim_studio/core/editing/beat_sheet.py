"""The beat sheet (ADR 0073): the video as beats, each with what appears, is said and heard.

A beat is the span between two markers (``ripple.beats``). Reading is all this does: the sheet is built from
the project and changes nothing, so it can be shown in a window, copied as Markdown or kept in a review.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..model.schema import Project
from . import ripple

EPS = 1e-6


@dataclass(frozen=True)
class Row:
    """One beat and what happens in it."""

    beat: ripple.Beat
    appears: list[str] = field(default_factory=list)  # labels of the objects that come in during the beat
    said: list[str] = field(default_factory=list)  # subtitles that start in it
    sounds: list[str] = field(default_factory=list)  # sounds that start in it

    @property
    def thumbnail_time(self) -> float:
        """Where its picture is drawn: a little in, so the beat's own objects have started to appear."""
        return min(self.beat.start + min(0.5, self.beat.length / 2), self.beat.end - EPS)


def _inside(beat: ripple.Beat, t: float) -> bool:
    return beat.start - EPS <= t < beat.end - EPS


def sheet(project: Project) -> list[Row]:
    """The rows, in time order."""
    rows = []
    for beat in ripple.beats(project):
        appears = [
            layer.label
            for layer in project.layers
            if not layer.is_camera
            and layer.parent_id is None
            and _inside(beat, project.lifetime(layer.id)[0])
        ]
        said = [cue.text for cue in project.subtitles if _inside(beat, cue.start)]
        sounds = [
            clip.name or clip.path.replace("\\", "/").rsplit("/", 1)[-1]
            for clip in project.audio
            if _inside(beat, clip.start)
        ]
        rows.append(Row(beat, appears, said, sounds))
    return rows


def clock(t: float) -> str:
    minutes, seconds = divmod(t, 60.0)
    return f"{int(minutes)}:{seconds:04.1f}"


def to_markdown(project: Project, title: str = "Beat sheet") -> str:
    """The sheet as Markdown, to paste into notes or a review."""
    lines = [f"# {title}", ""]
    for number, row in enumerate(sheet(project), 1):
        beat = row.beat
        lines.append(f"## {number}. {beat.name} ({clock(beat.start)} - {clock(beat.end)}, {beat.length:g} s)")
        if row.appears:
            lines.append("- Appears: " + ", ".join(row.appears))
        lines += [f'- Says: "{text}"' for text in row.said]
        if row.sounds:
            lines.append("- Sound: " + ", ".join(row.sounds))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
