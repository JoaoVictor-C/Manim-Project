"""Import a Manim scene as layers and clips (P10.3, ADR 0053) - pure: no Manim, no Qt.

``scene_recorder`` plays the scene once in another process and records what it did: what is drawn
between plays, each animation with its timing and its target as it began and ended. ``import_scene``
turns that recording into a project:

* **Layers.** The drawn pieces are split into the fewest groups that every object the code added or
  animated is made of (a VGroup animated as one is one layer; its members become layers of their
  own when the code animates them separately). A group becomes a built-in object (Circle, Text,
  MathTex...) when the recorder verified that the built-in rebuilds it exactly, else a **Shape**
  (ADR 0052): the exact drawn data. A layer lives while its pieces are drawn unchanged; when the
  code changes them between plays, or removes and adds them again, a new layer takes over.
* **Clips.** Animations Studio has become clips with their start, run time, ease and params;
  ``mobject.animate`` moves, uniform scales and fades (and ``Rotate``) become keyframes; a morph
  hands its layer off to a new layer (ADR 0005). A clip on a group whose parts are layers is split
  over them when each part is timed as in the whole (``lag_ratio``).
* **Verification.** Every state the recording holds - the object as each animation begins and
  ends, what is drawn between plays - is checked against what the layers would draw then (points
  within ``TOLERANCE``, the same colours). Anything that does not match, and anything the recorder
  reported (updaters, cameras, custom animations), makes the whole scene **one code layer**
  (ADR 0019) instead, with the reasons: the import never draws something else than Manim would.
"""

from __future__ import annotations

import ast
import heapq
import itertools
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import ValidationError

from .schema import (
    CLIP_KIND_INFO,
    AudioClip,
    Canvas,
    Clip,
    Cue,
    Easing,
    Keyframe,
    Layer,
    Lifetime,
    Project,
    Spec,
    SubtitleStyle,
    Transform2D,
    infer_lifetime,
)

TOLERANCE = 1e-6  # Manim units between a recorded point and the layer's
COLOUR_TOLERANCE = 1e-6
EPS = 1e-9
TEXT_TYPES = ("Text", "MathTex", "Tex")
LATEX_TYPES = ("MathTex", "Tex")
# What a clip may find in its layer's transform besides a move (the clip acts on the object before
# its transform, ADR 0031): a uniform scale keeps every centre and edge; a turn keeps only what does
# not depend on the object's box; a fade multiplies what the clip draws.
SCALE_SAFE = frozenset(
    {
        "Create",
        "Uncreate",
        "Write",
        "Unwrite",
        "DrawBorderThenFill",
        "FadeIn",
        "FadeOut",
        "GrowFromCenter",
        "SpinInFromNothing",
        "GrowFromEdge",
        "AddTextLetterByLetter",
        "RemoveTextLetterByLetter",
        "ShrinkToCenter",
        "Indicate",
        "Wiggle",
    }
)
TURN_SAFE = frozenset(
    {
        "Create",
        "Uncreate",
        "Write",
        "Unwrite",
        "DrawBorderThenFill",
        "FadeIn",
        "FadeOut",
        "AddTextLetterByLetter",
        "RemoveTextLetterByLetter",
    }
)
FADE_SAFE = frozenset(
    {
        "Create",
        "Uncreate",
        "FadeIn",
        "FadeOut",
        "GrowFromCenter",
        "SpinInFromNothing",
        "GrowFromEdge",
        "AddTextLetterByLetter",
        "RemoveTextLetterByLetter",
        "ShrinkToCenter",
        "Indicate",
        "Wiggle",
        "ApplyWave",
    }
)
# Clips whose frames depend on how the object is cut into curves and pieces, not only on its drawing.
STRUCTURAL = frozenset(
    {
        "Create",
        "Uncreate",
        "Write",
        "Unwrite",
        "DrawBorderThenFill",
        "SpiralIn",
        "AddTextLetterByLetter",
        "RemoveTextLetterByLetter",
        "ApplyWave",
    }
)


@dataclass
class ImportResult:
    """``project``: the scene as a project (its canvas, layers, sounds and subtitles). ``converted``
    is False when it is one code layer (the reasons are in ``report``)."""

    project: Project
    report: list[str]
    converted: bool
    reasons: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)


class Unsupported(Exception):  # noqa: N818 - a reason, not a failure
    """Something the layers cannot reproduce exactly: the scene stays a code layer."""

    def __init__(self, what: str, line: int | None = None) -> None:
        super().__init__(what)
        self.what = what
        self.line = line


# -- the file -----------------------------------------------------------------------------------------


