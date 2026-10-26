"""Code layers in the evaluator and renderer (P2d.1, ADR 0019).

A cache is built by hand from frames Manim renders with a transparent camera —
exactly what the runner will store — so compositing can be checked against
the same mobjects drawn directly.
"""

from __future__ import annotations

import manim as m
import numpy as np
import pytest

from manim_studio.core.code.code_cache import CodeCache
from manim_studio.core.code.code_frame import CodeFrame
from manim_studio.core.engine import adapter
from manim_studio.core.engine.evaluator import Evaluator
from manim_studio.core.model.schema import Canvas, Layer, Lifetime, Project, Spec, Transform2D
from manim_studio.render.cairo_export import make_camera, render_frame
from manim_studio.render.hit_test import hit_layers

CANVAS = Canvas(width_px=320, height_px=180, fps=10, duration=2.0)
UNIT_PX = CANVAS.height_px / CANVAS.frame_height  # 22.5 px per unit: shifts of 2 units are whole pixels
CODE = Spec(type="Code", params={"code": "class Dots(Scene): ..."})  # never run: the cache is built by hand


def ball(x: float = 0.0) -> m.Mobject:
    return m.Circle(radius=1.0).set_fill(m.ManimColor("#facc15"), 0.8).set_stroke(width=0).shift((x, 0, 0))


def square() -> m.Mobject:
    return m.Square(side_length=3.0).set_fill(m.ManimColor("#3b82f6"), 1.0).set_stroke(width=0)


def transparent_frame(mobs) -> np.ndarray:
    camera = m.Camera(
        pixel_width=CANVAS.width_px,
        pixel_height=CANVAS.height_px,
        frame_width=CANVAS.frame_width,
        frame_height=CANVAS.frame_height,
        background_opacity=0.0,
    )
    camera.capture_mobjects(mobs)
    return np.array(camera.pixel_array, copy=True)


def with_cache(tmp_path, project: Project, frames: list[np.ndarray], layer_id: str = "code") -> Evaluator:
    evaluator = Evaluator(project, CodeCache(tmp_path))
    writer = evaluator.code_cache.writer(
        evaluator.code_key(project.layer(layer_id)), CANVAS.width_px, CANVAS.height_px, CANVAS.fps
    )
    for f in frames:
        writer.add(f)
    writer.finish()
    return evaluator


def rendered(evaluator: Evaluator, t: float) -> np.ndarray:
    return render_frame(make_camera(CANVAS), evaluator.frame(t)).astype(int)


def reference(mobs) -> np.ndarray:
    return render_frame(make_camera(CANVAS), mobs).astype(int)


def test_a_code_frame_composites_like_the_mobjects_it_was_rendered_from(tmp_path) -> None:
    under = Layer(
        id="sq",
        spec=Spec(
            type="Square",
            params={"side_length": 3.0},
            style={"fill": "#3b82f6", "fill_opacity": 1.0, "stroke_width": 0},
        ),
    )
    code = Layer(id="code", spec=CODE)
    evaluator = with_cache(
        tmp_path, Project(canvas=CANVAS, layers=[under, code]), [transparent_frame([ball()])]
    )
    assert isinstance(evaluator.frame(0.0)[1], CodeFrame)
    diff = np.abs(rendered(evaluator, 0.0) - reference([square(), ball()]))
    assert diff.max() <= 3  # premultiplied rounding only
    # And under another object: the stacking order is kept.
    over = Project(canvas=CANVAS, layers=[code, under])
    diff = np.abs(rendered(Evaluator(over, evaluator.code_cache), 0.0) - reference([ball(), square()]))
    assert diff.max() <= 3


def test_frames_follow_time_from_the_lifetime_start_and_the_last_is_held(tmp_path) -> None:
    code = Layer(id="code", spec=CODE, lifetime=Lifetime(in_=0.5))
    frames = [transparent_frame([ball(x)]) for x in (-2.0, 0.0, 2.0)]
    evaluator = with_cache(tmp_path, Project(canvas=CANVAS, layers=[code]), frames)
    assert evaluator.frame(0.4) == []  # before its lifetime
    for t, x in ((0.5, -2.0), (0.6, 0.0), (0.65, 0.0), (0.7, 2.0), (1.9, 2.0)):
        assert np.abs(rendered(evaluator, t) - reference([ball(x)])).max() <= 3, t


