"""Cutting a scene's code, moving statements to a layer, proving a split (ADR 0061)."""

from __future__ import annotations

import ast

import numpy as np
import pytest

from manim_studio.core.code.code_cache import CodeCache
from manim_studio.core.code.scene_analysis import analyse
from manim_studio.core.code.scene_split import chapter_codes, move_selection, verify
from manim_studio.core.editing import edits
from manim_studio.core.model.schema import Canvas, Layer, Project, Spec

from .test_scene_analysis import PHASE_ROWS, probes

SCENE = """\
SPEED = 2  # module level stays


class Main(Scene):
    def construct(self):
        self.add(Line(LEFT, RIGHT))
        gap = 0.5
        a = Dot()
        self.play(FadeIn(a))  # phase one
        self.play(FadeOut(a))
        b = Square()
        self.play(FadeIn(b))
        self.play(FadeOut(b))
        c = Circle()
        self.play(FadeIn(c))
        self.play(FadeOut(c))
"""


def analysed():
    return analyse(SCENE, probes(PHASE_ROWS), fps=10, total_frames=60)


def test_each_chapter_keeps_the_setup_and_only_its_own_statements() -> None:
    chapters = chapter_codes(SCENE, analysed())
    assert [(c.start_frame, c.end_frame) for c in chapters] == [(0, 20), (20, 40), (40, None)]
    for code, own, others in (
        (chapters[0].code, "FadeIn(a)", ("FadeIn(b)", "FadeIn(c)")),
        (chapters[1].code, "FadeIn(b)", ("FadeIn(a)", "FadeIn(c)")),
        (chapters[2].code, "FadeIn(c)", ("FadeIn(a)", "FadeIn(b)")),
    ):
        ast.parse(code)
        assert "SPEED = 2  # module level stays" in code and "gap = 0.5" in code  # the setup and the module
        assert "self.add(Line(LEFT, RIGHT))" in code and own in code
        assert not any(other in code for other in others)
    assert "# phase one" in chapters[0].code  # comments inside a kept statement survive


def test_a_scene_that_does_not_split_gives_no_chapters() -> None:
    assert chapter_codes(SCENE, analyse(SCENE, None)) == []


def test_moving_statements_makes_two_programs_and_warns_about_crossing_names() -> None:
    moved = move_selection(SCENE, 11, 13)  # b = Square() and its two plays
    assert moved.problem == ""
    ast.parse(moved.kept)
    ast.parse(moved.moved)
    assert "Square()" in moved.moved and "Square()" not in moved.kept
    assert "Dot()" in moved.kept and "Dot()" not in moved.moved
    assert moved.warnings == []  # b is self-contained
    crossing = SCENE.replace("b = Square()", "b = Square().next_to(a)")
    warned = move_selection(crossing, 11, 13)
    assert warned.warnings and "a" in warned.warnings[0] and "defined in what stays" in warned.warnings[0]


def test_moving_nothing_or_everything_is_refused() -> None:
    assert "select some statements" in move_selection(SCENE, 1, 2).problem  # module level, no statement
    assert "whole scene" in move_selection(SCENE, 1, 99).problem
    assert "does not parse" in move_selection("def (:", 1, 2).problem


# -- verification ---------------------------------------------------------------------------------


def write(cache: CodeCache, key: str, frames: list[np.ndarray]):
    writer = cache.writer(key, 32, 18, 10, workers=0)
    for frame in frames:
        writer.add(frame)
    writer.finish()
    return cache.open(key)


def picture(seed: int) -> np.ndarray:
    frame = np.zeros((18, 32, 4), dtype=np.uint8)
    frame[3:9, 4:20] = np.random.default_rng(seed).integers(1, 255, (6, 16, 4), dtype=np.uint8)
    return frame


def test_verify_accepts_chapters_that_are_the_whole(tmp_path) -> None:
    cache = CodeCache(tmp_path)
    pictures = [picture(i) for i in range(6)]
    whole = write(cache, "whole", pictures)
    first = write(cache, "c1", pictures[:4])
    second = write(cache, "c2", pictures[4:])
    verdict = verify(whole, [(first, 0), (second, 4)])
    assert verdict.ok and verdict.checked == 6 and "identical" in verdict.message


