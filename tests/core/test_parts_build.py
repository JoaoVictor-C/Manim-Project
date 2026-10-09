"""Building a root with part markers (P2c.1, B28): exact glyphs, identical pixels."""

from __future__ import annotations

import numpy as np
import pytest

from manim_studio.core import adapter, edits, parts
from manim_studio.core.schema import Canvas, Layer, Project, Spec
from manim_studio.render.cairo_export import make_camera, render_frame

pytestmark = pytest.mark.latex

TEXT = r"\int_0^1 x^2\,dx = \frac{1}{3}"


def render(mob) -> np.ndarray:
    camera = make_camera(Canvas(width_px=320, height_px=180))
    return render_frame(camera, [mob])[..., :3].astype(int)


def with_parts(*keys: tuple[str, int], parent: str = "eq") -> Project:
    project = Project(layers=[Layer(id="eq", spec=Spec(type="MathTex", params={"text": TEXT}))])
    for tex, occurrence in keys:
        project = edits.add_part(project, parent, tex, occurrence).project
    return project


def regions_by_part(project: Project) -> dict[str, tuple[int, ...]]:
    resolution = parts.resolve(project, "eq")
    spec = parts.build_spec(project, "eq", resolution)
    return dict(zip(resolution.order, adapter.part_regions(spec), strict=True))


def test_each_part_holds_exactly_its_glyphs_and_the_render_is_unchanged() -> None:
    project = with_parts((r"\frac{1}{3}", 0), ("x^2", 0))
    project = edits.add_part(project, "part-2", "x").project  # nested inside x^2
    regions = regions_by_part(project)
    assert regions == {"part-2": (3, 4), "part-3": (3,), "part-1": (8, 9, 10)}
    plain = adapter.build_mobject(Spec(type="MathTex", params={"text": TEXT}))
    marked = adapter.build_mobject(parts.build_spec(project, "eq"))
    assert len(marked.family_members_with_points()) == len(plain.family_members_with_points()) == 11
    assert np.abs(render(plain) - render(marked)).max() == 0


def test_a_one_token_script_is_braced_and_marks_only_the_chosen_occurrence() -> None:
    project = with_parts(("1", 0))  # the "1" in the integral's upper limit: right after ^
    assert parts.resolve(project, "eq").spans["part-1"].braced
    assert regions_by_part(project) == {"part-1": (1,)}
    plain = adapter.build_mobject(Spec(type="MathTex", params={"text": TEXT}))
    assert np.abs(render(plain) - render(adapter.build_mobject(parts.build_spec(project, "eq")))).max() == 0
    second = with_parts(("1", 1))  # the numerator of \frac{1}{3}
    assert regions_by_part(second) == {"part-1": (8,)}
