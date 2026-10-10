# Benchmarks

Performance scripts for the per-frame path. They are not part of the test suite.

| script | measures |
|---|---|
| `bench_timeline_drag.py` | S1 acceptance: a clip drag in the real editor window, mouse event → canvas — B16 |
| `bench_edits.py` | one timeline drag step through the edit API (Write clip, morphs) — B15 |
| `bench_code_layer.py` | code layer frame cache and compositing costs — B30 |
| `bench_matching_tex.py` | keyed matching between two equations — B33 |
| `bench_anchor.py` | the anchor model and its compensation, numerically — B34 |
| `bench_preview.py` | evaluator, QPainter and Cairo time per frame on the stress scene (20 MathTex, 3 concurrent Writes, 10 keyframed layers) at 960×540 |

```bash
uv run python benchmarks/bench_preview.py
```

When a result informs a decision, append it to
[../docs/logs/benchmarks.md](../docs/logs/benchmarks.md) with the next id, the
date, and the machine if it differs.
