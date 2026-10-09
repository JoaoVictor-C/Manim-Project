"""Hit-testing on the canvas (S3.2, ADR 0016)."""

from __future__ import annotations

import numpy as np
import pytest

from manim_studio.core.evaluator import Evaluator
from manim_studio.core.schema import Canvas, Clip, Layer, Project, Spec, Transform2D
from manim_studio.render.hit_test import VISIBLE_ALPHA, hit_layers

CANVAS = Canvas(width_px=960, height_px=540, duration=2.0)
PX = CANVAS.width_px / CANVAS.frame_width  # pixels per Manim unit
FILLED = {"fill": "#3b82f6", "fill_opacity": 0.8}


def hits_at(project: Project, point, t: float = 0.0) -> list[str]:
    return hit_layers(Evaluator(project).frame_layers(t), point, PX)


def scene(*layers: Layer) -> Project:
    return Project(canvas=CANVAS, layers=list(layers))


def test_filled_shape_hits_inside_not_outside() -> None:
    project = scene(Layer(id="sq", spec=Spec(type="Square", params={"side_length": 2}, style=FILLED)))
    assert hits_at(project, (0.5, 0.5)) == ["sq"]
    assert hits_at(project, (1.5, 0.0)) == []


def test_outline_only_shape_hits_on_its_stroke_not_its_hole() -> None:
    project = scene(Layer(id="ring", spec=Spec(type="Circle", params={"radius": 2})))  # Manim: stroke only
    assert hits_at(project, (0.0, 0.0)) == []
    assert hits_at(project, (2.0, 0.0)) == ["ring"]
    diag = 2 / np.sqrt(2)  # between two anchors: the curve, not its chord
    assert hits_at(project, (diag, diag)) == ["ring"]
    assert hits_at(project, (2.0 + 3 / PX, 0.0)) == ["ring"]  # within 4 px
    assert hits_at(project, (2.0 + 9 / PX, 0.0)) == []


def test_a_line_is_hit_along_its_length_only() -> None:
    project = scene(Layer(id="ln", spec=Spec(type="Line", params={"start": [-2, -1], "end": [2, 1]})))
    assert hits_at(project, (1.0, 0.5)) == ["ln"]
    assert hits_at(project, (1.0, -0.5)) == []  # inside the bounding box, far from the line


def test_text_hits_anywhere_in_its_box() -> None:
    project = scene(Layer(id="t", spec=Spec(type="Text", params={"text": "I  I", "font_size": 96})))
    assert hits_at(project, (0.0, 0.0)) == ["t"]  # the gap between the letters
    assert hits_at(project, (3.0, 0.0)) == []


def test_rotated_image_hits_its_rectangle(tmp_path) -> None:
    from PIL import Image

    path = tmp_path / "wide.png"
    Image.new("RGBA", (400, 100), (255, 0, 0, 255)).save(path)
    layer = Layer(
        id="img",
        spec=Spec(type="ImageMobject", params={"path": str(path)}),
        base=Transform2D(rotation=90),
    )
    project = scene(layer)
    mob = Evaluator(project).frame_layers(0)[0][1]
    height = np.ptp(mob.points[:, 1])
    assert hits_at(project, (0.0, height / 2 - 0.05)) == ["img"]  # along the rotated long side
    assert hits_at(project, (height / 2 - 0.05, 0.0)) == []  # where it was before rotating


def test_front_most_first_and_all_hits_listed() -> None:
    back = Layer(id="back", spec=Spec(type="Square", params={"side_length": 4}, style=FILLED))
    front = Layer(id="front", spec=Spec(type="Circle", params={"radius": 1}, style=FILLED))
    assert hits_at(scene(back, front), (0.0, 0.0)) == ["front", "back"]
    assert hits_at(scene(back, front), (1.5, 1.5)) == ["back"]


def test_objects_invisible_because_of_a_clip_are_not_hit() -> None:
    """B23: at the first frame of a FadeIn the geometry exists but nothing is drawn."""
    layer = Layer(
        id="f",
        spec=Spec(type="Square", params={"side_length": 2}, style=FILLED),
        clips=[Clip(id="c", kind="FadeIn", start=0.5, duration=1.0)],
    )
    project = scene(layer)
    assert hits_at(project, (0.0, 0.0), t=0.5) == []
    assert hits_at(project, (0.0, 0.0), t=1.0) == ["f"]
    assert hits_at(project, (0.0, 0.0), t=0.2) == []  # before its lifetime: not in the frame


@pytest.mark.parametrize(("opacity", "hit"), [(VISIBLE_ALPHA / 2, False), (VISIBLE_ALPHA * 3, True)])
def test_faint_fill_threshold(opacity: float, hit: bool) -> None:
    spec = Spec(type="Square", params={"side_length": 2}, style={"fill": "#ffffff", "fill_opacity": opacity})
    assert (hits_at(scene(Layer(id="s", spec=spec)), (0.0, 0.0)) == ["s"]) is hit


def test_layer_opacity_zero_is_not_hit() -> None:
    layer = Layer(id="s", spec=Spec(type="Square", style=FILLED), base=Transform2D(opacity=0.0))
    assert hits_at(scene(layer), (0.0, 0.0)) == []


def test_moved_layers_hit_where_they_are_drawn() -> None:
    layer = Layer(id="s", spec=Spec(type="Square", style=FILLED), base=Transform2D(position=(3.0, 1.0)))
    assert hits_at(scene(layer), (3.0, 1.0)) == ["s"]
    assert hits_at(scene(layer), (0.0, 0.0)) == []
