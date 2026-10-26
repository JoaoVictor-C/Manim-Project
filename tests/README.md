# Tests

The pytest suite. The full guide - what each area covers, the acceptance tests, mutation
checks - is [docs/dev/testing.md](../docs/dev/testing.md); this page is the quick reference.

## Run

```bash
uv run pytest -m "not slow"                       # the quick loop (no real subprocesses)
uv run pytest                                     # everything, in parallel (up to 8 workers)
uv run pytest -n 0 -s tests/core/editing/test_edits.py    # one file, one worker: for pdb, print, -s
uv run pytest -m "not latex and not ui"           # without LaTeX or Qt
```

`uv run X` can be replaced by `.venv/Scripts/python -m X` when uv cannot find the interpreter.
Coverage: `uv run pytest --cov=manim_studio --cov-report=term-missing`.

## Layout

| path | what is here |
|---|---|
| `conftest.py` | session setup: per-worker Manim caches, LaTeX discovery and auto-skip, the shared `qt_app`, a fresh settings file per test, and every user folder redirected (plugins, logs, trust store, recovery, library); no build worker, preview process, code runner or sound unless a test opts in |
| `support.py` | shared constants (`CANVAS`, `SQUARE`, `TEXT`...) and frame helpers: a frame must equal Manim's own sequential playback |
| `qt_support.py` | Qt test helpers such as `FakeWorker` |
| `core/<package>/` | the model and the engine, no Qt, one folder per package of `src/manim_studio/core/` (`model`, `editing`, `engine`, `sound`, `code`, `assist`, `exchange`); `core/features/` holds the behaviour tests that run a whole project through the evaluator and belong to no single module (`euler_example.json` and `golden_readable_export.txt` are fixtures, next to the export tests) |
| `render/` | Qt paths vs Cairo, hit-testing, video export and the CLI, render options, preset thumbnails |
| `ui/<package>/` | the editor through the real `MainWindow`, offscreen, one folder per package of `src/manim_studio/ui/`; the tests of the whole window (main window, golden path, layout checks) stay at the top of `ui/` |
| `acceptance/` | the slice-by-slice walks a user would do, end to end (`test_acceptance_*.py`) |
| `processes/` | the helper processes: code runner, worker messages, scene recorder, chapters, helper check |
| `test_*.py` (top level) | the layering (`test_architecture.py`), logging, the version, the plugin API, the import command, documentation links |

## Naming

- `test_<module or feature>.py` for a module's or a feature's tests; the UI half of a feature is
  `ui/<package>/test_<feature>_ui.py` when its pure rules have a `core/` file.
- `acceptance/test_acceptance_<slice>.py` walks a slice's feature the way a user does (`p2a` ... `p7_3`,
  `s2`, `s3`, `v1`); `ui/test_golden_path.py` is the end-to-end walk of a typical animation.
- A test goes in the folder of the package it tests; a new package folder is a new test folder.
- Test names are sentences about behaviour: `test_rows_come_from_the_menus_with_their_paths`.

## Markers

| marker | meaning |
|---|---|
| `slow` | starts real processes (build worker, renderer, code runner): seconds each |
| `ui` | needs Qt (runs offscreen); an exception raised in a Qt slot fails the test |
| `latex` | needs a LaTeX installation; skipped automatically when `latex` is not found |

Markers are declared in `pyproject.toml` (`[tool.pytest.ini_options]`). No test may move
Manim's cache at import time, and none reads the developer's own preferences, plugins or
library.
