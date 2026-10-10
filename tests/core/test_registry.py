"""The object registry behind the library and the properties panel (S2.3).

Every type in the library must build with its defaults, and every exposed
param must build with a non-default value and actually change the object —
a param that Manim silently ignores would be a lying control in the UI.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from manim_studio.core import adapter
from manim_studio.core.adapter import LIBRARY, MOBJECT_PARAMS, MOBJECT_TYPES, Param
from manim_studio.core.schema import CODE_TYPES, TEXT_TYPES, Spec

LATEX_TYPES = {"MathTex", "Tex"}


def _marks(type_name: str):
    return [pytest.mark.latex] if type_name in LATEX_TYPES else []


BUILT = sorted(set(MOBJECT_PARAMS) - CODE_TYPES)  # code layers are rendered, not built (ADR 0019)
ALL_TYPES = [pytest.param(t, marks=_marks(t)) for t in BUILT]
ALL_PARAMS = [
    pytest.param(t, p, marks=_marks(t), id=f"{t}.{p.name}") for t in BUILT for p in MOBJECT_PARAMS[t]
]


@pytest.fixture
def image(tmp_path: Path):
    def make(name: str, color: tuple[int, int, int]) -> str:
        path = tmp_path / name
        Image.new("RGBA", (40, 20), (*color, 255)).save(path)
        return str(path)

    return make


def test_registry_and_library_cover_every_type_once() -> None:
    assert set(MOBJECT_PARAMS) == set(MOBJECT_TYPES) | CODE_TYPES
    listed = [t for _, types in LIBRARY for t in types]
    assert sorted(listed) == sorted(set(MOBJECT_TYPES) | CODE_TYPES)


def test_defaults_are_within_bounds_and_choices() -> None:
    for params in MOBJECT_PARAMS.values():
        for p in params:
            if p.minimum is not None:
                assert p.minimum <= p.default <= p.maximum, p
            if p.kind == "choice":
                assert p.default in p.choices, p


def test_default_spec_writes_only_what_manim_needs() -> None:
    assert adapter.default_spec("Circle") == Spec(type="Circle")
    assert adapter.default_spec("MathTex").params == {"text": r"e^{i\pi} + 1 = 0"}
    assert adapter.default_spec("Text", text="Hi").params == {"text": "Hi"}
    with pytest.raises(ValueError, match="unsupported"):
        adapter.default_spec("Teapot")


def test_param_value_falls_back_to_the_default() -> None:
    radius = MOBJECT_PARAMS["Circle"][0]
    assert adapter.param_value(Spec(type="Circle"), radius) == 1.0
    assert adapter.param_value(Spec(type="Circle", params={"radius": 2}), radius) == 2
    start = MOBJECT_PARAMS["Line"][0]
    assert adapter.param_value(Spec(type="Line", params={"start": [0, 1]}), start) == (0, 1)


@pytest.mark.parametrize("type_name", ALL_TYPES)
def test_every_library_object_builds(type_name: str, image) -> None:
    extra = {"path": image("a.png", (255, 0, 0))} if type_name == "ImageMobject" else {}
    mob = adapter.build_mobject(adapter.default_spec(type_name, **extra))
    assert abs(mob.get_center()).max() < 1e-6


def _other(param: Param, image) -> object:
    """A valid non-default value for ``param``."""
    if param.kind == "float":
        value = param.default * 1.5 if param.default else 0.5
        return min(value, param.maximum) if param.maximum is not None else value
    if param.kind == "int":
        return param.default + 1
    if param.kind == "choice":
        return next(c for c in param.choices if c != param.default)
    if param.kind == "point":
        return (param.default[0] - 0.5, param.default[1] + 0.7)
    if param.kind == "path":
        return image("b.png", (0, 0, 255))
    return "Arial" if param.name == "font" else "Other 42"


def _signature(mob) -> np.ndarray:
    if hasattr(mob, "pixel_array"):
        return np.asarray(mob.pixel_array, dtype=float).ravel()[:400]
    points = [sub.points for sub in mob.family_members_with_points()]
    return np.concatenate([np.concatenate(points).ravel(), [mob.width, mob.height]])


@pytest.mark.parametrize(("type_name", "param"), ALL_PARAMS)
def test_every_exposed_param_changes_the_object(type_name: str, param: Param, image) -> None:
    base = adapter.default_spec(type_name)
    if type_name == "ImageMobject":
        base = adapter.default_spec(type_name, path=image("a.png", (255, 0, 0)))
    changed = base.model_copy(update={"params": {**base.params, param.name: _other(param, image)}})
    a, b = _signature(adapter.build_mobject(base)), _signature(adapter.build_mobject(changed))
    assert a.shape != b.shape or not np.allclose(a, b), f"{type_name}.{param.name} has no effect"


def test_text_types_are_the_ones_with_a_text_param() -> None:
    with_text = {t for t, params in MOBJECT_PARAMS.items() if any(p.name == "text" for p in params)}
    assert with_text == TEXT_TYPES
