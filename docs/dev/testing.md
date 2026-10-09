# Testing

```bash
uv run pytest
```

## Layout

```
tests/
├── conftest.py        Manim cache + LaTeX setup, session `qt_app`, auto-skip of `latex`
├── support.py         shared constants (CANVAS, SQUARE, TEXT, …) and frame helpers
├── core/              evaluator contract: random access, transforms, invalidation
├── render/            Qt paths vs Cairo fidelity
└── ui/                editor smoke tests (offscreen Qt)
```

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
