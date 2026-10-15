"""SVG layers and media files (P3e.1, ADR 0027).

An SVG keeps its own colours, is drawn on by every vector clip kind in any
order, and is rebuilt when its file changes on disk (after ``check_media``).
A missing, broken or empty file draws a dashed placeholder instead of failing,
in the editor and the export alike.
"""

from __future__ import annotations

import os
import random

import av
import manim as m
import numpy as np
import pytest
from tests.support import CANVAS, FRAMES, assert_frames_equal, max_diff, render_in_order, sequential_reference

from manim_studio.core import adapter
from manim_studio.core.evaluator import Evaluator
from manim_studio.core.schema import Clip, Layer, Project, Spec, Transform2D
from manim_studio.render.cairo_export import export_video, make_camera, render_frame

SHAPES = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
  <rect x="5" y="5" width="40" height="40" fill="#f97316" stroke="#111827" stroke-width="2"/>
  <circle cx="70" cy="30" r="20" fill="#22d3ee"/>
  <path d="M10 90 C 30 50, 70 50, 90 90" fill="none" stroke="#a3e635" stroke-width="4"/>
</svg>"""
# A dot first, then a long line: MoveAlongPath must follow the line (the longest path).
TRACK = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100">
  <circle cx="10" cy="10" r="2" fill="#ffffff"/>
  <path d="M0 50 L200 50" fill="none" stroke="#ffffff" stroke-width="2"/>
</svg>"""
BAR = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
  <rect x="0" y="40" width="100" height="20" fill="#e11d48"/>
