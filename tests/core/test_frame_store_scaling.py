"""The frame store keeps its answers while making them O(log n) (P7.2, B64/B66).

``Reference`` is the store as it was: a ``max()`` over every kept frame to evict and a walk over
every frame to ask for the missing ones. The real store must give the same frames, in the same
order, after any sequence of accepts, invalidations and playhead moves.
"""

from __future__ import annotations

import random

import pytest

from manim_studio.core.frame_cache import FrameStore


class Reference:
    def __init__(self, total: int, budget: int) -> None:
        self.total, self.budget = total, budget
        self.frames: dict[int, bytes] = {}
        self.nbytes = 0

    def ahead(self, index: int, playhead: int) -> int:
        return (index - playhead) % max(self.total, index + 1, playhead + 1)

    def accept(self, index: int, data: bytes, playhead: int) -> None:
        old = self.frames.get(index)
        if old is not None:
            self.nbytes -= len(old)
        self.frames[index] = data
        self.nbytes += len(data)
        while self.nbytes > self.budget and len(self.frames) > 1:
            far = max((i for i in self.frames if i != index), key=lambda i: self.ahead(i, playhead))
            self.nbytes -= len(self.frames.pop(far))

    def invalidate(self, indices: list[int]) -> None:
        for i in indices:
            data = self.frames.pop(i, None)
            if data is not None:
                self.nbytes -= len(data)

    def missing(self, start: int, count: int) -> list[int]:
        horizon = self.total
        if self.nbytes >= self.budget * 0.95 and self.frames:
            horizon = max(self.ahead(i, start) for i in self.frames)
        out = []
        for offset in range(horizon):
            index = (start + offset) % self.total
            if index not in self.frames:
                out.append(index)
                if len(out) == count:
                    break
        return out


@pytest.mark.parametrize("seed", range(12))
def test_the_store_answers_like_the_scanning_one(seed: int) -> None:
    rng = random.Random(seed)
    total = rng.choice([7, 40, 300])
    budget = rng.choice([10**9, 20 * 10, 60 * 10, 150 * 10])  # 10-byte frames: never full .. often full
    store, ref = FrameStore(total=total, budget=budget), Reference(total, budget)
    playhead = 0
    for _ in range(600):
        action = rng.random()
        if action < 0.6:
            index = rng.randrange(total)
            data = b"x" * rng.choice([10, 10, 10, 4, 16])
            accepted = store.accept(0, store.generation, index, data, playhead)
            ref.accept(index, data, playhead)
            assert accepted == (index in ref.frames)
        elif action < 0.75:
            dropped = rng.sample(range(total), rng.randrange(1, min(total, 12)))
            store.invalidate(dropped)
            ref.invalidate(dropped)
        else:
            playhead = rng.randrange(total)
        assert dict(store.frames) == ref.frames
        assert store.nbytes == ref.nbytes
        assert sorted(store.frames) == store._order
        start, count = rng.randrange(total), rng.choice([1, 5, 60])
        assert store.missing(start, count) == ref.missing(start, count), (seed, start, count)


class Counting(list):
    reads = 0

    def __getitem__(self, item):
        Counting.reads += 1
        return super().__getitem__(item)


class CountingDict(dict):
    def __contains__(self, key):
        Counting.reads += 1
        return super().__contains__(key)


def full_store(frames: int = 20_000) -> FrameStore:
    store = FrameStore(total=frames * 2, budget=frames * 10)
    store._order = Counting()
    store.frames = CountingDict()
    for i in range(frames):
        store.accept(0, 0, i, b"0123456789", playhead=0)
    return store


def test_accepting_into_a_full_store_does_not_scan_the_kept_frames(monkeypatch) -> None:
    store = full_store()
    assert store.nbytes == store.budget
    scanned = []
    original = FrameStore._ahead
    monkeypatch.setattr(FrameStore, "_ahead", lambda self, *a: scanned.append(1) or original(self, *a))
    for i in range(30_000, 30_050):
        assert store.accept(0, 0, i, b"0123456789", playhead=i - 10)
    assert not scanned, "eviction measured the distance of kept frames one by one"
    store.missing(30_040, 60)  # a full store also looks for its farthest frame to bound the ask
    assert len(scanned) <= 2, "missing() measured the distance of kept frames one by one"
    assert len(store) == 20_000


def test_missing_jumps_over_the_kept_runs_instead_of_walking_them() -> None:
    store = full_store()
    Counting.reads = 0
    got = store.missing(100, 60)
    assert got == list(range(20_000, 20_060))  # the first frames past the kept run
    assert Counting.reads < 400, f"{Counting.reads} reads of the kept index for one missing(60)"
    got = store.missing(0, 60)
    assert Counting.reads < 800
    assert len(got) <= 60
