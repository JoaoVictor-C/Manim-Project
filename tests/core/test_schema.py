"""Project document validation (ADR 0004 lanes, ADR 0005 morph hand-off)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from manim_studio.core.evaluator import Evaluator
from manim_studio.core.schema import SCHEMA_VERSION, Canvas, Clip, Keyframe, Layer, Project, Spec

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
SQUARE = Spec(type="Square")


def test_overlapping_clips_are_rejected() -> None:
    with pytest.raises(ValidationError, match="overlap"):
        Layer(
            id="a",
            spec=SQUARE,
            clips=[
                Clip(id="1", kind="Create", start=0.0, duration=1.0),
                Clip(id="2", kind="Indicate", start=0.9, duration=1.0),
            ],
        )


def test_touching_clips_are_allowed() -> None:
    layer = Layer(
        id="a",
        spec=SQUARE,
        clips=[
            Clip(id="2", kind="Indicate", start=1.0, duration=1.0),
            Clip(id="1", kind="Create", start=0.0, duration=1.0),
        ],
    )
    assert [c.id for c in layer.clips] == ["1", "2"]  # sorted by start


def test_keyframes_are_sorted() -> None:
    layer = Layer(id="a", spec=SQUARE, tracks={"scale": [Keyframe(t=2, value=2.0), Keyframe(t=0, value=1.0)]})
    assert [k.t for k in layer.tracks["scale"]] == [0, 2]


def test_clips_after_a_morph_are_rejected() -> None:
    """A morph ends the layer (ADR 0005); a later clip would have nothing to animate."""
    with pytest.raises(ValidationError, match="after morph"):
        Layer(
            id="a",
            spec=SQUARE,
            clips=[
                Clip(id="m", kind="Transform", start=1.0, duration=1.0, to_layer="b"),
                Clip(id="f", kind="FadeOut", start=2.5, duration=0.5),
            ],
        )


def test_morph_needs_a_target() -> None:
    with pytest.raises(ValidationError, match="to_layer"):
        Clip(id="m", kind="Transform", start=0, duration=1)


def test_morph_target_must_exist() -> None:
    clip = Clip(id="m", kind="Transform", start=0, duration=1, to_layer="missing")
    with pytest.raises(ValidationError, match="missing"):
        Project(layers=[Layer(id="a", spec=SQUARE, clips=[clip])])


def test_unknown_clip_kind_is_rejected() -> None:
    with pytest.raises(ValidationError, match="Explode"):
        Clip(id="x", kind="Explode", start=0, duration=1)


def test_non_positive_duration_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Clip(id="x", kind="Create", start=0, duration=0)


def test_json_round_trip_keeps_lifetime_alias() -> None:
    layer = Layer.model_validate({"id": "a", "spec": {"type": "Square"}, "lifetime": {"in": 1.0, "out": 2.0}})
    project = Project(layers=[layer])
    data = json.loads(project.model_dump_json(by_alias=True))
    assert data["layers"][0]["lifetime"] == {"in": 1.0, "out": 2.0}
    assert Project.model_validate(data) == project


def test_frame_width_follows_aspect_ratio() -> None:
    assert Canvas(width_px=1920, height_px=1080, frame_height=8).frame_width == pytest.approx(8 * 16 / 9)


@pytest.mark.parametrize("path", sorted(EXAMPLES.glob("*.json")), ids=lambda p: p.name)
def test_examples_validate_and_evaluate(path: Path) -> None:
    project = Project.model_validate_json(path.read_text(encoding="utf-8"))
    assert project.schema_version == SCHEMA_VERSION
    evaluator = Evaluator(project)
    for t in (0.0, project.canvas.duration / 2, project.canvas.duration - 0.01):
        evaluator.frame(t)


def test_negative_start_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Clip(id="x", kind="Create", start=-0.5, duration=1)


def test_non_morph_clip_cannot_have_a_target() -> None:
    with pytest.raises(ValidationError, match="only valid on morph"):
        Clip(id="x", kind="FadeIn", start=0, duration=1, to_layer="b")


def test_layer_cannot_morph_into_itself() -> None:
    clip = Clip(id="m", kind="Transform", start=0, duration=1, to_layer="a")
    with pytest.raises(ValidationError, match="itself"):
        Project(layers=[Layer(id="a", spec=SQUARE, clips=[clip])])


def test_two_morphs_cannot_target_one_layer() -> None:
    def morph(layer_id: str) -> Layer:
        clip = Clip(id="m", kind="Transform", start=0, duration=1, to_layer="c")
        return Layer(id=layer_id, spec=SQUARE, clips=[clip])

    with pytest.raises(ValidationError, match="two morphs"):
        Project(layers=[morph("a"), morph("b"), Layer(id="c", spec=SQUARE)])


def test_duplicate_layer_ids_are_rejected() -> None:
    with pytest.raises(ValidationError, match="duplicate"):
        Project(layers=[Layer(id="a", spec=SQUARE), Layer(id="a", spec=SQUARE)])


def test_unsupported_schema_version_is_rejected() -> None:
    with pytest.raises(ValidationError, match="schema_version"):
        Project(schema_version=SCHEMA_VERSION + 1)


def test_bezier_x_outside_unit_interval_is_rejected() -> None:
    with pytest.raises(ValidationError, match="x1 and x2"):
        Keyframe(t=0, value=1.0, ease={"bezier": [1.2, 0, 0.5, 1]})


def test_schema_does_not_import_manim() -> None:
    """ADR 0003: documents validate without loading Manim (no circular import either)."""
    import subprocess
    import sys

    code = "import sys, manim_studio.core.schema; print('manim' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"
