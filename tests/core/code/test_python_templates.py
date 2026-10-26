"""The Python object templates (P10): ready-made code for the Code page's "New Python object" menu."""

from __future__ import annotations

import manim as m
import numpy as np
import pytest

from manim_studio.core.code import python_object, python_templates
from manim_studio.core.code.python_object import read_params
from manim_studio.core.engine import adapter
from manim_studio.core.engine.evaluator import Evaluator
from manim_studio.core.model.schema import Canvas, Clip, Layer, Project, Spec

MATRIX = python_templates.MATRIX


@pytest.fixture(autouse=True)
def _fresh(monkeypatch, tmp_path):
    monkeypatch.setenv("MANIM_STUDIO_TRUST_FILE", str(tmp_path / "trusted.json"))
    monkeypatch.setattr(python_object, "_trust_everything", True)
    adapter.forget_python_builds()
    yield
    adapter.forget_python_builds()


def build(values: dict | None = None) -> m.Mobject:
    params = {"code": MATRIX} if values is None else {"code": MATRIX, "values": values}
    return adapter.build_mobject(Spec(type="Python", params=params))


def tex(mob: m.Mobject) -> str:
    return mob.tex_string


def test_every_template_is_listed_and_reads_its_params() -> None:
    assert set(python_templates.TEMPLATES) == {"Right triangle", "Matrix"}
    for name, code in python_templates.TEMPLATES.items():
        assert read_params(code), name  # PARAMS read without running anything


def test_the_matrix_params() -> None:
    params = {p.name: p for p in read_params(MATRIX)}
    assert (params["rows"].default, params["rows"].minimum, params["rows"].maximum) == (3, 1, 8)
    assert (params["columns"].default, params["columns"].minimum, params["columns"].maximum) == (3, 1, 8)
    assert params["values"].kind == "text" and params["color"].kind == "colour"


def test_the_default_is_the_three_by_three() -> None:
    assert tex(build()) == r"\begin{bmatrix}1 & 2 & 3 \\ 4 & 5 & 6 \\ 7 & 8 & 9\end{bmatrix}"


def test_rows_columns_and_values_pick_the_shape_and_the_entries() -> None:
    matrix = build({"rows": 2, "columns": 3, "values": "a,b,c;d,e,f"})
    assert tex(matrix) == r"\begin{bmatrix}a & b & c \\ d & e & f\end{bmatrix}"


def test_missing_values_are_zeros_and_extra_ones_are_ignored() -> None:
    assert (
        tex(build({"rows": 2, "columns": 2, "values": "1,2;3"}))
        == r"\begin{bmatrix}1 & 2 \\ 3 & 0\end{bmatrix}"
    )
    assert (
        tex(build({"rows": 1, "columns": 2, "values": "1,2,3,4;5,6"})) == r"\begin{bmatrix}1 & 2\end{bmatrix}"
    )


def test_the_size_is_limited_to_eight() -> None:
    entries = tex(build({"rows": 99, "columns": 99, "values": "1"}))
    assert entries.count(r"\\") == 7 and entries.split(r"\\")[0].count("&") == 7


def test_the_colour_applies() -> None:
    matrix = build({"color": "#ff0000"})
    assert all(sub.get_color().to_hex().lower() == "#ff0000" for sub in matrix.family_members_with_points())


def test_it_is_an_object_that_draws_and_animates() -> None:
    project = Project(
        canvas=Canvas(width_px=160, height_px=90, fps=10, duration=2.0),
        layers=[
            Layer(
                id="mx",
                spec=Spec(
                    type="Python",
                    params={"code": MATRIX, "values": {"rows": 2, "columns": 2, "values": "1,0;0,1"}},
                ),
                clips=[Clip(id="c", kind="Write", start=0.0, duration=1.0)],
            )
        ],
    )
    evaluator = Evaluator(project)
    assert evaluator.build_errors() == {}
    drawn = dict(evaluator.frame_layers(0.5))["mx"]
    assert len(np.concatenate([s.points for s in drawn.family_members_with_points()])) > 0
