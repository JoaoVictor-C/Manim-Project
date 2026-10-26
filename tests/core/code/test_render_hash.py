"""What a render's identity ignores, and the frame writer's pool (ADR 0061)."""

from __future__ import annotations

import numpy as np

from manim_studio.core.code.code_cache import CodeCache, cache_key, code_hash, render_hash

SCENE = "class A(Scene):\n    def construct(self):\n        x = 1  # note\n\n        self.add(Dot())\n"


def test_comments_blank_lines_spacing_and_indent_width_do_not_change_a_render() -> None:
    other = "class A(Scene):\n  def construct(self):\n      x   =  1\n      self.add(Dot())\r\n"
    assert render_hash(SCENE) == render_hash(other)
    assert code_hash(SCENE) != code_hash(other)  # trust is about the exact text


def test_anything_that_can_draw_differently_changes_it() -> None:
    assert render_hash(SCENE) != render_hash(SCENE.replace("x = 1", "x = 2"))
    assert render_hash(SCENE.replace("Dot()", 'Text("a  b")')) != render_hash(
        SCENE.replace("Dot()", 'Text("a b")')
    )
    doc = 'class A(Scene):\n    """one"""\n    def construct(self):\n        self.add(Text(__doc__))\n'
    assert render_hash(doc) != render_hash(doc.replace("one", "two"))  # a scene can draw its docstring


def test_code_that_does_not_tokenise_still_has_an_identity() -> None:
    assert render_hash("def (:") != render_hash("def (; ")
    assert render_hash("x = '''never closed") == render_hash("x = '''never closed")


def test_a_chapter_is_not_the_whole_scene() -> None:
    args = (320, 180, 10, 8.0, "0.22.0")
    assert cache_key(SCENE, *args) == cache_key(SCENE, *args, "", 0)
    assert cache_key(SCENE, *args, "", 40) != cache_key(SCENE, *args)
    assert cache_key(SCENE, *args, "", 40) != cache_key(SCENE, *args, "", 80)


def test_the_writer_pool_stores_exactly_what_the_plain_writer_does(tmp_path) -> None:
    sequences = {}
    for workers in (0, 3):
        cache = CodeCache(tmp_path / f"w{workers}")
        writer = cache.writer("k", 32, 18, 10, workers=workers)
        shared = np.zeros((18, 32, 4), dtype=np.uint8)  # drawn into again and again, as Manim does
        rng = np.random.default_rng(5)
        for _ in range(40):
            shared[:] = 0
            h = int(rng.integers(2, 12))
            shared[1 : 1 + h, 2:30] = rng.integers(1, 255, (h, 28, 4), dtype=np.uint8)
            writer.add(shared)
        writer.finish()
        clip = cache.open("k")
        sequences[workers] = [
            None if (c := clip.crop(i)) is None else (c.x, c.y, c.pixels.tobytes()) for i in range(40)
        ]
    assert sequences[0] == sequences[3]


def test_probes_ride_with_the_frames(tmp_path) -> None:
    cache = CodeCache(tmp_path)
    writer = cache.writer("k", 32, 18, 10)
    writer.probes.append({"stmt": 0, "frame": 0, "visible": "abc"})
    writer.add(np.zeros((18, 32, 4), dtype=np.uint8))
    assert writer.frame_count == 1
    writer.finish()
    assert cache.open("k").probes == [{"stmt": 0, "frame": 0, "visible": "abc"}]
