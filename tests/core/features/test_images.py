"""ImageMobject layers (ADR 0002 purity, 0004 opacity multiplies, 0008 invalidation).

Images differ from vector objects: their opacity lives in ``pixel_array``'s alpha
channel, and Manim's ``ImageMobject.set_opacity`` writes it in place relative to
the *original* alpha. The evaluator must neither share nor overwrite those arrays.
"""

from __future__ import annotations

import random

import manim as m
import numpy as np
import pytest
from PIL import Image

from manim_studio.core.engine import adapter
from manim_studio.core.engine.evaluator import Evaluator
from manim_studio.core.model.schema import Clip, Keyframe, Layer, Project, Spec
from manim_studio.render.cairo_export import make_camera, render_frame
from support import CANVAS, FRAMES, assert_evaluators_agree, max_diff


@pytest.fixture(scope="module")
def image_spec(tmp_path_factory) -> Spec:
    """A 64x64 RGBA gradient with a semi-transparent half."""
    size = 64
    pixels = np.zeros((size, size, 4), dtype=np.uint8)
    pixels[..., 0] = np.linspace(0, 255, size, dtype=np.uint8)[None, :]
    pixels[..., 1] = np.linspace(255, 0, size, dtype=np.uint8)[:, None]
    pixels[..., 2] = 128
    pixels[..., 3] = 255
    pixels[size // 2 :, :, 3] = 128
    path = tmp_path_factory.mktemp("img") / "gradient.png"
    Image.fromarray(pixels, "RGBA").save(path)
    return Spec(type="ImageMobject", params={"path": str(path), "scale_to_resolution": 180})


def _layer(image_spec: Spec, opacity_keys: bool, position_keys: bool) -> Layer:
    tracks = {}
    if opacity_keys:
        tracks["opacity"] = [Keyframe(t=0, value=1.0), Keyframe(t=1, value=0.4, ease={"name": "linear"})]
    if position_keys:
        tracks["position"] = [Keyframe(t=0, value=(-2.0, 0.0)), Keyframe(t=1, value=(2.0, 1.0))]
    return Layer(
        id="img", spec=image_spec, tracks=tracks, clips=[Clip(id="f", kind="FadeIn", start=0, duration=1)]
    )


def _reference_frame(image_spec: Spec, layer: Layer, evaluator: Evaluator, t: float, camera) -> np.ndarray:
    """Independent of the evaluator's image paths: Manim calls + explicit alpha multiply."""
    anim = m.FadeIn(adapter.build_mobject(image_spec))
    anim.begin()
    anim.interpolate(t)
    mob = anim.mobject.copy()
    tr = evaluator.transform_at(layer, t)
    mob.shift([tr.position[0], tr.position[1], 0])
    mob.pixel_array = mob.pixel_array.copy()
    mob.pixel_array[:, :, 3] = (mob.pixel_array[:, :, 3] * tr.opacity).astype(np.uint8)
    return render_frame(camera, [mob])


@pytest.mark.parametrize(
    ("opacity_keys", "position_keys"),
    [(False, False), (False, True), (True, False), (True, True)],
    ids=["plain", "moving", "fading", "moving+fading"],
)
def test_image_frames_match_reference(image_spec: Spec, opacity_keys: bool, position_keys: bool) -> None:
    layer = _layer(image_spec, opacity_keys, position_keys)
    project = Project(canvas=CANVAS, layers=[layer])
    camera = make_camera(CANVAS)
    evaluator = Evaluator(project)
    for t in random.Random(3).sample(FRAMES, len(FRAMES)):
        expected = _reference_frame(image_spec, layer, evaluator, t, camera)
        diff = max_diff(render_frame(camera, evaluator.frame(t)), expected)
        assert diff <= 2, f"t={t}: differs by {diff}"  # alpha rounding on uint8


def test_image_evaluation_is_pure(image_spec: Spec) -> None:
    """Re-rendering a frame after others must give the same pixels (no shared pixel arrays).

    The sequence matters: a mid-FadeIn frame, then frames that run the transform
    path on the same working mobject, then the mid-FadeIn frame again. Compared
    against the independent reference, not a fresh evaluator, which would share
    any defect in the evaluator's image path.
    """
    layer = _layer(image_spec, opacity_keys=True, position_keys=True)
    project = Project(canvas=CANVAS, layers=[layer])
    camera = make_camera(CANVAS)
    evaluator = Evaluator(project)
    mid = FRAMES[4]
    sequence = [mid, FRAMES[9], FRAMES[2], mid, *random.Random(4).sample(FRAMES, len(FRAMES)), mid]
    for t in sequence:
        expected = _reference_frame(image_spec, layer, evaluator, t, camera)
        diff = max_diff(render_frame(camera, evaluator.frame(t)), expected)
        assert diff <= 2, f"t={t}: differs by {diff}"


def test_image_base_pixels_untouched(image_spec: Spec) -> None:
    original = adapter.build_mobject(image_spec).pixel_array.copy()
    evaluator = Evaluator(Project(canvas=CANVAS, layers=[_layer(image_spec, True, True)]))
    for t in FRAMES:
        evaluator.frame(t)
    assert np.array_equal(adapter.build_mobject(image_spec).pixel_array, original)


def test_image_transform_only_invalidation(image_spec: Spec) -> None:
    project = Project(canvas=CANVAS, layers=[_layer(image_spec, True, False)])
    evaluator = Evaluator(project)
    for t in FRAMES:
        evaluator.frame(t)
    edited = project.model_copy(deep=True)
    edited.layers[0].tracks["position"] = [Keyframe(t=0, value=(1.0, -1.0))]
    evaluator.invalidate(edited, {"img"}, kind="transform")
    assert_evaluators_agree(evaluator, Evaluator(edited))


def test_image_allowed_clip_kinds() -> None:
    kinds = adapter.allowed_clip_kinds("ImageMobject")
    assert "FadeIn" in kinds and "Indicate" in kinds
    assert not {"Create", "Write", "Uncreate", "DrawBorderThenFill", "Wiggle"} & set(kinds)
