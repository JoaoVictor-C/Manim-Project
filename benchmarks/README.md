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
| `bench_plugins.py` | plugin discovery, loading, building, the determinism check — B45 |
| `bench_simulation.py` | Manim's TracedPath frame by frame, trace and simulation replay costs — B46 |
| `bench_audio.py` | audio decoding, mixing, Qt playback clock, AAC muxing, Manim's add_sound — B47 |
| `bench_subtitles.py` | building and drawing a subtitle line, wrapping widths — B48 |
| `bench_readouts.py` | DecimalNumber builds and set_value, connectors per frame — B49 |
| `bench_markers.py` | sounds on clip edges in the explainer, snap point gathering — B50 |
| `bench_autosave.py` | recovery copies by project size, duplicate vs any edit, clipboard paste — B51 |
| `bench_presets.py` | repeated clip patterns and layer groups in the explainer — B52 |
| `bench_validation.py` | validation, `add_layer`, `update_layer`, `classify`, `changed_spans` at 20-2000 layers — B53 |
| `bench_design.py` | icon fonts and an application stylesheet: load and apply times — B54 |
| `bench_graph_editor.py` | the Animate page's graph: sampling, repaints, drag steps with up to 1000 keys — B56 |
| `bench_pages.py` | moving the shared views between pages, docks, a second canvas — B55 |
| `bench_deliver.py` | Deliver page: Python preview, queueing, a range exported at 480p/720p/1080p — B59 |
| `bench_code_editor.py` | the Code page's editor on 2000 lines: lexer, highlighting, a typed character, the dirty check, page switch — B57 |
| `bench_audio_page.py` | the level meter (whole mix vs a 100 ms window), table refresh, a cell edit end to end — B58 |
| `bench_handles.py` | parameter handle drags, snap points, moving many objects — B60 |
| `bench_preset_thumbs.py` | every built-in preset drawn as an 8-frame thumbnail at 160x90 — B61 |
| `bench_presets_browser.py` | the presets browser: first open, reopen, a search keystroke, a tab switch, a hover frame — B63 |
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
