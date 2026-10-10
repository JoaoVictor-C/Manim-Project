# Testing

```bash
uv run pytest                 # everything, in parallel (up to 8 workers)
uv run pytest -m "not slow"   # the quick loop: no real subprocesses (~30 s)
uv run pytest -n 0 -s tests/core/test_edits.py   # one worker: for pdb, print, -s
```

The suite runs in parallel by default (`pytest-xdist`, `--dist=worksteal`,
see `addopts` in `pyproject.toml`). Each worker gets its own Manim cache under
`.cache/test-workers/<worker>`, seeded with the shared cache's compiled LaTeX
and text, so workers never write the same file at once. Tests marked **`slow`**
start real processes — the build worker, the renderer, the code runner — and
pay Manim's import (5-8 s here) each time; skip them while iterating.

`conftest.py` puts Manim back on the shared cache after every test: CLI tests
point it at their own folder, and leaving it there made every later LaTeX build
compile from scratch (that alone cost a minute, B32).

In tests marked `ui`, an exception raised inside a Qt slot (a menu action, a
timer, a signal handler) fails the test: Qt only prints such exceptions, so a
broken handler used to pass unnoticed.

## Layout

```
tests/
├── conftest.py        Manim cache + LaTeX setup, session `qt_app`, auto-skip of `latex`
├── support.py         shared constants (CANVAS, SQUARE, TEXT, …) and frame helpers
├── test_logging.py    logging setup (ADR 0011)
├── core/
│   ├── test_random_access.py   frames == Manim's sequential loop, incl. extreme easings
│   ├── test_properties.py      random projects: order independence, invalidation
│   ├── test_images.py          ImageMobject layers vs an independent reference
│   ├── test_invalidation.py    edit classes (ADR 0008)
│   ├── test_lifetime.py        visibility rules
│   ├── test_edits.py           edit API, edit kinds, structural edits through the evaluator
│   ├── test_warm.py            warm keys and the warm gate (ADR 0015)
│   ├── test_schema.py          validation rules, JSON round trip, examples
│   ├── test_adapter.py         registry parity, builders, clamping, patches
│   ├── test_registry.py        object library: every type builds, every exposed param has an effect
│   ├── test_easing.py          cubic-bezier vs CSS reference, keyframe sampling
│   └── test_transforms.py      numpy transforms == Manim methods
├── render/            Qt paths vs Cairo; video export and CLI
└── ui/                editor: load/save, errors, wall-clock playback, stepping;
                       document/undo, timeline, build service (fake worker),
                       worker process (stand-in programs + the real worker)
```

Coverage: `uv run pytest --cov=manim_studio --cov-report=term-missing`
(93 % at the last count; the full suite takes 75-100 s in parallel, most of it real
subprocesses — the build worker and the renderer — and LaTeX).

`ui/test_acceptance_p2a.py`, `ui/test_acceptance_p2b.py` and
`ui/test_acceptance_p2c.py` are the Phase 2 acceptance tests (scale/rotate and
auto-key; keyframes on the timeline and the curve editor; terms of an equation
as part layers, with the exported video checked against hand-built Manim).
`ui/test_acceptance_p3f.py` opens the stress scene with the real preview
process, waits for every frame, then checks playback shows kept frames equal
to live ones, an edit to a late layer keeps the early frames and a zoom
refills; `ui/test_render_ahead.py` drives the same wiring with an in-process
stand-in, `ui/test_preview_process.py` the process itself (bit-exact frames,
generations, views, restart), `core/test_frame_cache.py` the spans (checked
exhaustively against rendered frames) and the store. Tests run with
`MANIM_STUDIO_PREVIEW=0` unless they opt in.
`ui/test_acceptance_p3e.py` adds an SVG through Media > SVG, draws it on with
DrawBorderThenFill, rewrites and deletes the file (redrawn on activation,
placeholder and message) and exports; `core/test_svg.py` covers colours, the
clip harness on SVGs, every kind of unreadable file, `check_media` with
checkpoints and path followers, and the export of a missing file.
`ui/test_acceptance_p3d.py` keys a dot, smooths a key and pulls its handle on
the canvas, then checks the arc, scrubbing and the export;
`core/test_motion_paths.py` covers arc-length walking, overshoot, edits that
keep tangents and the shape-keeping split.
`ui/test_acceptance_p3c.py` runs a dot along sin(x) through the menus (centre
on the curve, scrub = play, export = editor); `core/test_paths.py` checks the
path clips against Manim's MoveAlongPath, re-runs after moving either layer,
and runs the two-layer harness.
`ui/test_acceptance_p3b.py` adds axes and two graphs through the UI, draws
one with Create and turns it into the other (scrub = play, export = editor);
`core/test_graphs.py` covers expressions, the child-object rules, plotting and
evaluation against hand-built Manim, and runs the clip harness on a graph.
`ui/test_acceptance_p3a.py` zooms into a term of a split equation with
Ctrl+wheel, scales it by a corner at 400 % and fits back (export = editor);
`ui/test_viewport.py` covers the view model and the canvas input.
`ui/test_acceptance_p2g.py` circles a term of a split equation with
Circumscribe from the timeline, recolours it and fades a title in from the left
through Properties (scrub = play, export = editor); `core/test_clip_kinds.py`
samples every registered clip param through the random-access harness and
checks Circumscribe against Manim's own Succession played forward.
`ui/test_acceptance_p2f.py` drags a line's pivot cross to its top end, keys a
swing through Properties, and checks the top stays put in every frame and in
the export; `core/test_anchor.py` checks the anchored transform against Manim.
`ui/test_acceptance_p2e.py` turns one split equation into another through the
timeline menu (scrub = play, export = editor); `core/test_matching_tex.py`
checks the keyed matching against hand-built Manim.
`ui/test_acceptance_p2d.py` puts a real code layer under an equation through
the UI (random scrubbing equals playback, export equals the editor) and checks
that a project with untrusted code runs nothing. Tests never touch your trusted
code store (`MANIM_STUDIO_TRUST_FILE` points at a temporary file) and render no
code layers unless a test opts in (`MANIM_STUDIO_CODE=0` by default).
`ui/test_curve_editor.py` rechecks every fitted ease against Manim;
`core/test_part_layers.py` checks frames of objects with parts against the same
animations played on the glyphs by hand.

