"""Code layer frame cache and trust store (P2d.1, ADR 0019) — pure, no Manim."""

from __future__ import annotations

import os
import time

import numpy as np
import pytest

from manim_studio.core.code.code_cache import CodeCache, cache_key, code_hash, crop_frame
from manim_studio.core.code.trust import TrustStore, project_code
from manim_studio.core.model.schema import Layer, Project, Spec


def frame(w: int = 40, h: int = 20, box=None, rgba=(255, 0, 0, 255)) -> np.ndarray:
    out = np.zeros((h, w, 4), dtype=np.uint8)
    if box is not None:
        x0, y0, x1, y1 = box
        out[y0:y1, x0:x1] = rgba
    return out


def test_crop_keeps_only_visible_pixels_as_they_are() -> None:
    crop = crop_frame(frame(box=(5, 3, 9, 7), rgba=(100, 50, 25, 128)))  # premultiplied, as Cairo stores it
    assert (crop.x, crop.y, crop.pixels.shape) == (5, 3, (4, 4, 4))
    assert tuple(crop.pixels[0, 0]) == (100, 50, 25, 128)
    assert crop_frame(frame()) is None
    assert crop.pixels.flags["C_CONTIGUOUS"]


def test_a_render_round_trips_with_repeats_and_empty_frames(tmp_path) -> None:
    cache = CodeCache(tmp_path)
    writer = cache.writer("k", 40, 20, 10)
    a, b = frame(box=(0, 0, 4, 4)), frame(box=(10, 10, 20, 15), rgba=(0, 255, 0, 255))
    for f in (a, a, frame(), b):  # the same array twice = a held frame (Scene.wait)
        writer.add(f)
    assert not cache.has("k")  # invisible until finished
    writer.finish()
    clip = cache.open("k")
    assert (clip.frame_count, clip.fps, clip.duration) == (4, 10, 0.4)
    assert (
        len(list((tmp_path / "k").glob("*.z"))) == 2
    )  # the repeat reused its file, the empty frame has none
    assert (clip.crop(0).x, clip.crop(1).x) == (0, 0)
    assert clip.crop(2) is None
    assert (clip.crop(3).x, clip.crop(3).y) == (10, 10)
    assert clip.crop(99).x == 10 and clip.crop(-5).x == 0  # held at both ends


def test_an_aborted_render_leaves_nothing(tmp_path) -> None:
    cache = CodeCache(tmp_path)
    writer = cache.writer("k", 4, 4, 10)
    writer.add(frame(4, 4, box=(0, 0, 2, 2)))
    writer.abort()
    assert not cache.has("k") and list(tmp_path.iterdir()) == []


def test_eviction_drops_the_least_recently_used_but_keeps_the_open_project(tmp_path) -> None:
    cache = CodeCache(tmp_path)
    for i, key in enumerate(("old", "kept", "new")):
        writer = cache.writer(key, 40, 20, 10)
        writer.add(np.random.default_rng(i).integers(0, 255, (20, 40, 4), dtype=np.uint8))
        writer.finish()
        stamp = time.time() - 100 + i * 10
        os.utime(tmp_path / key / "index.json", (stamp, stamp))
    one = sum(f.stat().st_size for f in (tmp_path / "new").iterdir())
    assert cache.evict(max_bytes=int(one * 2.5), keep={"kept"}) == ["old"]  # two renders fit
    assert cache.has("kept") and cache.has("new") and not cache.has("old")
    assert cache.open("old") is None


def test_the_key_follows_what_a_render_depends_on() -> None:
    base = cache_key("x = 1\n", 1280, 720, 30, 8.0, "0.22.0")
    assert cache_key("x = 1\r\n", 1280, 720, 30, 8.0, "0.22.0") == base  # line endings do not matter
    for changed in (
        cache_key("x = 2\n", 1280, 720, 30, 8.0, "0.22.0"),
        cache_key("x = 1\n", 640, 360, 30, 8.0, "0.22.0"),
        cache_key("x = 1\n", 1280, 720, 60, 8.0, "0.22.0"),
        cache_key("x = 1\n", 1280, 720, 30, 9.0, "0.22.0"),
        cache_key("x = 1\n", 1280, 720, 30, 8.0, "0.23.0"),
    ):
        assert changed != base
    assert code_hash("a\r\nb") == code_hash("a\nb")


def test_the_trust_store_remembers_hashes_and_finds_untrusted_layers(tmp_path) -> None:
    path = tmp_path / "trust" / "trusted.json"
    project = Project(
        layers=[
            Layer(id="mine", spec=Spec(type="Code", params={"code": "class A(Scene): pass"})),
            Layer(id="theirs", spec=Spec(type="Code", params={"code": "import os"})),
            Layer(id="sq", spec=Spec(type="Square")),
        ]
    )
    store = TrustStore(path)
    assert store.untrusted(project) == ["mine", "theirs"]
    store.trust([project_code(project)["mine"]])
    assert TrustStore(path).untrusted(project) == ["theirs"]  # saved
    assert "import os" not in path.read_text(encoding="utf-8")  # hashes only


def test_the_default_store_location_can_be_overridden(monkeypatch, tmp_path) -> None:
    from manim_studio.core.code import trust

    monkeypatch.setenv("MANIM_STUDIO_TRUST_FILE", str(tmp_path / "t.json"))
    assert trust.default_path() == tmp_path / "t.json"


@pytest.mark.parametrize("clips", [True])
def test_code_layers_have_no_clips_and_cannot_be_morph_targets(clips) -> None:
    from pydantic import ValidationError

    from manim_studio.core.model.schema import Clip

    code = Spec(type="Code", params={"code": "class A(Scene): pass"})
    with pytest.raises(ValidationError, match="code layers have no clips"):
        Layer(id="c", spec=code, clips=[Clip(id="f", kind="FadeIn", start=0, duration=1)])
    morph = Clip(id="m", kind="Transform", start=0, duration=1, to_layer="c")
    with pytest.raises(ValidationError, match="cannot morph into a code layer"):
        Project(layers=[Layer(id="sq", spec=Spec(type="Square"), clips=[morph]), Layer(id="c", spec=code)])
