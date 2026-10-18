# Contributing to Manim Studio

Thanks for helping. This guide is the workflow; the technical rules are in
[docs/dev/coding-standards.md](docs/dev/coding-standards.md), the map of the code in
[docs/architecture.md](docs/architecture.md), and the reasons behind the design in the
[ADRs](docs/adr/README.md).

## 1. Set up

Follow [docs/dev/setup.md](docs/dev/setup.md) (Windows users: read its troubleshooting section
first). Then check that everything works:

```bash
uv sync
uv run pytest -m "not slow"
uv run manim-studio edit examples/euler.json
```

If `uv run` cannot find the interpreter (a non-ASCII user folder on Windows), call the
environment's Python directly: `.venv/Scripts/python -m pytest` - every `uv run X` below has an
equivalent `.venv/Scripts/python -m X`.

## 2. Pick or describe the work

- Work is planned in **slices**: small steps that each end with something runnable and its tests.
  The phases and their plans are in [docs/roadmap.md](docs/roadmap.md) and
  [docs/plans/](docs/plans/).
- For anything that changes a rule in an ADR, adds a dependency, a process or a file format, or
  is costly to reverse, write a **Proposed ADR first** ([docs/adr/README.md](docs/adr/README.md)).

## 3. Branch per slice

Branch from `master`, one branch per slice:

| prefix | for |
|---|---|
| `feat/` | new behaviour (`feat/p10-1-python-object`, `feat/right-triangle`) |
| `fix/` | bug fixes |
| `perf/` | performance work (with a benchmark entry) |
| `refactor/` | no behaviour change |
| `test/` | tests only |
| `docs/` | documentation only |
| `chore/` | tooling, configuration, repository hygiene |

Merge into `master` with a merge commit that names the slice
(`Merge branch 'feat/python-matrix' (Python object templates: Matrix)`).

## 4. Tests first

- Write the test that shows the behaviour (or the bug) before the code, then make it pass. UI
  behaviour is tested through the real `MainWindow` offscreen; pure rules (geometry, timing,
  validation) live in Qt-free modules with their own fast tests.
- Each user-visible slice gets an acceptance test that walks the feature the way a user does
  (`tests/ui/test_acceptance_*.py`, `tests/ui/test_golden_path.py`).
