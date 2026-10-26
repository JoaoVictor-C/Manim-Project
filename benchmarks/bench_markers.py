"""B50 - markers and snapping: what the explainer's hand-timed sounds line up with, and what
gathering snap candidates costs on a large project.

1. For every sound in examples/explainer.json (built by examples/build_explainer.py): the
   distance from its start to the nearest clip edge, key time and subtitle edge.
2. The number of snap candidates (clip edges, key times, sound and subtitle edges) and the time
   to gather and search them, as a drag does on every mouse move.

Run: ``python benchmarks/bench_markers.py`` (after ``python examples/build_explainer.py``).
"""

from __future__ import annotations

import statistics
import time
from pathlib import Path

from manim_studio.core.model.schema import Project

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "explainer.json"


def edges(project: Project) -> dict[str, list[float]]:
    return {
        "clip": sorted({t for x in project.layers for c in x.clips for t in (c.start, c.end)}),
        "key": sorted({k.t for x in project.layers for track in x.tracks.values() for k in track}),
        "cue": sorted({t for cue in project.subtitles for t in (cue.start, cue.end)}),
    }


def nearest(t: float, points: list[float]) -> float:
    return min((abs(p - t) for p in points), default=float("inf"))


def main() -> None:
    project = Project.model_validate_json(EXAMPLE.read_text(encoding="utf-8"))
    groups = edges(project)
    fps = project.canvas.fps
    print(f"{len(project.layers)} layers, {len(project.audio)} sounds, {len(project.subtitles)} cues")
    within = {name: 0 for name in groups}
    any_edge = 0
    for clip in project.audio:
        distances = {name: nearest(clip.start, points) for name, points in groups.items()}
        for name, d in distances.items():
            within[name] += d <= 0.5 / fps
        any_edge += min(distances.values()) <= 0.5 / fps
    for name, count in within.items():
        print(f"sounds starting on a {name} edge (within half a frame): {count}/{len(project.audio)}")
    print(f"on any edge: {any_edge}/{len(project.audio)}")

    def gather() -> list[float]:
        points = {0.0, project.canvas.duration}
        for points_of in edges(project).values():
            points.update(points_of)
        points.update(t for c in project.audio for t in (c.start, c.end))
        return sorted(points)

    samples = []
    for _ in range(50):
        start = time.perf_counter()
        candidates = gather()
        min(candidates, key=lambda c: abs(c - 12.34))
        samples.append((time.perf_counter() - start) * 1000)
    print(f"{len(candidates)} candidates, gathered and searched in {statistics.median(samples):.3f} ms")


if __name__ == "__main__":
    main()