def test_the_layer_transform_and_opacity_apply(tmp_path) -> None:
    code = Layer(id="code", spec=CODE, base=Transform2D(position=(2.0, 0.0)))
    evaluator = with_cache(tmp_path, Project(canvas=CANVAS, layers=[code]), [transparent_frame([ball()])])
    assert np.abs(rendered(evaluator, 0.0) - reference([ball(2.0)])).max() <= 3
    turned = Project(
        canvas=CANVAS, layers=[Layer(id="code", spec=CODE, base=Transform2D(rotation=90.0, scale=0.5))]
    )
    off_centre = [transparent_frame([ball(2.0)])]
    evaluator = with_cache(tmp_path / "turned", turned, off_centre)
    expected = reference([ball(2.0).scale(0.5, about_point=m.ORIGIN).rotate(m.PI / 2, about_point=m.ORIGIN)])
    assert np.abs(rendered(evaluator, 0.0) - expected).mean() < 1.0  # resampled: compare on average
    faded = Project(canvas=CANVAS, layers=[Layer(id="code", spec=CODE, base=Transform2D(opacity=0.5))])
    evaluator = with_cache(tmp_path / "faded", faded, [transparent_frame([ball()])])
    half = ball().set_fill(opacity=0.4)
    assert np.abs(rendered(evaluator, 0.0) - reference([half])).max() <= 3


def test_a_code_layer_without_frames_shows_a_placeholder(tmp_path) -> None:
    evaluator = Evaluator(Project(canvas=CANVAS, layers=[Layer(id="code", spec=CODE)]), CodeCache(tmp_path))
    [(layer_id, mob)] = evaluator.frame_layers(0.0)
    assert layer_id == "code" and isinstance(mob, m.VMobject) and not isinstance(mob, CodeFrame)


def test_a_code_frame_is_hit_on_its_visible_pixels_only(tmp_path) -> None:
    code = Layer(id="code", spec=CODE, base=Transform2D(position=(2.0, 0.0)))
    evaluator = with_cache(tmp_path, Project(canvas=CANVAS, layers=[code]), [transparent_frame([ball()])])
    layers = evaluator.frame_layers(0.0)
    assert hit_layers(layers, (2.0, 0.0), UNIT_PX) == ["code"]
    assert hit_layers(layers, (2.0, 1.5), UNIT_PX) == []  # inside the frame, but transparent
    assert hit_layers(layers, (0.0, 0.0), UNIT_PX) == []
    corners = layers[0][1].points[:, :2]
    assert corners.min(axis=0)[0] == pytest.approx(1.0, abs=0.1) and corners.max(axis=0)[0] == pytest.approx(
        3.0, abs=0.1
    )


def test_every_library_type_builds_through_the_evaluator(tmp_path) -> None:
    """A code layer must never reach build_mobject; every other type must build."""
    from PIL import Image

    image = tmp_path / "pixel.png"
    Image.new("RGBA", (4, 4), (255, 0, 0, 255)).save(image)
    layers = []
    for _section, types in adapter.LIBRARY:
        for type_name in types:
            if type_name in {"Text", "MathTex", "Tex", "DecimalNumber"}:
                continue  # need LaTeX/Pango; covered by their own tests
            extra = {"path": str(image)} if type_name == "ImageMobject" else {}
            if type_name == "TracedPath":  # traces the first object (ADR 0033)
                extra = {"target": layers[0].id}
            if type_name == "Connector":  # joins the first two objects (ADR 0036)
                extra = {"source": layers[0].id, "target": layers[1].id}
            layers.append(Layer(id=type_name.lower(), spec=adapter.default_spec(type_name, **extra)))
    evaluator = Evaluator(Project(canvas=CANVAS, layers=layers), CodeCache(tmp_path / "code"))
    drawn = [layer_id for layer_id, _ in evaluator.frame_layers(0.0)]
    assert drawn == [layer.id for layer in layers]
    with pytest.raises(ValueError, match="rendered by the code runner"):
        adapter.build_mobject(CODE)
