# Testing

```bash
uv run pytest
```

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
(93 % at the last count; the suite runs in about 60 s, a third of it real
subprocesses — the build worker and the renderer — and LaTeX).

`ui/test_acceptance_p2a.py`, `ui/test_acceptance_p2b.py` and
`ui/test_acceptance_p2c.py` are the Phase 2 acceptance tests (scale/rotate and
auto-key; keyframes on the timeline and the curve editor; terms of an equation
as part layers, with the exported video checked against hand-built Manim).
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
