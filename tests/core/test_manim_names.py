"""core/manim_names.py and scripts/gen_manim_names.py: the table of Manim's names (P13.0)."""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

from manim_studio.core import manim_names

ROOT = Path(__file__).resolve().parents[2]


def test_the_table_has_the_everyday_names() -> None:
    names = manim_names.names()
    for name in ("Circle", "Create", "MathTex", "UP", "PI", "BLUE", "Scene", "VGroup", "FadeIn"):
        assert name in names
    assert list(names) == sorted(names)
    assert len(names) > 300


def test_modules_and_private_names_are_left_out() -> None:
    names = manim_names.names()
    assert not any(n.startswith("_") for n in names)
    assert "np" not in names and "typing" not in names


def test_methods_of_a_class_include_the_inherited_ones() -> None:
    circle = manim_names.methods("Circle")
    assert "set_color" in circle and "move_to" in circle and "point_at_angle" in circle
    assert list(circle) == sorted(circle)
    assert "set_color" in manim_names.methods("Mobject")
    assert "add_updater" in manim_names.methods("VMobject")
    assert "play" in manim_names.methods("Scene") and "wait" in manim_names.methods("Scene")
    assert "run_time" in manim_names.methods("Create")  # an attribute of every Animation


def test_methods_of_an_unknown_class_are_empty() -> None:
    assert manim_names.methods("NoSuchThing") == ()
    assert manim_names.methods("") == ()


def test_kwargs_of_a_class_and_of_a_function() -> None:
    assert "radius" in manim_names.kwargs("Circle")
    assert "color" in manim_names.kwargs("Circle")
    assert "fill_opacity" in manim_names.kwargs("Circle")  # passed on through **kwargs
    assert "run_time" in manim_names.kwargs("Create")
    assert "kwargs" not in manim_names.kwargs("Circle") and "self" not in manim_names.kwargs("Circle")
    assert manim_names.kwargs("smooth")[0] == "t"
    assert manim_names.kwargs("NoSuchThing") == ()


def test_the_version_stamp_looks_like_a_version() -> None:
    assert re.fullmatch(r"\d+\.\d+(\.\d+)?([.\-+\w]*)?", manim_names.version())


def test_is_known() -> None:
    assert manim_names.is_known("Circle") and manim_names.is_known("PI")
    assert not manim_names.is_known("circle") and not manim_names.is_known("")
    assert not manim_names.is_known("Circl")


def test_close_matches_ranks_the_likeliest_first() -> None:
    assert manim_names.close_matches("Circl", manim_names.names())[0] == "Circle"
    assert "FadeIn" not in manim_names.close_matches("FadeIn", manim_names.names())  # not itself
    assert manim_names.close_matches("Creat", manim_names.names())[0] == "Create"
    assert len(manim_names.close_matches("Squar", manim_names.names(), n=2)) <= 2


def test_close_matches_tries_case_first() -> None:
    assert manim_names.close_matches("circle", manim_names.names())[0] == "Circle"
    assert manim_names.close_matches("blue", manim_names.names())[0] == "BLUE"
    assert manim_names.close_matches("x", ["X", "xy"], 3)[0] == "X"


def test_close_matches_cutoff_and_junk() -> None:
    assert manim_names.close_matches("zzzzzz", ["Circle", "Square"]) == []
    assert manim_names.close_matches("", ["Circle"]) == []
    assert manim_names.close_matches("Circle", ["Circle"], 0) == []
    assert manim_names.close_matches("Circl", []) == []
    assert manim_names.close_matches("Circl", ["Circle", "Circle"]) == ["Circle"]


def test_the_file_is_small_enough_and_inside_the_package() -> None:
    assert manim_names.FILE.stat().st_size < 600_000
    assert manim_names.FILE.parent.name == "core"


def test_a_missing_file_gives_an_empty_table(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    manim_names._table.cache_clear()
    manim_names._name_set.cache_clear()
    manim_names.methods.cache_clear()
    monkeypatch.setattr(manim_names, "FILE", tmp_path / "missing.json")
    try:
        assert manim_names.names() == () and manim_names.version() == ""
        assert manim_names.methods("Circle") == () and not manim_names.is_known("Circle")
    finally:
        monkeypatch.undo()
        manim_names._table.cache_clear()
        manim_names._name_set.cache_clear()
        manim_names.methods.cache_clear()


@pytest.mark.slow
def test_the_shipped_file_matches_the_installed_manim(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location("gen_manim_names", ROOT / "scripts" / "gen_manim_names.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["gen_manim_names"] = module
    try:
        spec.loader.exec_module(module)
        target = tmp_path / "manim_names.json"
        assert module.write(target) is True
        assert module.write(target) is False  # idempotent
        shipped = manim_names.FILE.read_bytes()
        assert target.read_bytes() == shipped, (
            "src/manim_studio/core/manim_names.json is out of date (Manim's version or names changed): "
            "run `python scripts/gen_manim_names.py` and commit the result"
        )
    finally:
        sys.modules.pop("gen_manim_names", None)