def test_verify_names_the_first_frame_that_differs(tmp_path) -> None:
    cache = CodeCache(tmp_path)
    pictures = [picture(i) for i in range(6)]
    whole = write(cache, "whole", pictures)
    first = write(cache, "c1", pictures[:4])
    second = write(cache, "c2", [pictures[4], picture(99)])
    verdict = verify(whole, [(first, 0), (second, 4)])
    assert not verdict.ok and verdict.first_bad == 5 and "frame 5" in verdict.message


def test_verify_refuses_chapters_of_the_wrong_length(tmp_path) -> None:
    cache = CodeCache(tmp_path)
    pictures = [picture(i) for i in range(6)]
    whole = write(cache, "whole", pictures)
    short = write(cache, "c1", pictures[:3])
    rest = write(cache, "c2", pictures[4:])
    verdict = verify(whole, [(short, 0), (rest, 4)])
    assert not verdict.ok and "chapter 1 has 3 frames but covers 4" in verdict.message
    assert not verify(whole, [(rest, 4)]).ok


def test_verify_can_be_stopped_and_reports_progress(tmp_path) -> None:
    cache = CodeCache(tmp_path)
    pictures = [picture(i) for i in range(60)]
    whole = write(cache, "whole", pictures)
    half = write(cache, "c1", pictures[:30])
    rest = write(cache, "c2", pictures[30:])
    seen = []
    assert verify(whole, [(half, 0), (rest, 30)], progress=lambda a, b: seen.append((a, b))).ok
    assert seen[0] == (0, 60) and seen[-1][1] == 60
    stopped = verify(whole, [(half, 0), (rest, 30)], should_stop=lambda: True)
    assert not stopped.ok and stopped.message == "stopped"


# -- the edits --------------------------------------------------------------------------------------


def project() -> Project:
    layers = [
        Layer(id="under", spec=Spec(type="Square")),
        Layer(
            id="scene",
            name="Orbit",
            spec=Spec(type="Code", params={"code": SCENE}),
            lifetime={"in": 2.0, "out": 20.0},
        ),
        Layer(id="over", spec=Spec(type="Circle")),
    ]
    return Project(canvas=Canvas(width_px=320, height_px=180, fps=10, duration=30.0), layers=layers)


def test_a_split_replaces_the_layer_by_chapters_in_the_same_place() -> None:
    parts = [(c.code, c.start_frame, c.start_time, c.name) for c in chapter_codes(SCENE, analysed())]
    result = edits.split_code_layer(project(), "scene", parts).project
    assert result.layers[0].id == "under" and result.layers[-1].id == "over"
    chapters = result.layers[1:4]
    assert [x.name for x in chapters] == ["Orbit - chapter 1", "Orbit - chapter 2", "Orbit - chapter 3"]
    assert [(x.lifetime.in_, x.lifetime.out) for x in chapters] == [(2.0, 4.0), (4.0, 6.0), (6.0, 20.0)]
    assert [x.spec.params.get("start_frame", 0) for x in chapters] == [0, 20, 40]
    assert all(x.spec.type == "Code" for x in chapters) and chapters[1].spec.params["code"] == parts[1][0]


def test_a_split_of_something_else_or_into_one_is_refused() -> None:
    p = project()
    with pytest.raises(edits.EditError, match="not a code layer"):
        edits.split_code_layer(p, "under", [("a", 0, 0.0, "x"), ("b", 5, 0.5, "y")])
    with pytest.raises(edits.EditError, match="at least two"):
        edits.split_code_layer(p, "scene", [("a", 0, 0.0, "x")])
    with pytest.raises(edits.EditError, match="frame 0"):
        edits.split_code_layer(p, "scene", [("a", 3, 0.3, "x"), ("b", 5, 0.5, "y")])


def test_moving_to_a_new_layer_keeps_the_look_and_adds_a_copy_above() -> None:
    moved = move_selection(SCENE, 11, 13)
    result = edits.move_code_to_new_layer(project(), "scene", moved.kept, moved.moved).project
    ids = [x.id for x in result.layers]
    assert ids[:2] == ["under", "scene"] and ids[3] == "over" and len(ids) == 4
    original, new = result.layers[1], result.layers[2]
    assert original.spec.params["code"] == moved.kept and new.spec.params["code"] == moved.moved
    assert new.lifetime == original.lifetime and new.name == "Orbit (moved)"