</svg>"""


@pytest.fixture
def svg(tmp_path):
    def write(text: str, name: str = "drawing.svg") -> str:
        path = tmp_path / name
        path.write_text(text, encoding="utf-8")
        return str(path)

    return write


def spec(path: str, **params) -> Spec:
    return Spec(type="SVGMobject", params={"path": path, **params})


def project(*layers: Layer) -> Project:
    return Project(canvas=CANVAS, layers=list(layers))


def frame(evaluator: Evaluator, t: float) -> np.ndarray:
    return render_frame(make_camera(CANVAS), evaluator.frame(t))


def is_placeholder(mob: m.Mobject) -> bool:
    return isinstance(mob, m.DashedVMobject)


# -- building ----------------------------------------------------------------------------------------


def test_an_svg_keeps_its_colours_and_takes_the_height(svg) -> None:
    mob = adapter.build_mobject(spec(svg(SHAPES), height=3.0))
    fills = {sub.get_fill_color().to_hex().lower() for sub in mob.family_members_with_points()}
    assert {"#f97316", "#22d3ee"} <= fills
    assert mob.height == pytest.approx(3.0)
    assert np.allclose(mob.get_center(), 0.0, atol=1e-9)


def test_style_overrides_the_files_colours(svg) -> None:
    mob = adapter.build_mobject(
        Spec(type="SVGMobject", params={"path": svg(SHAPES)}, style={"fill": "#ffffff"})
    )
    assert {sub.get_fill_color().to_hex().lower() for sub in mob.family_members_with_points()} == {"#ffffff"}


def test_svgs_take_every_vector_clip_kind() -> None:
    kinds = adapter.allowed_clip_kinds("SVGMobject")
    assert {"Create", "Write", "DrawBorderThenFill", "SpiralIn", "Wiggle", "MoveAlongPath"} <= set(kinds)
    assert "AddTextLetterByLetter" not in kinds


@pytest.mark.parametrize(
    "kind", ["DrawBorderThenFill", "Create", "Write", "FadeIn", "SpiralIn", "Circumscribe"]
)
def test_drawing_clips_scrub_like_they_play(svg, kind: str) -> None:
    drawing = spec(svg(SHAPES))
    reference = sequential_reference(kind, drawing)
    one = project(Layer(id="a", spec=drawing, clips=[Clip(id="c", kind=kind, start=0, duration=1)]))
    shuffled = random.Random(4).sample(range(len(FRAMES)), len(FRAMES))
    assert_frames_equal(reference, render_in_order(one, shuffled), f"{kind} scrubbed")
    assert_frames_equal(reference, render_in_order(one, shuffled, fresh_each_frame=True), f"{kind} fresh")


# -- files that cannot be drawn ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("make", "problem"),
    [
        (lambda svg: svg("<svg><path d='M0 0 L", "broken.svg"), "cannot read the file (ParseError)"),
        (
            lambda svg: svg("<svg xmlns='http://www.w3.org/2000/svg'></svg>", "empty.svg"),
            "the drawing is empty",
        ),
        (lambda svg: svg(SHAPES, "gone.svg").replace("gone", "never"), "file not found"),
        (lambda svg: "", "no file chosen"),
    ],
)
def test_a_file_that_cannot_be_drawn_shows_a_placeholder(svg, make, problem) -> None:
    layer = Layer(
        id="logo", spec=spec(make(svg), height=1.5), clips=[Clip(id="c", kind="Create", start=0, duration=1)]
    )
    evaluator = Evaluator(project(layer))
    for t in (0.0, 0.5, 0.99):
        evaluator.frame(t)  # never raises
    assert evaluator.build_errors() == {"logo": problem}
    rest = Evaluator(project(layer.model_copy(update={"clips": []})))
    (mob,) = rest.frame(0.5)
    assert is_placeholder(mob)
    assert mob.height == pytest.approx(1.5, abs=0.05)  # the layer's size: the layout does not jump


def test_a_missing_image_shows_a_placeholder_too(tmp_path) -> None:
    layer = Layer(id="pic", spec=Spec(type="ImageMobject", params={"path": str(tmp_path / "none.png")}))
    evaluator = Evaluator(project(layer))
    (mob,) = evaluator.frame(0.5)
    assert is_placeholder(mob)
    assert evaluator.build_errors() == {"pic": "file not found"}


def test_good_files_report_no_problem(svg) -> None:
    evaluator = Evaluator(project(Layer(id="logo", spec=spec(svg(SHAPES)))))
    evaluator.frame(0.0)
    assert evaluator.build_errors() == {}


def test_the_export_draws_the_placeholder_too(tmp_path) -> None:
    layer = Layer(
        id="logo",
        spec=spec(str(tmp_path / "gone.svg")),
        clips=[Clip(id="c", kind="Write", start=0, duration=1)],
    )
    out = tmp_path / "missing.mp4"
    export_video(project(layer), out)
    with av.open(str(out)) as container:
        frames = [f.to_ndarray(format="rgb24") for f in container.decode(video=0)]
    expected = frame(Evaluator(project(layer)), FRAMES[-1])[:, :, :3].astype(int)
    assert np.abs(frames[-1].astype(int) - expected).mean() < 3


# -- files changed on disk ------------------------------------------------------------------------------


def test_a_changed_file_is_redrawn_after_check_media(svg) -> None:
    path = svg(SHAPES)
    layer = Layer(id="logo", spec=spec(path), clips=[Clip(id="in", kind="FadeIn", start=0, duration=0.4)])
    evaluator = Evaluator(project(layer))
    before = {t: frame(evaluator, t) for t in (0.2, 0.8)}  # in the clip, and after it (a checkpoint)
    assert evaluator.check_media() == set()

    svg(BAR)  # rewritten in another program
    assert all(np.array_equal(frame(evaluator, t), before[t]) for t in before)  # not until checked
    assert evaluator.check_media() == {"logo"}
    fresh = Evaluator(project(layer))
    for t in before:
        now = frame(evaluator, t)
        assert max_diff(now, before[t]) > 50, t
        assert np.array_equal(now, frame(fresh, t)), t  # exactly what a fresh evaluator draws
    assert evaluator.check_media() == set()


def test_a_deleted_file_turns_into_a_placeholder_and_back(svg, tmp_path) -> None:
    path = svg(SHAPES)
    evaluator = Evaluator(project(Layer(id="logo", spec=spec(path))))
    good = frame(evaluator, 0.5)
    hidden = tmp_path / "away.svg"
    (tmp_path / "drawing.svg").rename(hidden)
    assert evaluator.check_media() == {"logo"}
    (mob,) = evaluator.frame(0.5)
    assert is_placeholder(mob) and evaluator.build_errors() == {"logo": "file not found"}
    hidden.rename(path)
    assert evaluator.check_media() == {"logo"}
    assert np.array_equal(frame(evaluator, 0.5), good)


# -- moving along an SVG -------------------------------------------------------------------------------


def runner(path_layer: str = "track") -> Layer:
    return Layer(
        id="dot",
        spec=Spec(type="Dot", params={"radius": 0.2}),
        base=Transform2D(position=(0.0, -3.0)),
        clips=[
            Clip(
                id="run",
                kind="MoveAlongPath",
                start=0,
                duration=1,
                params={"path": path_layer},
                ease={"name": "linear"},
            )
        ],
    )


def centre(evaluator: Evaluator, t: float) -> np.ndarray:
    return dict(evaluator.frame_layers(t))["dot"].get_center()


def test_moving_along_an_svg_follows_its_longest_path(svg) -> None:
    track = Layer(id="track", spec=spec(svg(TRACK), height=2.0), base=Transform2D(position=(0.0, 1.0)))
    evaluator = Evaluator(project(track, runner()))
    line = adapter.longest_path(adapter.build_mobject(track.spec)).copy().shift((0.0, 1.0, 0.0))
    start, end = line.get_start(), line.get_end()
    assert abs(end[0] - start[0]) > 3  # the line, not the dot
    assert np.allclose(centre(evaluator, 0.0), start, atol=1e-6)
    assert np.allclose(centre(evaluator, 0.5), (start + end) / 2, atol=1e-6)
    assert np.allclose(centre(evaluator, 0.999), start + (end - start) * 0.999, atol=1e-3)


def test_a_follower_takes_the_new_path_when_the_file_changes(svg) -> None:
    path = svg(TRACK, "track.svg")
    track = Layer(id="track", spec=spec(path))
    evaluator = Evaluator(project(track, runner()))
    before = centre(evaluator, 0.25)
    edited = svg(TRACK.replace("M0 50 L200 50", "M0 10 L200 90"), "track.svg")
    stat = os.stat(edited)  # same size: make sure the save is not in the same clock tick as the first
    os.utime(edited, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
    assert evaluator.check_media() == {"track"}
    after = centre(evaluator, 0.25)
    assert not np.allclose(before, after)
    assert np.allclose(after, centre(Evaluator(project(track, runner())), 0.25))


def test_a_missing_path_drawing_leaves_the_follower_at_its_placeholder(tmp_path) -> None:
    track = Layer(id="track", spec=spec(str(tmp_path / "gone.svg")), base=Transform2D(position=(2.0, 1.0)))
    evaluator = Evaluator(project(track, runner()))
    for t in (0.0, 0.5, 0.99):
        assert np.allclose(centre(evaluator, t), (2.0, 1.0, 0.0), atol=1e-6), t
