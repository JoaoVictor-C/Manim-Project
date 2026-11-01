"""The camera as a 2D orthographic camera (ADR 0083): size, background, follow, Scene view drawing."""

from __future__ import annotations

import numpy as np
import pytest

from manim_studio.core.editing import edits
from manim_studio.core.engine import frame_cache
from manim_studio.core.engine.evaluator import (
    Evaluator,
    camera_scale,
    camera_size,
    camera_transform,
    layer_transform,
)
from manim_studio.core.engine.python_export import readable_problems
from manim_studio.core.model.schema import Canvas, Easing, Keyframe, Layer, Project, Spec, Transform2D
from manim_studio.render.cairo_export import make_camera, render_frame

CANVAS = Canvas(width_px=320, height_px=180, fps=10, duration=4.0, background="#000000")
LINEAR = Easing(name="linear")


def square(layer_id: str = "sq", **base) -> Layer:
    return Layer(
        id=layer_id,
        spec=Spec(type="Square", params={"side_length": 1}, style={"fill": "#3b82f6", "fill_opacity": 1}),
        base=Transform2D(**base),
    )


def camera(params: dict | None = None, tracks: dict | None = None, **base) -> Layer:
    return Layer(
        id="camera",
        name="Camera",
        spec=Spec(type="Camera", params=params or {}),
        base=Transform2D(**base),
        tracks=tracks or {},
    )


def project(*layers: Layer) -> Project:
    return Project(canvas=CANVAS, layers=list(layers))


def drawn(scene: Project, t: float = 0.0, through: bool = True) -> np.ndarray:
    evaluator = Evaluator(scene)
    evaluator.set_through_camera(through)
    layers = [mob for _, mob in evaluator.frame_layers(t)]
    camera_ = make_camera(scene.canvas, scene.camera, scene.view_background)
    return render_frame(camera_, layers, evaluator.overlay(t)).astype(int)


# -- size and scale ----------------------------------------------------------------------------


def test_size_is_half_the_visible_height_and_the_inverse_of_the_scale() -> None:
    assert camera_size(1.0, 8.0) == 4.0  # Manim's frame is 8 high: the camera at rest has size 4
    assert camera_size(2.0, 8.0) == 2.0  # zoomed in twice: it sees half as much
    for size in (0.5, 3.0, 4.0, 12.5):
        assert camera_size(camera_scale(size, 8.0), 8.0) == pytest.approx(size)


def test_scale_keys_ease_as_a_size() -> None:
    keys = [Keyframe(t=0.0, value=1.0, ease=LINEAR), Keyframe(t=2.0, value=2.0, ease=LINEAR)]
    layer = camera(tracks={"scale": keys})
    middle = camera_transform(layer, 1.0)
    assert camera_size(middle.scale, 8.0) == pytest.approx(3.0)  # sizes 4 -> 2: halfway is 3
    assert layer_transform(layer, 1.0).scale == pytest.approx(1.5)  # a plain layer eases the scale
    assert camera_transform(layer, 0.0).scale == 1.0 and camera_transform(layer, 2.0).scale == 2.0
    assert camera_transform(layer, 3.0).scale == 2.0
    evaluator = Evaluator(project(square(), layer))
    a, _b = evaluator.camera_affine(1.0)
    assert np.allclose(a, np.eye(2) * 4.0 / 3.0)


def test_a_camera_scale_must_be_above_zero() -> None:
    with pytest.raises(ValueError, match="above 0"):
        camera(scale=0.0)
    with pytest.raises(ValueError, match="above 0"):
        camera(tracks={"scale": [Keyframe(t=0.0, value=1.0), Keyframe(t=1.0, value=0.0)]})


def test_clearing_scale_keys_keeps_the_eased_size() -> None:
    keys = [Keyframe(t=0.0, value=1.0, ease=LINEAR), Keyframe(t=2.0, value=2.0, ease=LINEAR)]
    scene = project(square(), camera(tracks={"scale": keys}))
    cleared = edits.clear_track(scene, "camera", "scale", 1.0).project
    assert cleared.layer("camera").base.scale == pytest.approx(4.0 / 3.0)


# -- background ----------------------------------------------------------------------------------


def test_the_camera_background_replaces_the_canvas_background() -> None:
    plain = drawn(project(square(position=(3.0, 0.0)), camera()))
    assert tuple(plain[5, 5, :3]) == (0, 0, 0)
    red = project(square(position=(3.0, 0.0)), camera({"background": "#ff0000"}))
    assert red.view_background == "#ff0000"
    pixels = drawn(red)
    assert tuple(pixels[5, 5, :3]) == (255, 0, 0)
    assert np.array_equal(pixels[90, 160 + 60], plain[90, 160 + 60])  # the square is drawn as before
    hidden = red.model_copy(
        update={"layers": [red.layers[0], red.layers[1].model_copy(update={"visible": False})]}
    )
    assert hidden.view_background == "#000000"  # a hidden camera does nothing