def scene_classes(source: str) -> list[str]:
    """The Scene classes a file defines, read without running it (``class X(Scene)``, or a class
    deriving from another scene class of the file); empty when the text is not Python."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return []
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    scenes: list[str] = []
    changed = True
    while changed:
        changed = False
        for node in classes:
            if node.name in scenes:
                continue
            bases = [_base_name(b) for b in node.bases]
            if any(b is not None and (b.endswith("Scene") or b in scenes) for b in bases):
                scenes.append(node.name)
                changed = True
    return [node.name for node in classes if node.name in scenes]


def _base_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def scene_code(source: str, scene: str) -> str:
    """The file's text for a code layer (ADR 0019), which holds exactly one scene: the other scene
    classes are left out. Raises ``ValueError`` when the scene derives from another scene of the
    file (a code layer could not tell them apart)."""
    tree = ast.parse(source)
    scenes = set(scene_classes(source))
    if scene not in scenes:
        raise ValueError(f"the file has no scene {scene!r}")
    by_name = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}
    ancestors, todo = set(), [scene]
    while todo:
        node = by_name.get(todo.pop())
        for base in node.bases if node is not None else []:
            name = _base_name(base)
            if name in scenes and name not in ancestors:
                ancestors.add(name)
                todo.append(name)
    if ancestors:
        raise ValueError(
            f"{scene} derives from {', '.join(sorted(ancestors))}, another scene of the file: a code layer "
            "holds one scene"
        )
    lines = source.splitlines(keepends=True)
    drop: list[tuple[int, int]] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name in scenes and node.name != scene:
            first = min([node.lineno, *(d.lineno for d in node.decorator_list)])
            drop.append((first - 1, node.end_lineno))
    for start, end in sorted(drop, reverse=True):
        del lines[start:end]
    return "".join(lines)


# -- importing ---------------------------------------------------------------------------------------


def import_scene(recording: dict[str, Any], source: str | None = None) -> ImportResult:
    """The recorded scene as layers and clips, or - when anything in it cannot be reproduced exactly -
    as one code layer holding the scene (``source``: the file's text; read from the recording's
    ``file`` when not given). The report says what became what, and why when it did not."""
    canvas = _canvas(recording)
    reasons = [_where(p.get("what", ""), p.get("line")) for p in recording.get("problems", [])]
    if not reasons:
        try:
            return _Importer(recording, canvas).run()
        except Unsupported as exc:
            reasons = [_where(exc.what, exc.line)]
        except ValidationError as exc:  # a layer the project refuses: never a wrong project
            reasons = [str(exc.errors()[0]["msg"]).removeprefix("Value error, ")]
    return _as_code(recording, canvas, source, reasons)


def _where(what: str, line: int | None) -> str:
    return f"line {line}: {what}" if line else what


def _canvas(recording: dict[str, Any]) -> Canvas:
    data = recording.get("canvas", {})
    fps = int(data.get("fps", 30))
    duration = float(recording.get("duration", 0.0))
    return Canvas(
        width_px=int(data.get("width_px", 1280)),
        height_px=int(data.get("height_px", 720)),
        fps=fps,
        background=str(data.get("background", "#000000")),
        frame_height=float(data.get("frame_height", 8.0)),
        duration=duration if duration > 0 else 1.0,
    )


def _as_code(recording: dict, canvas: Canvas, source: str | None, reasons: list[str]) -> ImportResult:
    """The whole scene as one code layer (ADR 0019): frames exactly as Manim draws them."""
    name = str(recording.get("scene", "Scene"))
    if source is None:
        source = Path(recording.get("file", "")).read_text(encoding="utf-8")
    code = scene_code(source, name)
    layer = Layer(id="code-1", name=name, spec=Spec(type="Code", params={"code": code}))
    project = Project(canvas=canvas, layers=[layer])
    file = Path(str(recording.get("file", ""))).name
    report = [
        f"{name} ({file}) is kept as one code layer: Manim plays it and the editor shows its frames. "
        "Its objects cannot be edited one by one, because:",
        *(f"  - {why}" for why in reasons),
        "A code layer runs the scene's code on this computer (it asks before running a file's code).",
    ]
    report += _notes(recording)
    return ImportResult(project, report, False, reasons, {"code": 1})


def _notes(recording: dict) -> list[str]:
    return [f"Note: {note}" for note in recording.get("notes", [])]


# -- the pieces -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Piece:
    points: np.ndarray  # (n, 2)
    fill: np.ndarray  # (k, 4)
    stroke: np.ndarray
    background: np.ndarray
    rest: tuple  # widths, sheen, joints, caps: compared exactly

    def extent(self) -> float:
        if not len(self.points):
            return 0.0
        return float(np.ptp(self.points, axis=0).max())

    def invisible(self) -> bool:
        stroke_width, background_width = self.rest[0], self.rest[1]
        fill = not len(self.fill) or float(self.fill[:, 3].max()) <= 0
        stroke = stroke_width <= 0 or float(self.stroke[:, 3].max()) <= 0
        back = background_width <= 0 or float(self.background[:, 3].max()) <= 0
        return self.extent() < EPS or (fill and stroke and back)


def _rgbas(value: Any) -> np.ndarray:
    return np.asarray(value, dtype=float).reshape(-1, 4)


def _decode(piece: dict[str, Any]) -> _Piece:
    points = np.asarray(piece["points"], dtype=float)
    if points.shape[1] == 3:
        if np.abs(points[:, 2]).max(initial=0) > EPS:
            raise Unsupported("an object has points off the plane (3D): the editor's scene is flat")
        points = points[:, :2]
    fill, stroke = _rgbas(piece["fill"]), _rgbas(piece["stroke"])
    background = _rgbas(piece.get("background", [0.0, 0.0, 0.0, 1.0]))
    gradient = len(fill) > 1 or len(stroke) > 1 or len(background) > 1
    rest = (
        float(piece.get("stroke_width", 0.0)),
        float(piece.get("background_width", 0.0)),
        # Where a gradient runs; Manim turns it with the object, but one colour ignores it.
        tuple(float(v) for v in piece.get("sheen_direction", (-1.0, 1.0, 0.0))) if gradient else (),
        float(piece.get("sheen_factor", 0.0)),
        piece.get("joint", "AUTO"),
        piece.get("cap", "AUTO"),
        bool(piece.get("shade_in_3d", False)),
    )
    return _Piece(points, fill, stroke, background, rest)


@dataclass(frozen=True)
class _Motion:
    """A similarity of the plane from a layer's first state: ``p -> k R(angle) p + t``, and an
    opacity factor. The layer's keys are this composed with its base transform."""

    k: float = 1.0
    angle: float = 0.0  # degrees, not wrapped (a full turn is 360)
    t: tuple[float, float] = (0.0, 0.0)
    opacity: float = 1.0

    def matrix(self) -> np.ndarray:
        a = math.radians(self.angle)
        return self.k * np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])

    def apply(self, pieces: list[_Piece]) -> list[_Piece]:
        if self == _Motion():
            return pieces
        m, t = self.matrix(), np.asarray(self.t)
        out = []
        for p in pieces:
            fill, stroke, back = p.fill.copy(), p.stroke.copy(), p.background.copy()
            if self.opacity != 1:
                for rgbas in (fill, stroke, back):
                    rgbas[:, 3] *= self.opacity
            out.append(_Piece(p.points @ m.T + t, fill, stroke, back, p.rest))
        return out

    def scaled(self, kappa: float, shift: np.ndarray, ratio: float) -> _Motion:
        t = kappa * np.asarray(self.t) + shift
        return _Motion(self.k * kappa, self.angle, (float(t[0]), float(t[1])), self.opacity * ratio)

    def turned(self, angle: float, about: np.ndarray) -> _Motion:
        a = math.radians(angle)
        r = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
        t = r @ (np.asarray(self.t) - about) + about
        return _Motion(self.k, self.angle + angle, (float(t[0]), float(t[1])), self.opacity)


def _same_rest(a: tuple, b: tuple) -> bool:
    """Widths, sheen, joints and caps: equal (numbers up to rounding)."""
    for x, y in zip(a, b, strict=True):
        if isinstance(x, tuple):
            if len(x) != len(y) or any(abs(u - v) > 1e-9 for u, v in zip(x, y, strict=True)):
                return False
        elif isinstance(x, float):
            if abs(x - y) > 1e-9 * max(1.0, abs(x)):
                return False
        elif x != y:
            return False
    return True


def _same(a: list[_Piece], b: list[_Piece]) -> bool:
    if len(a) != len(b):
        return False
    for x, y in zip(a, b, strict=True):
        if x.points.shape != y.points.shape or not _same_rest(x.rest, y.rest):
            return False
        if len(x.points) and np.abs(x.points - y.points).max() > TOLERANCE * max(1.0, np.abs(y.points).max()):
            return False
        for u, v in ((x.fill, y.fill), (x.stroke, y.stroke), (x.background, y.background)):
            if u.shape != v.shape or np.abs(u - v).max(initial=0) > COLOUR_TOLERANCE:
                return False
    return True


