"""A computer without LaTeX (the user's other PC): MathTex can't be built, and that must show a
placeholder with the reason, not break drawing, idle work and selection."""

from __future__ import annotations

import shutil
import uuid

import pytest

from manim_studio.core.engine.evaluator import Evaluator
from manim_studio.core.model.schema import Canvas, Clip, Layer, PartKey, Project, Spec


@pytest.fixture
def no_latex(monkeypatch, tmp_path):
    """``latex`` is not on PATH, as on a computer without MiKTeX or TeX Live."""
    monkeypatch.setenv("PATH", str(tmp_path))
    assert shutil.which("latex") is None


def unseen(text: str) -> str:
    """A formula no cache has seen, so LaTeX would really run."""
    return rf"{text} + \text{{{uuid.uuid4().hex[:8]}}}"


def project(*extra: Layer, text: str) -> Project:
    eq = Layer(
        id="eq",
        spec=Spec(type="MathTex", params={"text": text}),
        clips=[Clip(id="w", kind="Write", start=0.0, duration=1.0)],
    )
    circle = Layer(id="c", spec=Spec(type="Circle"))
    return Project(
        canvas=Canvas(width_px=160, height_px=90, fps=10, duration=3.0), layers=[eq, circle, *extra]
    )


def test_without_latex_a_formula_is_a_placeholder_and_says_why(no_latex) -> None:
    evaluator = Evaluator(project(text=unseen("x^2")))
    for t in (0.0, 0.5, 2.0):
        drawn = dict(evaluator.frame_layers(t))
        assert drawn["c"].family_members_with_points()  # the rest is drawn
        assert drawn["eq"].family_members_with_points()  # the dashed placeholder
    assert "LaTeX is not installed (latex was not found)" in evaluator.build_errors()["eq"]
    for layer, index in evaluator.missing_checkpoints():  # the idle pass of the window
        evaluator.compute_checkpoint(layer, index)


def test_without_latex_a_formula_with_parts_is_a_placeholder(no_latex) -> None:
    text = unseen("a + b")
    part = Layer(id="p", parent_id="eq", part=PartKey(tex="a"))
    evaluator = Evaluator(project(part, text=text))
    evaluator.frame(0.5)
    evaluator.frame(2.0)
    assert "LaTeX is not installed" in evaluator.build_errors()["eq"]