- **Mutation check:** once the tests pass, break each guard you wrote (`if x:` to `if False:`,
  drop a line, swap a bound) and confirm a test fails. Earlier slices keep a small script per
  slice that applies each mutant, runs the named tests and restores the file; such scripts are
  scratch and live under `.cache/` (not committed). Note the result ("all 38 mutants are
  killed") in the slice's plan or in [docs/dev/testing.md](docs/dev/testing.md).
- Tests that start real processes are marked `slow`; LaTeX-dependent ones `latex`; Qt ones `ui`.
  See [docs/dev/testing.md](docs/dev/testing.md) and [tests/README.md](tests/README.md).

## 5. Code

Respect the architecture rules ([docs/architecture.md](docs/architecture.md#rules-checked-in-review-and-by-tests)):
no Qt in `core/`, Manim's API only in `core/adapter.py`, never mutate evaluator outputs, every
change through a `core/edits.py` function and `Evaluator.apply(edit)`. Log with
`get_logger(__name__)`; no stray `print`.

## 6. Check before you commit

```bash
uv run ruff format src tests benchmarks scripts
uv run ruff check src tests benchmarks scripts
uv run pytest -m "not slow"
uv run pytest
uv run python scripts/check_docs.py
```

The full suite (`uv run pytest`, parallel) runs the slow tests too. If you touched the per-frame
path (evaluator, rendering, playback), run the relevant benchmark and compare against
[docs/logs/benchmarks.md](docs/logs/benchmarks.md):

```bash
uv run python benchmarks/bench_preview.py
```

If you added or changed a menu shortcut or a gesture, regenerate the shortcuts page:

```bash
uv run python scripts/gen_shortcuts.py -o docs/guide/shortcuts.md
```

## 7. Commit

[Conventional Commits](https://www.conventionalcommits.org/), with the *why* in the body:

```text
feat(timeline): drag clips to change their start time

Clip drags call Evaluator.invalidate(..., {layer}) per mouse move (ADR 0008).
```

Types: `feat`, `fix`, `perf`, `refactor`, `test`, `docs`, `style`, `build`, `chore`.
Common scopes: `core`, `adapter`, `evaluator`, `schema`, `render`, `ui`, `timeline`, `cli`,
`docs`, `adr`, or the slice (`p10`). Commit early and often.

## 8. Records: ADRs, benchmarks, decisions, changelog

These are **append-only history** - add to them, never rewrite them:

- **ADRs** ([docs/adr/](docs/adr/README.md)): copy [the template](docs/adr/template.md) to the next
  free number, status *Proposed*, then *Accepted* with an entry in the index. To change a decision,
  write a new ADR that supersedes the old one (an *amendment* section is used for small additions).
- **Benchmarks** ([docs/logs/benchmarks.md](docs/logs/benchmarks.md)): when a measurement informs a
  decision, append it with the next id (B71, B72, ...), the date, the script and the machine if it
  differs. The script goes in [benchmarks/](benchmarks/README.md).
- **Decision sessions** ([docs/logs/decision-sessions.md](docs/logs/decision-sessions.md)): the
  structured reasoning behind larger choices, numbered.
- **Plans** ([docs/plans/](docs/plans/)): one per slice; mark items done as they land.
- **Changelog** ([CHANGELOG.md](CHANGELOG.md)): a bullet under **[Unreleased]** for every
  user-visible change. Release notes per version go in [docs/releases/](docs/releases/0.3.0.md).

## 9. How to add...

### An object type

1. `core/adapter.py`: the Manim class in `MOBJECT_TYPES` (or a builder in `build_mobject` for an
   object that is not one Manim class, like `RightTriangle`), its parameters in `MOBJECT_PARAMS`
   (each `Param` with a label and limits), and its place in `LIBRARY` (with a friendlier name in
   `LIBRARY_LABELS` if needed).
2. `core/library.py`: add it to `_SHAPES` if themes should colour it like a shape.
3. `core/python_export.py`: how the readable export writes it, if it is not a plain Manim class.
4. Tests: `tests/core/test_registry.py` already checks that every type builds and every exposed
   parameter has an effect; add a test file for its own behaviour (see
   `tests/core/test_right_triangle.py`).
5. `docs/project-format.md`, the user guide ([objects](docs/guide/objects.md)) and the changelog.

For something users should add without changing Manim Studio, prefer a plugin
(`examples/plugins/pendulum.py`) or a Python object.

### A clip kind

Add it to `schema.CLIP_KIND_INFO` (category, introducer/remover, vector-only, allowed types) and
`adapter.ANIMATION_CLASSES`; options go through the clip parameter registry (ADR 0022). It must pass
the random-access tests (`tests/core/test_random_access.py`, `tests/core/test_clip_kinds.py`:
scrubbing equals Manim's own sequential playback). List any deliberate difference from vanilla
Manim in [docs/deviations.md](docs/deviations.md).

### A built-in preset, theme or template

Built-in library items are JSON files in `src/manim_studio/library/`, generated by
`examples/build_library.py` - edit the lists there and run it:

```bash
uv run python examples/build_library.py
```

(On Windows it writes CRLF line endings; git stores them as LF, so unchanged items show no diff
once staged.)

Users save their own with **Animate > Save Animation as Preset...** and
**Save Object as Template...** (ADR 0039).

### A menu action

In `ui/main_window.py` (or the panel that owns it): a `QAction` with a mnemonic, a shortcut if it
deserves one, and **a tooltip** - `tests/ui/test_layout_checks.py` fails for a menu item without one
(only `SELF_EXPLANATORY` and the `DATA_MENUS` are exempt); call `setToolTipsVisible(True)` on a new
menu. A shortcut appears in Help > Keyboard Shortcuts by itself; regenerate
`docs/guide/shortcuts.md` (section 6). Test the action through the real window.

### A workspace page

Subclass `Page` in `ui/pages/` (`build()` once, `place(shared)` each time it is shown,
`on_show` / `on_hide`), register it in `MainWindow.__init__` (the order gives its `Shift+number`),
and add it to the pages parametrized in `tests/ui/test_layout_checks.py` so it is checked for
squeezed and clipped widgets at a small window. See ADR 0041.

## Pull request checklist

- [ ] Tests added or updated; `uv run pytest` passes
- [ ] `ruff format` and `ruff check` are clean; `scripts/check_docs.py` passes
- [ ] `CHANGELOG.md` updated under **[Unreleased]**
- [ ] User guide and `docs/project-format.md` updated if behaviour or the file format changed
- [ ] ADR added if a decision changed; benchmark entry if performance justified the change
- [ ] Deviations from vanilla Manim listed in `docs/deviations.md`

## Reporting bugs

Include the project JSON (or a minimal one), what you expected, what happened, and the log
(**Help > Open Log Folder**: `%LOCALAPPDATA%\ManimStudio\logs\manim-studio.log` on Windows,
`~/.local/state/manim-studio/logs/` on Linux). `manim-studio -vv edit` adds debug output to the
console.