def _box_centre(pieces: list[_Piece]) -> np.ndarray:
    points = np.vstack([p.points for p in pieces if len(p.points)])
    return (points.min(axis=0) + points.max(axis=0)) / 2


def _fit_scale(before: list[_Piece], after: list[_Piece]) -> tuple[float, np.ndarray, float] | None:
    """``(kappa, shift, ratio)`` with ``after = kappa * before + shift`` and its opacities ``ratio``
    times as much, every other colour and width the same; None when the change is not that."""
    if len(before) != len(after):
        return None
    for x, y in zip(before, after, strict=True):
        if x.points.shape != y.points.shape or not _same_rest(x.rest, y.rest):
            return None
        for u, v in ((x.fill, y.fill), (x.stroke, y.stroke), (x.background, y.background)):
            if u.shape != v.shape or np.abs(u[:, :3] - v[:, :3]).max(initial=0) > COLOUR_TOLERANCE:
                return None
    p0 = np.vstack([p.points for p in before])
    p1 = np.vstack([p.points for p in after])
    m0, m1 = p0.mean(axis=0), p1.mean(axis=0)
    c0, c1 = p0 - m0, p1 - m1
    norm = float((c0**2).sum())
    kappa = float((c0 * c1).sum()) / norm if norm > EPS else 1.0
    shift = m1 - kappa * m0
    size = max(1.0, float(np.abs(p1).max()))
    if np.abs(kappa * p0 + shift - p1).max() > TOLERANCE * size:
        return None
    a0 = np.concatenate([np.concatenate([p.fill[:, 3], p.stroke[:, 3], p.background[:, 3]]) for p in before])
    a1 = np.concatenate([np.concatenate([p.fill[:, 3], p.stroke[:, 3], p.background[:, 3]]) for p in after])
    dot = float(a0 @ a0)
    ratio = float(a0 @ a1) / dot if dot > EPS else 1.0
    if np.abs(a1 - ratio * a0).max(initial=0) > COLOUR_TOLERANCE:
        return None
    return kappa, shift, ratio


# -- the importer ------------------------------------------------------------------------------------


@dataclass
class _ClipBuild:
    kind: str
    start: float
    duration: float
    ease: dict | None
    params: dict[str, Any]
    motion: _Motion  # the layer's motion while it plays
    line: int | None
    to: _LayerBuild | None = None
    shift: tuple[float, float] | None = None  # a FadeIn/FadeOut move, in world units


@dataclass
class _LayerBuild:
    key: int  # creation order
    atom: int | None  # None: a copy that only plays a morph (TransformFromCopy)
    start: float
    pieces: list[_Piece]  # the first state, in world units
    leaves: list[tuple[str, str]]  # (raw leaf, state) of the first state: finds a built-in candidate
    raw_pieces: list[dict]  # the first state's recorded data (a shape's)
    name: str | None
    line: int | None
    motion: _Motion = field(default_factory=_Motion)
    clips: list[_ClipBuild] = field(default_factory=list)
    spans: list[tuple[float, float, str, dict | None, _Motion, _Motion, int | None]] = field(
        default_factory=list
    )  # keyframed moves: (start, end, kind, ease, motion before, motion after, line)
    busy: list[tuple[float, float]] = field(default_factory=list)
    end: float | None = None
    explicit_start: bool = False
    morph_in: bool = False
    morph_out: bool = False
    flat: bool = True  # its first state's tree is a shape's (a morph may pair pieces as a shape does)
    alt: tuple[list[tuple[str, str]], list[dict], bool] | None = None  # a morph target's own object
    needs: str | None = None  # a type a clip needs (letter by letter: Text)
    final: Layer | None = None
    spec_type: str = ""


