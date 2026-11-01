"""examples/camera.json (ADR 0083): the camera tour is what its builder writes, and the camera moves."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

from manim_studio.core.engine.evaluator import Evaluator
from manim_studio.core.model.schema import Project

EXAMPLES = Path(__file__).resolve().parents[3] / "examples"


def builder():
    spec = importlib.util.spec_from_file_location("build_camera", EXAMPLES / "build_camera.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_committed_file_is_what_the_builder_writes() -> None:
    path = EXAMPLES / "camera.json"
    if not path.exists():
        pytest.skip("camera.json is not in this checkout")
    built = json.loads(builder().build().model_dump_json(by_alias=True))
    assert json.loads(path.read_text(encoding="utf-8")) == built


def test_the_camera_pans_zooms_and_rolls_through_the_tour() -> None:
    project = Project.model_validate_json((EXAMPLES / "camera.json").read_text(encoding="utf-8"))
    evaluator = Evaluator(project)
    assert [layer.is_camera for layer in project.layers].count(True) == 1
    assert project.view_background == "#101a3a"
    at_rest = evaluator.camera_affine(0.0)
    assert at_rest is None or np.allclose(at_rest[0], np.eye(2))
    assert evaluator.camera_affine(4.0) is None  # looking at station two, Size 4: the plain frame
    zoomed = evaluator.camera_affine(5.5)  # in on the dot: Size 1.4 -> scale 4 / 1.4
    assert zoomed[0][0][0] == pytest.approx(4.0 / 1.4, rel=1e-6)
    rolled = evaluator.camera_affine(7.5)
    assert abs(rolled[0][0][1]) > 0.05  # rolled by a few degrees
    assert evaluator.camera_moved(3.0)