`ui/test_export_dialog.py` holds the S4 acceptance test (export while editing;
the video shows the scene as it was when Export was pressed), and
`ui/test_export_job.py` runs the real renderer (progress before exit, cancel,
errors).

`ui/test_acceptance_s3.py` is the S3 acceptance test: move an object on the
canvas with real mouse events, undo, redo; then animate it with the stopwatch.

`ui/test_acceptance_s2.py` is the S2 acceptance test: File > New, add a
MathTex, type an equation, add a Write clip from the timeline menu, save and
render — through the real widgets and the real worker.

Editor windows in tests build synchronously: `conftest.py` sets
`MANIM_STUDIO_WORKER=0`. The worker's own behaviour is tested in
`ui/test_worker_process.py` (lifecycle rules with tiny stand-in programs, then
one shared real worker) and its effect on edits in `ui/test_build_service.py`
with a deterministic fake.

## Markers

| marker | meaning | skip with |
|---|---|---|
| `latex` | needs a LaTeX install; skipped automatically when `latex` is missing | `-m "not latex"` |
| `ui` | needs Qt; runs with `QT_QPA_PLATFORM=offscreen` | `-m "not ui"` |

## What the core tests prove

The central contract (ADR 0002): **a frame is a pure function of (project, t)
and equals Manim's own sequential play loop.** The helpers in `support.py` make
that easy to state:

- `sequential_reference(kind, spec)` — frames exactly as `Scene.play` makes them;
- `render_in_order(project, order, fresh_each_frame)` — frames from the evaluator
  in any order;
- `assert_frames_equal` / `assert_evaluators_agree` — pixel comparison with a
  tolerance of 1 level (anti-aliasing rounding).

## Property tests

`core/test_properties.py` generates valid projects from fixed seeds and checks
the two contracts every project must meet. When one fails, the message names
the seed; reproduce it with `random_project(random.Random(seed))`. If you add a
feature, extend the generator so the feature appears in generated projects —
check that it does (the generator once produced no morphs at all).

## Write the failing test first

For bugs, write the test, watch it fail for the right reason, then fix. For
tests that guard a subtle property (purity, caching), also check the test fails
against the old code — a test that passes on the bug guards nothing.

## Writing a test

- Name the ADR a test protects in its module or test docstring.
- Compare pixels, not internal state, when checking rendering behaviour.
- For any new cache or edit path: render after the edit and compare with a
  freshly built `Evaluator` (`assert_evaluators_agree`).
- Keep canvases small (`support.CANVAS` is 320×180, 15 frames) — the whole suite
  should stay under ~15 s.
- Qt tests take the session `qt_app` fixture; never create your own
  `QApplication` (Qt allows one per process).

## Benchmarks

Benchmarks are not tests: run `benchmarks/bench_preview.py` when a change touches
the per-frame path, and log results that inform a decision in
[../logs/benchmarks.md](../logs/benchmarks.md).
