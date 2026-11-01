"""Explain a moment (ADR 0082): what is on screen at a time, and which layers, clips and keys make it so.

Read-only, like the beat sheet (ADR 0073): ``moments`` lists the times where something changes, so a scene
can be stepped through, and ``explain`` says for one time which layers are visible and why, which clips are
running and how far, which keyed properties are moving and their value, the subtitles shown, the sounds
playing and the beat. Every item also has a plain sentence ("Circle is drawn in by Create, 40% through").
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..model.schema import CLIP_KIND_INFO, Easing, Keyframe, Layer, Project
from . import ripple
from .beat_sheet import clock

EPS = 1e-6
MAX_MOMENTS = 200  # a long scene is thinned evenly to this many steps


def _frame(t: float, fps: int) -> float:
    return round(t * fps) / fps


def moments(project: Project, limit: int = MAX_MOMENTS) -> list[float]:
    """The distinct times where something changes, in order, on frames inside the scene.

    A layer appearing or leaving, a clip starting or ending, a key, a subtitle starting or ending, a sound
    starting and a marker. More than ``limit`` are thinned evenly (the first and last are kept).
    """
    fps, end = project.canvas.fps, project.canvas.duration
    times = [0.0]
    times += [marker.t for marker in project.markers]
    for layer in project.layers:
        if layer.is_camera and not layer.tracks:
            continue
        start, stop = project.lifetime(layer.id)
        times += [start, stop]
        for clip in layer.clips:
            times += [clip.start, clip.end]
        for track in layer.tracks.values():
            times += [key.t for key in track]
    for cue in project.subtitles:
        times += [cue.start, cue.end]
    times += [clip.start for clip in project.audio]
    found = sorted(
        {min(max(_frame(t, fps), 0.0), end) for t in times if math.isfinite(t) and -EPS <= t <= end + EPS}
    )
    if len(found) <= limit:
        return found
    if limit <= 1:
        return found[:limit]
    step = (len(found) - 1) / (limit - 1)
    return [found[round(i * step)] for i in range(limit)]


def step(times: list[float], t: float, direction: int) -> float | None:
    """The moment after (``direction`` > 0) or before ``t``; None at either end."""
    if direction > 0:
        return next((m for m in times if m > t + EPS), None)
    return next((m for m in reversed(times) if m < t - EPS), None)


def _ease_name(ease: Easing | None) -> str:
    if ease is None:
        return "default"
    if ease.bezier is not None:
        return "custom curve"
    return ease.name or "linear"


def _type(layer: Layer) -> str:
    if layer.spec is not None:
        return layer.spec.type
    return "Part" if layer.part is not None else "Layer"


def _seconds(t: float) -> str:
    return "the end" if not math.isfinite(t) else clock(t)


@dataclass(frozen=True)
class VisibleLayer:
    layer_id: str
    label: str
    type: str
    start: float  # the lifetime: [start, end)
    end: float
    hidden: bool = False  # switched off in the editor

    @property
    def sentence(self) -> str:
        why = f"from {_seconds(self.start)} to {_seconds(self.end)}"
        hidden = " (hidden in the editor)" if self.hidden else ""
        return f"{self.label} ({self.type}) is on screen {why}{hidden}"


@dataclass(frozen=True)
class ActiveClip:
    layer_id: str
    label: str
    clip_id: str
    kind: str
    progress: float  # 0..1, in time (the easing then shapes it)
    easing: str
    start: float
    end: float
    target: str | None = None  # a morph's other layer, by label

    @property
    def sentence(self) -> str:
        how = f"{round(self.progress * 100)}% through, {self.easing} easing"
        verb = _verb(self.kind, self.target)
        return f"{self.label} {verb} {self.kind}, {how}"


def _verb(kind: str, target: str | None) -> str:
    info = CLIP_KIND_INFO.get(kind)
    if info is None:
        return "is animated by"
    if info.category == "morph":
        return f"turns into {target} with" if target else "is reshaped by"
    if info.introducer:
        return "is drawn in by" if info.vector_only else "comes in with"
    if info.remover:
        return "leaves with"
    if info.category == "motion":
        return "is moved by"
    return "is emphasised by"


@dataclass(frozen=True)
class AnimatingKey:
    layer_id: str
    label: str
    track: str
    value: float | tuple[float, ...]
    start: float  # the keys either side of the moment
    end: float

    @property
    def value_text(self) -> str:
        if isinstance(self.value, tuple):
            return "(" + ", ".join(f"{v:.2f}" for v in self.value) + ")"
        return f"{self.value:.2f}"

    @property
    def sentence(self) -> str:
        return (
            f"{self.label}'s {self.track.replace('_', ' ')} is keyed, moving between "
            f"{clock(self.start)} and {clock(self.end)}: now {self.value_text}"
        )


@dataclass(frozen=True)
class ShownSubtitle:
    cue_id: str
    text: str
    start: float
    end: float

    @property
    def sentence(self) -> str:
        return f'The subtitle "{self.text}" is shown ({clock(self.start)} - {clock(self.end)})'


@dataclass(frozen=True)
class PlayingSound:
    audio_id: str
    name: str
    into: float  # seconds into the clip

    @property
    def sentence(self) -> str:
        return f"{self.name} plays, {self.into:.1f} s in"


@dataclass(frozen=True)
class Explanation:
    t: float
    beat: str | None
    layers: list[VisibleLayer] = field(default_factory=list)
    clips: list[ActiveClip] = field(default_factory=list)
    keys: list[AnimatingKey] = field(default_factory=list)
    subtitles: list[ShownSubtitle] = field(default_factory=list)
    sounds: list[PlayingSound] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (self.layers or self.clips or self.keys or self.subtitles or self.sounds)


def _value_at(track: list[Keyframe], t: float):
    from ..engine.evaluator import _sample  # the evaluator's own sampling (imports Manim)

    value = _sample(track, t, None)
    return tuple(float(v) for v in value) if isinstance(value, (tuple, list)) else float(value)


def _alive(start: float, end: float, t: float) -> bool:
    return start - EPS <= t < end - EPS


def explain(project: Project, t: float) -> Explanation:
    """What makes the frame at ``t``."""
    beats = ripple.beats(project)
    beat = next((b.name for b in beats if _alive(b.start, b.end, t)), None)
    if beat is None and beats and t >= beats[-1].end - EPS:  # the very end belongs to the last beat
        beat = beats[-1].name
    by_id = {layer.id: layer for layer in project.layers}
    layers, clips, keys = [], [], []
    for layer in project.layers:
        start, end = project.lifetime(layer.id)
        if not layer.is_camera and _alive(start, end, t):
            layers.append(VisibleLayer(layer.id, layer.label, _type(layer), start, end, not layer.visible))
        for clip in layer.clips:
            if _alive(clip.start, clip.end, t):
                target = by_id[clip.to_layer].label if clip.to_layer in by_id else None
                progress = min(max((t - clip.start) / clip.duration, 0.0), 1.0)
                clips.append(
                    ActiveClip(
                        layer.id,
                        layer.label,
                        clip.id,
                        clip.kind,
                        progress,
                        _ease_name(clip.ease),
                        clip.start,
                        clip.end,
                        target,
                    )
                )
        for track_name, track in layer.tracks.items():
            if len(track) < 2:
                continue
            ordered = sorted(track, key=lambda k: k.t)
            if not (ordered[0].t - EPS <= t < ordered[-1].t - EPS):
                continue
            k0 = max((k for k in ordered if k.t <= t + EPS), key=lambda k: k.t)
            k1 = min((k for k in ordered if k.t > k0.t + EPS), key=lambda k: k.t)
            if k0.value == k1.value:
                continue  # held, not moving
            keys.append(AnimatingKey(layer.id, layer.label, track_name, _value_at(ordered, t), k0.t, k1.t))
    subtitles = [
        ShownSubtitle(cue.id, cue.text, cue.start, cue.end)
        for cue in project.subtitles
        if _alive(cue.start, cue.end, t)
    ]
    sounds = [
        PlayingSound(clip.id, clip.name or clip.path.replace("\\", "/").rsplit("/", 1)[-1], t - clip.start)
        for clip in project.audio
        if _alive(clip.start, clip.end, t)
    ]
    return Explanation(t, beat, layers, clips, keys, subtitles, sounds)


SECTIONS = (
    ("Running", "clips"),
    ("Moving", "keys"),
    ("On screen", "layers"),
    ("Said", "subtitles"),
    ("Heard", "sounds"),
)


def to_text(explanation: Explanation) -> str:
    """The explanation as plain text, one sentence per item."""
    head = f"At {clock(explanation.t)}"
    if explanation.beat:
        head += f', in the beat "{explanation.beat}"'
    lines = [head]
    for title, name in SECTIONS:
        items = getattr(explanation, name)
        if items:
            lines += ["", f"{title}:"] + [f"- {item.sentence}" for item in items]
    if explanation.empty:
        lines += ["", "Nothing is on screen."]
    return "\n".join(lines) + "\n"
