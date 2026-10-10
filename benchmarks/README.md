# Benchmarks

Performance scripts for the per-frame path. They are not part of the test suite.

| script | measures |
|---|---|
| `bench_timeline_drag.py` | S1 acceptance: a clip drag in the real editor window, mouse event → canvas — B16 |
| `bench_edits.py` | one timeline drag step through the edit API (Write clip, morphs) — B15 |
| `bench_code_layer.py` | code layer frame cache and compositing costs — B30 |
| `bench_matching_tex.py` | keyed matching between two equations — B33 |
| `bench_clip_kinds.py` | candidate clip kinds against the random-access rule — B35 |
| `bench_viewport.py` | what a re-framed preview camera costs, and its exactness — B36 |
| `bench_graphs.py` | expression compiler, Axes build, plotting, graph clips under scrubbing — B37 |
| `bench_move_along_path.py` | MoveAlongPath under scrubbing, its cost, an arc-length table — B38 |
| `bench_spatial_paths.py` | curved position segments: raw vs arc-length walking, table cost — B39 |
| `bench_python_export.py` | exported Python (both forms) rendered by Manim vs the editor — B44 |
| `bench_axes_objects.py` | Manim's Axes helpers on our axes and graphs: build cost, scrubbing — B42 |
| `bench_render_ahead.py` | preview frame cost at widget size, keeping frames (raw, zlib), showing them again — B41 |
| `bench_svg.py` | SVGMobject build cost, colours, drawing clips under scrubbing — B40 |
| `bench_anchor.py` | the anchor model and its compensation, numerically — B34 |
| `bench_preview.py` | evaluator, QPainter and Cairo time per frame on the stress scene (20 MathTex, 3 concurrent Writes, 10 keyframed layers) at 960×540 |

```bash
uv run python benchmarks/bench_preview.py
```

When a result informs a decision, append it to
[../docs/logs/benchmarks.md](../docs/logs/benchmarks.md) with the next id, the
date, and the machine if it differs.
