"""examples/smart_transform.py: the smart morph as one plain Manim file (scripts/gen_smart_transform.py)."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import manim as m
import numpy as np
import pytest

from manim_studio.core.engine import adapter

ROOT = Path(__file__).resolve().parents[3]
FILE = ROOT / "examples" / "smart_transform.py"


@pytest.fixture(scope="module")
def mono():
    spec = importlib.util.spec_from_file_location("smart_transform_file", FILE)
    module = importlib.util.module_from_spec(spec)
    sys.modules["smart_transform_file"] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop("smart_transform_file", None)


def test_the_file_is_up_to_date_with_the_source() -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import gen_smart_transform
    finally:
        sys.path.pop(0)
    assert FILE.read_text(encoding="utf-8").replace("\r\n", "\n") == gen_smart_transform.render()


def test_the_file_needs_only_manim_and_numpy() -> None:
    text = FILE.read_text(encoding="utf-8")
    assert "manim_studio" not in text.replace("Manim Studio's", "").replace("Manim Studio", "")
    imports = {
        line.split()[1].split(".")[0] for line in text.splitlines() if line.startswith(("import ", "from "))
    }
    assert imports <= {"__future__", "itertools", "dataclasses", "manim", "numpy"}


def pairs():
    return {
        "circle-square": (m.Circle(color=m.BLUE, fill_opacity=0.6), m.Square(color=m.RED, fill_opacity=0.3)),
        "square-turned": (m.Square(side_length=2), m.Square(side_length=2).rotate(m.PI / 2)),
        "cat-elephant": (m.Text("cat").scale(2), m.Text("elephant").scale(1.4)),
    }


@pytest.mark.parametrize("name", ["circle-square", "square-turned", "cat-elephant"])
def test_the_file_morphs_exactly_like_the_editor(mono, name) -> None:
    source, target = pairs()[name]
    animation, start, _end = mono.smart_transform(source.copy(), target.copy(), run_time=1)
    editor_start, editor_end, exact = adapter.smart_pair(source.copy(), target.copy())
    for mine, theirs in zip(
        start.family_members_with_points(), editor_start.family_members_with_points(), strict=True
    ):
        assert np.array_equal(mine.points, theirs.points)
    editor = type("E", (adapter.SmartMorph, m.ReplacementTransform), {})(editor_start, editor_end, run_time=1)
    editor.exact = exact
    for a in (animation, editor):
        a.begin()
    for alpha in (0.0, 0.25, 0.5, 0.8, 1.0):
        animation.interpolate(alpha)
        editor.interpolate(alpha)
        for mine, theirs in zip(
            animation.mobject.family_members_with_points(),
            editor.mobject.family_members_with_points(),
            strict=True,
        ):
            assert np.array_equal(mine.points, theirs.points), alpha
            assert np.array_equal(mine.stroke_rgbas, theirs.stroke_rgbas) and np.array_equal(
                mine.fill_rgbas, theirs.fill_rgbas
            ), alpha


def test_the_ends_are_the_two_shapes_exactly(mono) -> None:
    source, target = pairs()["circle-square"]
    animation, _start, _end = mono.smart_transform(source.copy(), target.copy(), run_time=1)
    animation.begin()
    animation.interpolate(0.0)
    assert np.array_equal(
        np.concatenate([p.points for p in animation.mobject.family_members_with_points()]), source.points
    )
    animation.interpolate(1.0)
    assert np.array_equal(
        np.concatenate([p.points for p in animation.mobject.family_members_with_points()]), target.points
    )


def test_an_image_falls_back_to_manims_own_transform(mono) -> None:
    image = m.ImageMobject(np.zeros((4, 4, 4), dtype=np.uint8))
    animation, start, _end = mono.smart_transform(image, m.Circle())
    assert isinstance(animation, m.ReplacementTransform) and start is image


@pytest.mark.slow
def test_the_demo_scene_renders_with_plain_manim(tmp_path) -> None:
    """`manim` itself, no Manim Studio on the path of the render: the file is self-contained."""
    subprocess.run(
        [
            sys.executable,
            "-m",
            "manim",
            "render",
            "-ql",
            "--disable_caching",
            str(FILE),
            "SmartMorphDemo",
            "--media_dir",
            str(tmp_path / "media"),
        ],
        check=True,
        capture_output=True,
        cwd=tmp_path,
    )
    assert next((tmp_path / "media" / "videos").rglob("SmartMorphDemo.mp4")).stat().st_size > 10_000
