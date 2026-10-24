"""A Python object as a standalone Manim scene (P13.7)."""

from __future__ import annotations

import ast

from manim_studio.core.standalone import standalone_scene

CODE = "PARAMS = {'r': (1.0, 0.5, 3.0), 'label': 'a'}\n\ndef build(p):\n    return Circle(radius=p['r'])\n"


def test_the_result_parses_and_keeps_the_object_text() -> None:
    out = standalone_scene(CODE, {"r": 2.0}, "my wheel")
    ast.parse(out)
    assert out.startswith("from manim import *")
    assert CODE.rstrip() in out
    assert "class MyWheel(Scene):" in out


def test_the_scene_calls_build_with_the_current_values_and_the_defaults() -> None:
    out = standalone_scene(CODE, {"r": 2.0})
    assert "'r': 2.0" in out and "'label': 'a'" in out
    assert "self.add(build(p))" in out


def test_an_existing_manim_import_is_not_repeated() -> None:
    out = standalone_scene("from manim import *\n" + CODE)
    assert out.count("from manim import") == 1


def test_it_runs_as_a_scene_under_manim() -> None:
    import manim

    namespace: dict = {}
    exec(compile(standalone_scene(CODE, {"r": 2.5}), "<standalone>", "exec"), namespace)
    scene_cls = namespace["Object"]
    assert issubclass(scene_cls, manim.Scene)
