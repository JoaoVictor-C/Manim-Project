"""Chapters end to end (ADR 0061): real Manim renders a scene whole and in chapters, and the frames match.

The runner records the scene at statement boundaries while it renders; the analyser reads them; the split
cuts the code; the chapters render from their own start frame; the verifier compares every frame.
"""

from __future__ import annotations

import json

import pytest

from manim_studio.code_runner import Job, render_code
from manim_studio.core.code_cache import CodeCache, cache_key
from manim_studio.core.scene_analysis import analyse
from manim_studio.core.scene_split import chapter_codes, verify

pytestmark = pytest.mark.slow

FPS = 10
VERSION = "test"

THREE_PHASES = """
class Main(Scene):
    def construct(self):
        self.add(Line(LEFT * 3, RIGHT * 3, color=GREY))
        base = 0.5
        a = Dot(LEFT, color=RED)
        self.play(FadeIn(a), run_time=base)
        self.play(a.animate.shift(RIGHT * 2), run_time=1)
        self.play(FadeOut(a), run_time=base)
        b = Square(0.8, color=BLUE)
        tr = ValueTracker(0)
        b.add_updater(lambda mob: mob.set_x(tr.get_value()))
        self.play(FadeIn(b), run_time=base)
        self.play(tr.animate.set_value(2), run_time=1)
        self.play(FadeOut(b), run_time=base)
        c = Circle(0.4, color=GREEN)
        self.play(Create(c), run_time=1)
        self.play(c.animate.scale(2), run_time=1)
        self.play(FadeOut(c), run_time=base)
"""

# the last phase starts from where the first one left its dot: it cannot be rendered on its own
COUPLED = THREE_PHASES.replace("Circle(0.4, color=GREEN)", "Circle(0.4, color=GREEN).move_to(a)")

# a scene that reads the scene's own clock: a chapter must start with the clock where the whole one was
CLOCK = """
class Main(Scene):
    def construct(self):
        self.add(Line(LEFT * 3, RIGHT * 3, color=GREY))
        a = Dot(LEFT, color=RED)
        self.play(FadeIn(a), run_time=1)
        self.play(FadeOut(a), run_time=1)
        b = Dot(color=BLUE).move_to(RIGHT * (self.time - 1.5))
        self.play(FadeIn(b), run_time=1)
        self.play(FadeOut(b), run_time=1)
"""


def render(cache: CodeCache, code: str, start: int = 0, clock: float | None = None) -> str:
    key = cache_key(code, 160, 90, FPS, 8.0, VERSION, "", start, clock)
    if not cache.has(key):
        render_code(Job(key, code, 160, 90, FPS, 8.0, start_frame=start, start_time=clock), cache)
    return key


def test_a_job_with_a_start_frame_says_so_and_one_without_does_not() -> None:
    plain = Job("k", "x", 160, 90, 10, 8.0)
    assert "start_frame" not in json.loads(plain.to_json())
    assert "start_time" not in json.loads(plain.to_json())
    chapter = Job("k", "x", 160, 90, 10, 8.0, start_frame=40, start_time=4.000000000000001)
    again = Job.from_json(chapter.to_json())
    assert (again.start_frame, again.start_time) == (40, 4.000000000000001)  # the exact float survives
    assert (
        Job.from_json(plain.to_json()).start_frame == 0 and Job.from_json(plain.to_json()).start_time is None
    )


def test_a_render_records_the_scene_at_each_statement(tmp_path) -> None:
    cache = CodeCache(tmp_path)
    clip = cache.open(render(cache, THREE_PHASES))
    probes = clip.probes
    assert [p["stmt"] for p in probes] == list(range(16))
    assert (
        probes[3]["frame"] == 0 and probes[4]["frame"] == 5
    )  # the first play is statement 3 (a is made at 2)
    assert probes[15]["frame"] == 60  # before the last play (0.5 s = 5 frames more)
    # back to the setup after each fade: the same picture, so the same digest
    assert probes[3]["visible"] == probes[7]["visible"] == probes[13]["visible"]
    assert probes[3]["visible"] != probes[4]["visible"]
    assert "a" in probes[4]["names"] and "tr" not in probes[4]["names"]  # variables made so far, by name
    assert probes[4]["names"]["a"] != probes[5]["names"]["a"]  # and how far each has got


def test_a_scene_of_phases_renders_the_same_whole_and_in_chapters(tmp_path) -> None:
    cache = CodeCache(tmp_path)
    key = render(cache, THREE_PHASES)
    whole = cache.open(key)
    result = analyse(THREE_PHASES, whole.probes, FPS, whole.frame_count)
    assert [(c.first, c.end, c.start_frame) for c in result.chapters] == [
        (3, 6, 0),
        (6, 12, 20),
        (12, 16, 40),
    ]
    chapters = chapter_codes(THREE_PHASES, result)
    clips = [
        (cache.open(render(cache, c.code, c.start_frame, c.start_time)), c.start_frame) for c in chapters
    ]
    verdict = verify(whole, clips)
    assert verdict.ok, verdict.message
    assert verdict.checked == whole.frame_count == 65


def test_a_chapter_costs_only_its_own_frames(tmp_path) -> None:
    cache = CodeCache(tmp_path)
    whole = cache.open(render(cache, THREE_PHASES))
    result = analyse(THREE_PHASES, whole.probes, FPS, whole.frame_count)
    middle = chapter_codes(THREE_PHASES, result)[1]
    clip = cache.open(render(cache, middle.code, middle.start_frame, middle.start_time))
    assert clip.frame_count == 20 < whole.frame_count


def test_a_phase_that_needs_an_earlier_object_is_not_cut(tmp_path) -> None:
    cache = CodeCache(tmp_path)
    whole = cache.open(render(cache, COUPLED))
    result = analyse(COUPLED, whole.probes, FPS, whole.frame_count)
    # a is made in the setup, moved by phase 1 and used by phase 3: no cut can leave phase 1 behind
    assert not result.splittable
    assert any("use a" in r for cut in result.cuts for r in cut.reasons)


def test_the_scene_clock_of_a_chapter_starts_where_the_whole_one_was(tmp_path) -> None:
    cache = CodeCache(tmp_path)
    whole = cache.open(render(cache, CLOCK))
    result = analyse(CLOCK, whole.probes, FPS, whole.frame_count)
    assert result.splittable
    chapters = chapter_codes(CLOCK, result)
    clips = [
        (cache.open(render(cache, c.code, c.start_frame, c.start_time)), c.start_frame) for c in chapters
    ]
    assert verify(whole, clips).ok  # b sits at x = time - 1.5 in both