class _Importer:
    def __init__(self, recording: dict[str, Any], canvas: Canvas) -> None:
        self.rec = recording
        self.canvas = canvas
        self.raw_states: dict[str, dict] = recording.get("states", {})
        self.decoded: dict[str, _Piece] = {}
        self.objects: dict[str, dict] = recording.get("objects", {})
        self.candidates = {
            "|".join(f"{a}:{b}" for a, b in c["leaves"]): c for c in recording.get("candidates", [])
        }
        self.layers: list[_LayerBuild] = []
        self.visible: dict[int, _LayerBuild] = {}
        self.ignored: dict[int, tuple[str, ...]] = {}  # what an ended layer left drawn (zero size)
        self.order: set[tuple[int, int]] = set()
        self.object_atoms: dict[tuple[str, ...], str] = {}  # renamed leaves -> object, for names
        self.sounds: list[dict] = []
        self.captions: list[dict] = []
        self.report_extra: list[str] = []

    # -- states ------------------------------------------------------------------------------------

    def piece(self, state: str) -> _Piece:
        piece = self.decoded.get(state)
        if piece is None:
            piece = self.decoded[state] = _decode(self.raw_states[state])
        return piece

    def pieces(self, states) -> list[_Piece]:
        return [self.piece(s) for s in states]

    # -- 1: names that survive morphs ----------------------------------------------------------------

    def renamed_steps(self) -> list[dict]:
        """The steps with each leaf named ``leaf#n``: after a morph the object that goes on is a new
        layer, so its pieces get new names (``n`` counts its morphs)."""
        epoch: dict[str, int] = {}

        def name(leaf: str) -> str:
            return f"{leaf}#{epoch.get(leaf, 0)}"

        def pairs(items) -> list[tuple[str, str]]:
            return [(name(leaf), state) for leaf, state in items or []]

        out = []
        for step in self.rec.get("steps", []):
            kind = step["type"]
            if kind == "frame":
                out.append({**step, "draw": pairs(step["draw"])})
            elif kind in ("add", "remove"):
                objects = [{**o, "leaves": pairs(o["leaves"]), "raw": o["leaves"]} for o in step["objects"]]
                out.append({**step, "objects": objects})
            elif kind == "play":
                anims = []
                for a in step["animations"]:
                    anims.append(
                        {
                            **a,
                            "at_begin": pairs(a.get("at_begin")),
                            "raw_begin": [tuple(x) for x in a.get("at_begin") or []],
                            "to_at_begin": pairs(a.get("to_at_begin")),
                            "raw_to_begin": [tuple(x) for x in a.get("to_at_begin") or []],
                        }
                    )
                before = pairs(step["before"])
                during = [name(leaf) for leaf in step["during"]]
                drawn_after = {leaf for leaf, _ in step["after"]}
                for a in step["animations"]:
                    if a.get("kind") in CLIP_KIND_INFO and CLIP_KIND_INFO[a["kind"]].category == "morph":
                        for leaf in _going_on(a, drawn_after):
                            epoch[leaf] = epoch.get(leaf, 0) + 1
                for item, a in zip(anims, step["animations"], strict=True):
                    item["at_finish"] = pairs(a.get("at_finish"))
                    item["to_at_finish"] = pairs(a.get("to_at_finish"))
                out.append(
                    {
                        **step,
                        "animations": anims,
                        "before": before,
                        "during": during,
                        "after": pairs(step["after"]),
                    }
                )
            else:
                out.append(step)
        return out

    # -- 2: which pieces make one layer --------------------------------------------------------------

    def atoms(self, steps: list[dict]) -> None:
        """Split the pieces into the fewest groups every object is made of, each a run of pieces in
        the order its objects draw them."""
        groups: list[list[str]] = []
        drawn: list[str] = []
        for step in steps:
            if step["type"] in ("add", "remove"):
                for o in step["objects"]:
                    leaves = [leaf for leaf, _ in o["leaves"]]
                    groups.append(leaves)
                    self.object_atoms.setdefault(tuple(leaves), o["object"])
            elif step["type"] == "play":
                for a in step["animations"]:
                    for key, obj in (
                        ("at_begin", "target"),
                        ("at_finish", "target"),
                        ("to_at_begin", "to"),
                        ("to_at_finish", "to"),
                    ):
                        leaves = [leaf for leaf, _ in a.get(key) or []]
                        if leaves:
                            groups.append(leaves)
                            if a.get(obj):
                                self.object_atoms.setdefault(tuple(leaves), a[obj])
                drawn += [leaf for leaf, _ in step["before"]] + [leaf for leaf, _ in step["after"]]
            elif step["type"] == "frame":
                drawn += [leaf for leaf, _ in step["draw"]]
        member: dict[str, set[int]] = {}
        for index, group in enumerate(groups):
            for leaf in group:
                member.setdefault(leaf, set()).add(index)
        known = set(member)
        self.internal = {leaf for leaf in drawn if leaf not in known}  # pieces an animation adds itself
        classes: dict[str, int] = {}
        signatures: dict[frozenset, int] = {}
        for leaf in member:
            classes[leaf] = signatures.setdefault(frozenset(member[leaf]), len(signatures))
        counter = itertools.count(len(signatures))
        for leaf in dict.fromkeys(self.internal):  # each drawn on its own: a layer if it stays drawn
            classes[leaf] = next(counter)
            groups.append([leaf])
        changed = True
        while changed:  # a group's pieces of one class must be one run in it: split the others
            changed = False
            for group in groups:
                seen: dict[int, int] = {}
                renamed: dict[int, int] = {}
                previous = None
                for leaf in group:
                    c = classes[leaf]
                    if c != previous:
                        if c in seen:
                            renamed.setdefault(c, next(counter))
                            changed = True
                        seen[c] = seen.get(c, 0) + 1
                    previous = c
                if renamed:
                    run_index: dict[int, int] = {}
                    previous = None
                    for leaf in group:
                        c = classes[leaf]
                        if c != previous:
                            run_index[c] = run_index.get(c, 0) + 1
                        previous = c
                        if c in renamed and run_index[c] > 1:
                            classes[leaf] = renamed[c]
                    break
        order: dict[int, list[str]] = {}
        for group in groups:
            for leaf in group:
                bucket = order.setdefault(classes[leaf], [])
                if leaf not in bucket:
                    bucket.append(leaf)
        self.atom_leaves: dict[int, list[str]] = order
        self.atom_of: dict[str, int] = {leaf: c for c, leaves in order.items() for leaf in leaves}

    def atom_name(self, atom: int | None) -> str:
        if atom is None:
            return "a copy"
        obj = self.object_atoms.get(tuple(self.atom_leaves[atom]))
        if obj is not None:
            info = self.objects.get(obj, {})
            label = info.get("name") or f"a {info.get('class', 'object')}"
            return f"{label} (line {info['line']})" if info.get("line") else label
        return "a part of an object"

    def object_name(self, obj: str | None) -> str | None:
        info = self.objects.get(obj or "", {})
        return info.get("name")

    def split(self, pairs: list[tuple[str, str]], line: int | None) -> list[tuple[int, list[str]]]:
        """``(atom, its states)`` for the atoms ``pairs`` covers, in order (each whole, in its order)."""
        out: list[tuple[int, list[str]]] = []
        position = 0
        while position < len(pairs):
            leaf = pairs[position][0]
            atom = self.atom_of.get(leaf)
            leaves = self.atom_leaves.get(atom, [])
            chunk = pairs[position : position + len(leaves)]
            if atom is None or [x for x, _ in chunk] != leaves:
                raise Unsupported(
                    "an animation acts on part of an object whose other parts move on their own", line
                )
            out.append((atom, [s for _, s in chunk]))
            position += len(leaves)
        return out

    def drawn_atoms(self, pairs: list[tuple[str, str]], line: int | None, skip: set[int]) -> dict[int, tuple]:
        """Each fully drawn atom's states; a partly drawn one cannot be a layer."""
        states = dict(pairs)
        out: dict[int, tuple] = {}
        for leaf, _ in pairs:
            atom = self.atom_of.get(leaf)
            if atom is None or atom in out or atom in skip:
                continue
            leaves = self.atom_leaves[atom]
            if not all(x in states for x in leaves):
                raise Unsupported(f"only part of {self.atom_name(atom)} is drawn", line)
            out[atom] = tuple(states[x] for x in leaves)
        return out

    # -- 3: the timeline ---------------------------------------------------------------------------

    def run(self) -> ImportResult:
        steps = self.renamed_steps()
        self.atoms(steps)
        for step in steps:
            kind = step["type"]
            if kind == "frame":
                self.on_draw(step["t"], step["draw"], None, set())
            elif kind == "play":
                self.on_play(step)
            elif kind == "sound":
                self.sounds.append(step)
            elif kind == "subcaption":
                self.captions.append(step)
        return self.finish()

    def new_layer(
        self,
        atom: int | None,
        states: tuple,
        t: float,
        line: int | None,
        raw: list[str] | None = None,
        explicit: bool = False,
    ) -> _LayerBuild:
        leaves = raw if raw is not None else [leaf.split("#")[0] for leaf in self.atom_leaves[atom]]
        obj = self.object_atoms.get(tuple(self.atom_leaves[atom])) if atom is not None else None
        layer = _LayerBuild(
            key=len(self.layers),
            atom=atom,
            start=t,
            pieces=self.pieces(states),
            leaves=list(zip(leaves, states, strict=True)),
            raw_pieces=[self.raw_states[s] for s in states],
            name=self.object_name(obj),
            line=self.objects.get(obj or "", {}).get("line"),
            explicit_start=explicit,
        )
        self.layers.append(layer)
        if atom is not None:
            self.visible[atom] = layer
            self.ignored.pop(atom, None)
        return layer

    def expected(self, layer: _LayerBuild) -> list[_Piece]:
        return layer.motion.apply(layer.pieces)

    def matches(self, layer: _LayerBuild, states) -> bool:
        return _same(self.expected(layer), self.pieces(states))

    def end(self, layer: _LayerBuild, t: float) -> None:
        layer.end = t
        if layer.atom is not None and self.visible.get(layer.atom) is layer:
            del self.visible[layer.atom]

    def on_draw(self, t: float, pairs, line, skip: set[int], play: bool = False) -> None:
        """What is drawn at ``t`` between animations: layers end, start and go on. As a play begins
        (``play``), pieces no object owns are the animation's own (a fade's ghost copy): left out."""
        if play:
            pairs = [(leaf, s) for leaf, s in pairs if leaf not in self.internal]
        drawn = self.drawn_atoms(pairs, line, skip)
        for atom, layer in list(self.visible.items()):
            if atom not in drawn and atom not in skip:
                self.end(layer, t)
        for atom, states in drawn.items():
            layer = self.visible.get(atom)
            if layer is not None and self.matches(layer, states):
                continue
            if layer is None and self.ignored.get(atom) == states:
                continue  # what a clip left drawn though invisible (ShrinkToCenter keeps a point)
            if layer is not None:
                if any(b > t + EPS for _, b in layer.busy):
                    raise Unsupported(f"{self.atom_name(atom)} changes while it is animated", line)
                self.end(layer, t)
            self.new_layer(atom, states, t, line, explicit=True)
        self.constrain([leaf for leaf, _ in pairs], dict(self.visible))

    def constrain(self, leaves: list[str], layers: dict[int, _LayerBuild]) -> None:
        """Layers drawn together keep Manim's order (its z-index sort included)."""
        sequence: list[_LayerBuild] = []
        for leaf in leaves:
            layer = layers.get(self.atom_of.get(leaf))
            if layer is None or (sequence and sequence[-1] is layer):
                continue
            if layer in sequence:
                raise Unsupported(
                    f"pieces of {self.atom_name(layer.atom)} are drawn between pieces of another object"
                )
            sequence.append(layer)
        for a, b in itertools.pairwise(sequence):
            self.order.add((a.key, b.key))

    def check_lane(self, layer: _LayerBuild, begin: float, start: float, end: float, what: str, line) -> None:
        if layer.morph_out:
            raise Unsupported(
                f"{what} comes after {self.atom_name(layer.atom)} has turned into another object", line
            )
        for a, b in layer.busy:
            if a < end - EPS and begin < b - EPS:
                raise Unsupported(
                    f"{what} plays while {self.atom_name(layer.atom)} is already animated", line
                )
        layer.busy.append((start, end))

    def on_play(self, step: dict) -> None:
        t0, line = step["t"], step["line"]
        anims = sorted(step["animations"], key=lambda a: (a["start"], a["begin"]))
        skip: set[int] = set()
        for a in anims:  # what a morph turns into appears through the morph
            if a.get("kind") in CLIP_KIND_INFO and CLIP_KIND_INFO[a["kind"]].category == "morph":
                skip |= {self.atom_of[leaf] for leaf, _ in a["to_at_begin"] if leaf in self.atom_of}
        self.on_draw(t0, step["before"], line, skip, play=True)
        playing: dict[int, _LayerBuild] = dict(self.visible)
        self.ended_here: set[int] = set()
        for a in anims:
            if a.get("kind") is None:
                raise Unsupported(f"{a['class']} is not an animation Manim Studio has", a.get("line"))
            category = CLIP_KIND_INFO[a["kind"]].category if a["kind"] in CLIP_KIND_INFO else a["kind"]
            if category == "morph":
                self.morph(step, a, playing)
            elif category == "keys":
                self.keyed(step, a)
            elif category == "rotate":
                self.rotation(step, a)
            else:
                self.clip(step, a, playing)
        self.constrain(step["during"], playing)
        self.verify_after(step)

    def layer_for(self, atom: int, states, t: float, introducer: bool, what: str, line) -> _LayerBuild:
        layer = self.visible.get(atom)
        if layer is None:
            if not introducer:
                raise Unsupported(f"{what} acts on {self.atom_name(atom)}, which is not on screen", line)
            return self.new_layer(atom, tuple(states), t, line)
        if not self.matches(layer, states):
            raise Unsupported(f"{self.atom_name(atom)} is not as its layer draws it when {what} begins", line)
        return layer

    def clip(self, step: dict, a: dict, playing: dict) -> None:
        t0, line, kind = step["t"], a.get("line"), a["kind"]
        info = CLIP_KIND_INFO[kind]
        parts = self.split(a["at_begin"], line)
        if len(parts) > 1 and not a.get("leafwise"):
            raise Unsupported(
                f"{a['class']} acts on a group whose parts are animated separately, and its parts would "
                "not be timed as in the whole",
                line,
            )
        total = len(a["at_begin"])
        lag = float(a.get("lag_ratio", 0.0))
        unit = a["duration"] / ((total - 1) * lag + 1) if total else a["duration"]
        index = 0
        for atom, states in parts:
            n = len(states)
            if len(parts) == 1:
                start, duration, params = t0 + a["start"], a["duration"], dict(a.get("params") or {})
            else:
                start = t0 + a["start"] + index * lag * unit
                duration = ((n - 1) * lag + 1) * unit
                params = {**(a.get("params") or {}), "lag_ratio": lag}
            index += n
            if duration <= EPS:
                raise Unsupported(f"{a['class']} takes no time", line)
            layer = self.layer_for(atom, states, start, info.introducer, a["class"], line)
            playing.setdefault(atom, layer)
            self.check_lane(layer, t0 + a["begin"], start, start + duration, a["class"], line)
            shift = None
            if kind in ("FadeIn", "FadeOut") and "shift" in params:
                shift = _direction(params["shift"])
            if info.only_types:
                layer.needs = sorted(info.only_types)[0]
            layer.clips.append(
                _ClipBuild(kind, start, duration, a.get("ease"), params, layer.motion, line, shift=shift)
            )
            if info.remover:
                self.end(layer, start + duration)
                self.ended_here.add(atom)

    def morph(self, step: dict, a: dict, playing: dict) -> None:
        t0, line = step["t"], a.get("line")
        start, end = t0 + a["start"], t0 + a["start"] + a["duration"]
        parts = self.split(a["at_begin"], line)
        if len(parts) != 1:
            raise Unsupported(f"{a['class']} turns a group whose parts are animated separately", line)
        atom, states = parts[0]
        if a.get("copy"):
            source = self.new_layer(
                None, tuple(states), start, line, raw=[x for x, _ in a["raw_begin"]], explicit=True
            )
            source.flat = bool(a.get("flat", True))
            for leaf in step["during"]:
                if any(leaf == x for x, _ in a["to_at_begin"]):
                    playing[self.atom_of.get(leaf)] = source
        else:
            source = self.layer_for(atom, states, start, False, a["class"], line)
            source.flat = source.flat and bool(a.get("flat", True))
        self.check_lane(source, t0 + a["begin"], start, end, a["class"], line)
        after = dict(step["after"])
        going = _going_on(a, after)
        if not going:
            raise Unsupported(f"nothing is left on screen after {a['class']}", line)
        cont = self.split([(leaf, after[leaf]) for leaf in going], line)
        if len(cont) != 1:
            raise Unsupported(f"what {a['class']} leaves is split between several objects", line)
        target_atom, target_states = cont[0]
        if target_atom in self.visible:
            raise Unsupported(
                f"{a['class']} turns into {self.atom_name(target_atom)}, which is already drawn", line
            )
        target = self.new_layer(target_atom, tuple(target_states), end, line)
        target.morph_in = True
        continuing_is_target = bool([leaf for leaf, _ in a["to_at_finish"] if leaf in after])
        target.flat = bool(a.get("to_finish_flat" if continuing_is_target else "finish_flat", True))
        raw_b = [x for x, _ in a["raw_to_begin"]]
        if raw_b:
            b_pieces = [self.raw_states[s] for _, s in a["raw_to_begin"]]
            target.alt = (
                list(zip(raw_b, [s for _, s in a["raw_to_begin"]], strict=True)),
                b_pieces,
                bool(a.get("to_flat", True)),
            )
            if not _same(self.pieces([s for _, s in a["raw_to_begin"]]), target.pieces) and not _drawn_alike(
                self.pieces([s for _, s in a["raw_to_begin"]]), target.pieces
            ):
                target.alt = None
        source.clips.append(
            _ClipBuild(
                a["kind"],
                start,
                end - start,
                a.get("ease"),
                dict(a.get("params") or {}),
                source.motion,
                line,
                to=target,
            )
        )
        source.morph_out = True
        self.end(source, end)
        if not a.get("copy"):
            self.ended_here.add(atom)

    def keyed(self, step: dict, a: dict) -> None:
        t0, line = step["t"], a.get("line")
        start, end = t0 + a["start"], t0 + a["start"] + a["duration"]
        before = self.split(a["at_begin"], line)
        after = {atom: states for atom, states in self.split(a["at_finish"], line)}
        for atom, states in before:
            layer = self.layer_for(atom, states, start, False, a["class"], line)
            self.check_lane(layer, t0 + a["begin"], start, end, a["class"], line)
            fit = _fit_scale(self.pieces(states), self.pieces(after.get(atom, ())))
            if fit is None:
                raise Unsupported(
                    f"{a['class']} on {self.atom_name(atom)} is not a move, a uniform scale or a fade "
                    "(colours or shape change, or it turns: keys cannot redo it)",
                    line,
                )
            kappa, shift, ratio = fit
            moved = layer.motion.scaled(kappa, shift, ratio)
            if moved.opacity > 1 + 1e-9:
                raise Unsupported(
                    f"{a['class']} makes {self.atom_name(atom)} more opaque than it began", line
                )
            layer.spans.append((start, end, "keys", a.get("ease"), layer.motion, moved, line))
            layer.motion = moved

    def rotation(self, step: dict, a: dict) -> None:
        t0, line = step["t"], a.get("line")
        start, end = t0 + a["start"], t0 + a["start"] + a["duration"]
        (atom, states), *rest = self.split(a["at_begin"], line)
        if rest:
            raise Unsupported(f"{a['class']} turns a group whose parts are animated separately", line)
        layer = self.layer_for(atom, states, start, False, a["class"], line)
        self.check_lane(layer, t0 + a["begin"], start, end, a["class"], line)
        about = np.asarray(a["about"], dtype=float)
        turned = layer.motion.turned(float(a["angle"]), about)
        finish = dict(a["at_finish"])
        if not _same(
            turned.apply(layer.pieces), self.pieces([finish.get(leaf) for leaf in self.atom_leaves[atom]])
        ):
            raise Unsupported(f"{a['class']} does not end as a turn of {self.atom_name(atom)}", line)
        layer.spans.append((start, end, "rotate", a.get("ease"), layer.motion, turned, line))
        layer.motion = turned

    def verify_after(self, step: dict) -> None:
        t, line = step["t"] + step["duration"], step["line"]
        pairs = list(step["after"])
        drawn = self.drawn_atoms(pairs, line, set())
        for atom, layer in list(self.visible.items()):
            if atom not in drawn and (layer.end is None or layer.end > t + EPS):
                raise Unsupported(f"{self.atom_name(atom)} disappears without an animation", line)
        for atom, states in drawn.items():
            layer = self.visible.get(atom)
            if layer is None:
                if atom in self.ended_here and all(p.invisible() for p in self.pieces(states)):
                    self.ignored[atom] = states  # ShrinkToCenter leaves a point drawn: the layer ended
                    continue
                if self.ignored.get(atom) == states:
                    continue
                raise Unsupported(f"{self.atom_name(atom)} appears during a play without an animation", line)
            if not self.matches(layer, states):
                raise Unsupported(
                    f"{self.atom_name(atom)} does not end as its clips leave it (an animation with an "
                    "unusual ease or arguments)",
                    line,
                )
        self.constrain([leaf for leaf, _ in pairs], dict(self.visible))

    # -- 4: layers -----------------------------------------------------------------------------------

    def finish(self) -> ImportResult:
        for layer in self.layers:
            self.build(layer)
        ordered = self.stacking()
        ids: set[str] = set()
        for layer in ordered:
            stem = re.sub(r"[^a-z0-9]+", "-", layer.spec_type.lower()).strip("-") or "layer"
            n = 1
            while f"{stem}-{n}" in ids:
                n += 1
            layer.final = layer.final.model_copy(update={"id": f"{stem}-{n}"})
            ids.add(layer.final.id)
        by_key = {layer.key: layer for layer in ordered}
        final_layers = []
        for layer in ordered:
            clips = []
            for clip in layer.final.clips:
                if clip.to_layer is not None:
                    clip = clip.model_copy(update={"to_layer": by_key[int(clip.to_layer)].final.id})
                clips.append(clip)
            final_layers.append(
                Layer.model_validate(
                    {**layer.final.model_dump(by_alias=True), "clips": [c.model_dump() for c in clips]}
                )
            )
        audio, sound_notes = self.audio()
        cues, cue_notes = self.cues()
        project = Project(
            canvas=self.canvas,
            layers=final_layers,
            audio=audio,
            subtitles=cues,
            subtitle_style=SubtitleStyle(burn_in=False),
        )
        return self.result(project, ordered, sound_notes + cue_notes)

    def stacking(self) -> list[_LayerBuild]:
        """The layers in an order every frame agrees with (Manim's drawing order)."""
        after: dict[int, set[int]] = {layer.key: set() for layer in self.layers}
        need: dict[int, int] = {layer.key: 0 for layer in self.layers}
        for a, b in self.order:
            if b not in after[a]:
                after[a].add(b)
                need[b] += 1
        ready = [key for key, n in need.items() if n == 0]
        heapq.heapify(ready)
        out = []
        while ready:
            key = heapq.heappop(ready)
            out.append(key)
            for nxt in after[key]:
                need[nxt] -= 1
                if need[nxt] == 0:
                    heapq.heappush(ready, nxt)
        if len(out) != len(self.layers):
            raise Unsupported("the drawing order of the objects changes in a way layers cannot follow")
        by_key = {layer.key: layer for layer in self.layers}
        return [by_key[key] for key in out]

    def build(self, layer: _LayerBuild) -> None:
        """The layer's spec (a built-in object when one rebuilds it and suits its clips, else a shape),
        transform, keys, clips and lifetime."""
        structural = any(c.kind in STRUCTURAL for c in layer.clips) or layer.morph_out
        options: list[tuple[str, Spec, dict, list]] = []
        sources = [(layer.leaves, layer.raw_pieces, layer.flat)]
        if layer.alt is not None and not structural:
            sources.insert(0, layer.alt)
        reasons: list[str] = []
        for leaves, raw, flat in sources:
            candidate = self.candidates.get("|".join(f"{a}:{b}" for a, b in leaves))
            if candidate is not None:
                ends_morph = layer.morph_in or layer.morph_out
                if ends_morph and not candidate.get("structure", False):
                    reasons.append(f"its {candidate['spec']['type']} has other sub-objects than Manim's")
                else:
                    options.append(
                        ("builtin", Spec.model_validate(candidate["spec"]), candidate["base"], raw)
                    )
            if (layer.morph_in or layer.morph_out) and not flat:
                reasons.append("it is a nested group: a morph would pair other pieces")
                continue
            options.append(
                ("shape", _shape_spec(raw), {"position": None, "rotation": 0.0, "scale": 1.0}, raw)
            )
        for _kind, spec, base, raw in options:
            if layer.needs and spec.type != layer.needs:
                reasons.append(f"a clip needs a {layer.needs}")
                continue
            try:
                layer.final = self.assemble(layer, spec, base, raw)
            except Unsupported as exc:
                reasons.append(exc.what)
                continue
            layer.spec_type = spec.type
            return
        raise Unsupported(
            f"{self.atom_name(layer.atom)} cannot be a layer: {'; '.join(dict.fromkeys(reasons))}", layer.line
        )

    def assemble(self, layer: _LayerBuild, spec: Spec, base: dict, raw: list[dict]) -> Layer:
        pieces = [_decode(p) for p in raw]
        if base["position"] is None:  # a shape: its data centred, placed by its box's centre
            centre = _box_centre(pieces)
            base = {"position": [float(centre[0]), float(centre[1])], "rotation": 0.0, "scale": 1.0}
        s0, angle0 = float(base["scale"]), float(base["rotation"])
        p0 = np.asarray(base["position"], dtype=float)
        anchor = self.anchor(layer, s0, angle0, p0)

        def transform(motion: _Motion) -> tuple[float, float, tuple[float, float], float]:
            s, angle = motion.k * s0, motion.angle + angle0
            a = math.radians(angle)
            m = s * np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
            offset = motion.matrix() @ p0 + np.asarray(motion.t)
            position = offset - anchor + m @ anchor
            return s, angle, (float(position[0]), float(position[1])), motion.opacity

        clips = []
        for index, clip in enumerate(layer.clips):
            s, angle, _, opacity = transform(clip.motion)
            self.check_safe(clip, s, angle, opacity)
            params = dict(clip.params)
            if clip.shift is not None and (abs(s - 1) > EPS or abs(angle % 360) > EPS):
                a = -math.radians(angle)
                local = (
                    np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
                    @ np.asarray(clip.shift)
                    / s
                )
                params["shift"] = [float(local[0]), float(local[1])]
            clips.append(
                Clip(
                    id=f"{clip.kind.lower()}-{index + 1}",
                    kind=clip.kind,
                    start=clip.start,
                    duration=clip.duration,
                    ease=Easing(**clip.ease) if clip.ease else None,
                    params=params,
                    to_layer=str(clip.to.key) if clip.to is not None else None,
                )
            )
        first = transform(_Motion())
        tracks: dict[str, list[Keyframe]] = {}
        for start, end, kind, ease, before, after, line in layer.spans:
            v0, v1 = transform(before), transform(after)
            if kind == "rotate" and math.dist(v0[2], v1[2]) > TOLERANCE:
                raise Unsupported("it turns about a point keys cannot hold still", line)
            for index, prop in enumerate(("scale", "rotation", "position", "opacity")):
                a, b = v0[index], v1[index]
                if (math.dist(a, b) if prop == "position" else abs(a - b)) <= EPS:
                    continue
                track = tracks.setdefault(prop, [])
                easing = Easing(**ease) if ease else Easing(name="smooth")
                if track and abs(track[-1].t - start) <= EPS:
                    track[-1] = track[-1].model_copy(update={"ease": easing})
                else:
                    if track and track[-1].t > start + EPS:
                        raise Unsupported("two moves of it overlap", line)
                    track.append(Keyframe(t=start, value=a, ease=easing))
                track.append(Keyframe(t=end, value=b))
        base_transform = Transform2D(
            position=first[2],
            scale=first[0],
            rotation=first[1],
            opacity=first[3],
            anchor=(float(anchor[0]), float(anchor[1])),
        )
        built = Layer(
            id=str(layer.key),
            name=layer.name or "",
            spec=spec,
            base=base_transform,
            tracks=tracks,
            clips=clips,
        )
        start, end = layer.start, layer.end if layer.end is not None else math.inf
        inferred = infer_lifetime(built, _MorphIn(layer.start) if layer.morph_in else None)
        lifetime = Lifetime(
            in_=None if abs(inferred[0] - start) <= EPS else start,
            out=None
            if (math.isinf(end) and math.isinf(inferred[1])) or abs(inferred[1] - end) <= EPS
            else end,
        )
        if layer.morph_in and lifetime.in_ is not None:
            raise Unsupported("a morph target that starts at another time")
        return built.model_copy(update={"lifetime": lifetime})

    def anchor(self, layer: _LayerBuild, s0: float, angle0: float, p0: np.ndarray) -> np.ndarray:
        """The point (in the object's own units) its turns turn about: keys hold it still. Every turn
        of a layer must turn about the same point of the object."""
        found: np.ndarray | None = None
        for _start, _end, kind, _ease, before, after, line in layer.spans:
            if kind != "rotate":
                continue
            # The fixed point of before -> after, in world units, mapped back into the object's units.
            mb, ma = before.matrix(), after.matrix()
            tb, ta = np.asarray(before.t), np.asarray(after.t)
            delta = ma @ np.linalg.inv(mb)
            shift = ta - delta @ tb
            try:
                fixed = np.linalg.solve(np.eye(2) - delta, shift)
            except np.linalg.LinAlgError:
                continue  # a whole number of turns: any point stays
            a = math.radians(angle0)
            base = s0 * np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
            local = np.linalg.solve(base, np.linalg.solve(mb, fixed - tb) - p0)
            if found is not None and np.abs(local - found).max() > TOLERANCE:
                raise Unsupported("it turns about different points of itself", line)
            found = local
        return found if found is not None else np.zeros(2)

    def check_safe(self, clip: _ClipBuild, s: float, angle: float, opacity: float) -> None:
        info = CLIP_KIND_INFO[clip.kind]
        if info.category == "morph":
            return
        if abs(s - 1) > EPS and clip.kind not in SCALE_SAFE:
            raise Unsupported(f"its {clip.kind} would be scaled with it", clip.line)
        if abs(math.remainder(angle, 360)) > EPS and clip.kind not in TURN_SAFE:
            raise Unsupported(f"its {clip.kind} would be turned with it", clip.line)
        if (
            clip.kind in ("FadeIn", "FadeOut")
            and "scale" in clip.params
            and abs(math.remainder(angle, 360)) > EPS
        ):
            raise Unsupported(f"its {clip.kind} would grow about another centre", clip.line)
        if abs(opacity - 1) > EPS and clip.kind not in FADE_SAFE:
            raise Unsupported(f"its {clip.kind} would be faded with it", clip.line)

    # -- sound and subtitles ---------------------------------------------------------------------------

    def audio(self) -> tuple[list[AudioClip], list[str]]:
        from . import audio as sound

        clips, notes = [], []
        for n, step in enumerate(self.sounds, start=1):
            path = step["path"]
            length = sound.probe(path) if step.get("exists") else None
            if not length:
                notes.append(
                    f"Not imported: the sound {Path(path).name} (line {step.get('line')}) cannot be read"
                )
                continue
            clips.append(
                AudioClip(
                    id=f"sound-{n}",
                    name=Path(path).stem,
                    path=path,
                    start=max(0.0, step["t"]),
                    duration=length,
                    gain=step.get("gain", 0.0),
                )
            )
        return clips, notes

    def cues(self) -> tuple[list[Cue], list[str]]:
        cues, notes = [], []
        for n, step in enumerate(sorted(self.captions, key=lambda s: s["t"]), start=1):
            start, end = max(0.0, step["t"]), step["t"] + step["duration"]
            if end <= start or (cues and start < cues[-1].end - EPS):
                notes.append(f"Not imported: the subtitle {step['text']!r} overlaps another (one lane)")
                continue
            cues.append(Cue(id=f"cue-{n}", start=start, end=end, text=step["text"]))
        return cues, notes

    # -- the report ---------------------------------------------------------------------------------

    def result(self, project: Project, ordered: list[_LayerBuild], notes: list[str]) -> ImportResult:
        types = [layer.spec_type for layer in ordered]
        built = [t for t in types if t != "Shape"]
        shapes = types.count("Shape")
        clips = sum(len(layer.final.clips) for layer in ordered)
        moves = sum(len(layer.spans) for layer in ordered)
        name = self.rec.get("scene", "Scene")
        file = Path(str(self.rec.get("file", ""))).name
        report = [
            f"Imported {name} ({file}): {len(ordered)} layers ({len(built)} built-in objects, "
            f"{shapes} shapes), {clips} clips, {moves} keyframed moves, {project.canvas.duration:g} s.",
        ]
        for layer in ordered:
            label = layer.name or layer.final.label
            where = f" (line {layer.line})" if layer.line else ""
            what = "a shape: its exact drawing" if layer.spec_type == "Shape" else f"a {layer.spec_type}"
            parts = [f"{c.kind} at {c.start:.2f} s" for c in layer.final.clips]
            if layer.spans:
                parts.append(f"{len(layer.spans)} keyframed move{'s' if len(layer.spans) > 1 else ''}")
            tail = f": {', '.join(parts)}" if parts else ""
            report.append(f"  {label}{where} -> {what}{tail}")
        latex = [t for t in types if t in LATEX_TYPES]
        if latex:
            report.append(
                f"{len(latex)} equation{'s are' if len(latex) > 1 else ' is'} kept as LaTeX (MathTex/Tex): "
                "drawing them needs LaTeX on this computer; Freeze to Shape makes them plain data "
                "that does not."
            )
        if project.subtitles:
            report.append("Subtitles are not burned into the video (Manim writes them as an .srt file).")
        report += notes + _notes(self.rec)
        counts = {
            "layers": len(ordered),
            "builtin": len(built),
            "shapes": shapes,
            "clips": clips,
            "moves": moves,
        }
        return ImportResult(project, report, True, [], counts)