def test_camera_settings_are_validated_and_omitted_by_default() -> None:
    with pytest.raises(ValueError, match="colour"):
        camera({"background": "red"})
    with pytest.raises(ValueError, match="unknown camera settings"):
        camera({"zoom": 2})
    with pytest.raises(ValueError, match="two numbers"):
        camera({"follow_offset": [1.0]})
    with pytest.raises(ValueError, match="missing"):
        project(camera({"follow": "nobody"}))
    with pytest.raises(ValueError, match="itself"):
        project(camera({"follow": "camera"}))
    eq = Layer(id="eq", spec=Spec(type="MathTex", params={"text": "a+b"}))
    part = Layer.model_validate({"id": "eq-a", "parent_id": "eq", "part": {"tex": "a"}})
    with pytest.raises(ValueError, match="part"):
        project(eq, part, camera({"follow": "eq-a"}))
    scene = project(square(), camera())
    dumped = scene.model_dump(by_alias=True)
    assert dumped["layers"][1]["spec"]["params"] == {}
    assert Project.model_validate_json(scene.model_dump_json(by_alias=True)) == scene


# -- follow --------------------------------------------------------------------------------------


def moving_square() -> Layer:
    keys = [Keyframe(t=0.0, value=(0.0, 0.0), ease=LINEAR), Keyframe(t=2.0, value=(4.0, 1.0), ease=LINEAR)]
    return square().model_copy(update={"tracks": {"position": keys}})


def test_following_puts_the_target_where_the_camera_looks() -> None:
    scene = project(
        moving_square(), camera({"follow": "sq", "follow_offset": [1.0, 0.0]}, position=(0.0, 0.5))
    )
    evaluator = Evaluator(scene)
    view = evaluator.camera_view(2.0)
    assert view.position == pytest.approx((5.0, 1.5))  # target + offset + its own position
    a, b = evaluator.camera_affine(2.0)
    assert np.allclose(a @ np.array([5.0, 1.5]) + b, 0.0)  # the point it looks at is the frame's middle
    still = drawn(project(square(position=(-1.0, -0.5)), camera()))
    assert np.abs(drawn(scene, 2.0) - still).max() <= 1  # the square stays where the offset puts it
    assert np.abs(drawn(scene, 1.0) - still).max() <= 1


def test_following_a_pinned_label_does_not_go_round() -> None:
    label = Layer(
        id="lbl",
        spec=Spec(type="Text", params={"text": "Hi"}),
        pin={"target": "sq", "anchor": "top"},
    )
    scene = project(moving_square(), label, camera({"follow": "lbl"}))
    evaluator = Evaluator(scene)
    view = evaluator.camera_view(2.0)
    assert view.position[0] == pytest.approx(4.0, abs=0.05)  # above the square, which is at x = 4
    assert view.position[1] > 1.0
    assert evaluator.frame_layers(2.0)  # draws


def test_deleting_the_followed_layer_stops_following() -> None:
    scene = project(moving_square(), camera({"follow": "sq", "follow_offset": [1.0, 0.0]}))
    after = edits.remove_layer(scene, "sq").project
    assert after.layer("camera").spec.params == {}


def test_editing_the_followed_layer_drops_every_frame() -> None:
    scene = project(moving_square(), square("other", position=(2.0, 0.0)), camera({"follow": "sq"}))
    moved = scene.model_copy(
        update={
            "layers": [scene.layers[0].model_copy(update={"base": Transform2D(scale=2.0)}), *scene.layers[1:]]
        }
    )
    assert frame_cache.changed_spans(scene, moved) is None
    background = edits.update_layer(
        scene, "camera", spec=Spec(type="Camera", params={"follow": "sq", "background": "#112233"})
    ).project
    assert frame_cache.changed_spans(scene, background) is None
    other = edits.update_layer(scene, "other", base=Transform2D(position=(1.0, 0.0)).model_dump()).project
    assert frame_cache.changed_spans(scene, other) is not None  # what the camera does not follow: its spans


# -- Scene view ----------------------------------------------------------------------------------


def test_scene_view_draws_the_scene_flat_while_the_camera_moves() -> None:
    scene = project(square(position=(1.0, 0.0)), camera(position=(2.0, 1.0), scale=2.0, rotation=30.0))
    flat = drawn(project(square(position=(1.0, 0.0))))
    assert np.array_equal(drawn(scene, through=False), flat)
    assert not np.array_equal(drawn(scene), flat)
    evaluator = Evaluator(scene)
    evaluator.set_through_camera(False)
    assert not evaluator.camera_moved(0.0) and evaluator.camera_affine(0.0) is None
    assert evaluator.camera_view(0.0).position == (2.0, 1.0)  # the gizmo still knows where it is
    evaluator.set_through_camera(True)
    assert evaluator.camera_moved(0.0)


def test_the_readable_export_still_refuses_a_camera() -> None:
    scene = project(square(), camera({"background": "#ff0000", "follow": "sq"}))
    assert any("camera" in problem for problem in readable_problems(scene))
