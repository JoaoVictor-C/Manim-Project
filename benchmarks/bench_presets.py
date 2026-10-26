"""B52 - presets and templates: how repetitive a real project is.

On examples/explainer.json (built by examples/build_explainer.py):
1. clip patterns: how often each (kind, duration, ease) recurs, and each layer's sequence of
   clip kinds (an "entrance + exit" pattern repeated across layers is a preset candidate);
2. key patterns: layers whose keyframe tracks have the same shape (times relative to the
   first key, values relative to the first value);
3. groups of layers created together (same name prefix): template candidates.

Run: ``python benchmarks/bench_presets.py`` (after ``python examples/build_explainer.py``).
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from manim_studio.core.model.schema import Project

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "explainer.json"


def main() -> None:
    project = Project.model_validate_json(EXAMPLE.read_text(encoding="utf-8"))
    clips = [
        (c.kind, round(c.duration, 2), c.ease.name if c.ease else None)
        for x in project.layers
        for c in x.clips
    ]
    print(f"{len(project.layers)} layers, {len(clips)} clips")
    counts = Counter(clips)
    repeated = sum(n for n in counts.values() if n > 1)
    print(f"clips sharing kind+duration+ease with another: {repeated}/{len(clips)}")
    for pattern, n in counts.most_common(6):
        print(f"  {n:3d} x {pattern}")
    sequences = Counter(tuple(c.kind for c in x.clips) for x in project.layers if x.clips)
    print("layer clip sequences:")
    for seq, n in sequences.most_common(6):
        print(f"  {n:3d} x {' -> '.join(seq)}")
    shapes = Counter()
    for layer in project.layers:
        for prop, track in layer.tracks.items():
            if len(track) < 2:
                continue
            t0, v0 = track[0].t, track[0].value
            rel = tuple(
                (
                    round(k.t - t0, 2),
                    tuple(round(a - b, 2) for a, b in zip(k.value, v0, strict=True))
                    if isinstance(k.value, tuple)
                    else round(k.value - v0, 2),
                )
                for k in track
            )
            shapes[(prop, rel)] += 1
    keyed, shared = sum(shapes.values()), sum(n for n in shapes.values() if n > 1)
    print(f"keyed tracks: {keyed}, sharing a relative shape with another: {shared}")
    prefixes = Counter(re.sub(r"[-_ ]?\d+$", "", x.name or x.id) for x in project.layers)
    print("layer name stems used more than once:", {k: n for k, n in prefixes.items() if n > 1})


if __name__ == "__main__":
    main()