@dataclass(frozen=True)
class _MorphIn:
    """What ``infer_lifetime`` reads of the morph into a layer: when it ends."""

    end: float


def _going_on(anim: dict, drawn: set[str] | dict) -> list[str]:
    """The pieces of what a morph leaves on screen: its target's (ReplacementTransform, FadeTransform,
    TransformFromCopy), else its source's (Transform keeps the source, turned into the target)."""
    target = [leaf for leaf, _ in anim.get("to_at_finish") or [] if leaf in drawn]
    return target or [leaf for leaf, _ in anim.get("at_finish") or [] if leaf in drawn]


def _shape_spec(raw: list[dict]) -> Spec:
    """A shape (ADR 0052) of the recorded pieces, centred as the editor builds every object."""
    pieces = [_decode(p) for p in raw]
    centre = _box_centre(pieces)
    shapes = []
    for data in raw:
        piece = {k: v for k, v in data.items() if k != "z_index"}  # the layer order draws it (ADR 0053)
        points = np.asarray(data["points"], dtype=float)
        points[:, 0] -= centre[0]
        points[:, 1] -= centre[1]
        piece["points"] = points.tolist()
        shapes.append(piece)
    return Spec(type="Shape", params={"version": 1, "shapes": shapes})


def _direction(value: Any) -> tuple[float, float]:
    names = {"UP": (0.0, 1.0), "DOWN": (0.0, -1.0), "LEFT": (-1.0, 0.0), "RIGHT": (1.0, 0.0)}
    if isinstance(value, str):
        return names[value]
    return float(value[0]), float(value[1])


def _drawn_alike(a: list[_Piece], b: list[_Piece]) -> bool:
    """Do two states draw the same thing although cut into other curves (a morph's end aligned with
    its source: the same box and colours)? The editor may then build the target's own object."""
    a, b = [p for p in a if not p.invisible()], [p for p in b if not p.invisible()]
    if not a or not b:
        return False

    def box(pieces: list[_Piece]) -> np.ndarray:
        points = np.vstack([p.points for p in pieces])
        return np.concatenate([points.min(axis=0), points.max(axis=0)])

    def colours(pieces: list[_Piece]) -> set:
        return {tuple(np.round(np.concatenate([p.fill[0], p.stroke[0]]), 6)) for p in pieces if len(p.points)}

    return bool(np.abs(box(a) - box(b)).max() < TOLERANCE * 10) and colours(a) == colours(b)
