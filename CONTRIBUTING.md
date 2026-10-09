# Contributing to Manim Studio

Thanks for helping. This guide covers the workflow; the technical rules live in
[docs/dev/coding-standards.md](docs/dev/coding-standards.md) and the reasons
behind the design in [docs/adr/](docs/adr/README.md).

## 1. Set up

Follow [docs/dev/setup.md](docs/dev/setup.md), then check everything works:

```bash
uv sync
```

```bash
uv run pytest
```

## 2. Pick or describe the work

- Roadmap slices are in [docs/roadmap.md](docs/roadmap.md).
- For anything that changes a rule in an ADR, or is costly to reverse, write a
  **Proposed ADR first** ([docs/adr/README.md](docs/adr/README.md)).

## 3. Branch

Branch from `master`:

| prefix | for |
|---|---|
| `feat/` | new behaviour (`feat/s1-timeline`) |
| `fix/` | bug fixes |
| `docs/` | documentation only |
| `refactor/` | no behaviour change |
| `test/` | tests only |
| `perf/` | performance work (include a benchmark entry) |

## 4. Code

- Keep slices small and runnable; each ends with tests.
- Respect the architecture rules: no Qt in `core/`, Manim classes only in
  `core/adapter.py`, never mutate evaluator outputs, every edit goes through
  `Evaluator.invalidate()` with the right edit class.
- Log with `get_logger(__name__)`; no stray `print`.

## 5. Check before you push

```bash
uv run ruff format src tests benchmarks
```

```bash
uv run ruff check src tests benchmarks
```

```bash
uv run pytest
```

If you touched the per-frame path (evaluator, rendering, playback), also run the
benchmark and compare against [docs/logs/benchmarks.md](docs/logs/benchmarks.md):

```bash
uv run python benchmarks/bench_preview.py
```

## 6. Commit

[Conventional Commits](https://www.conventionalcommits.org/):

```
feat(timeline): drag clips to change their start time

Clip drags call Evaluator.invalidate(..., {layer}) per mouse move (ADR 0008).
```

Types: `feat`, `fix`, `docs`, `refactor`, `test`, `perf`, `build`, `chore`.
Scopes: `core`, `adapter`, `evaluator`, `schema`, `render`, `ui`, `timeline`,
`cli`, `docs`, `adr`.

## 7. Pull request checklist

- [ ] Tests added or updated; `uv run pytest` passes
- [ ] `ruff format` and `ruff check` are clean
- [ ] `CHANGELOG.md` updated under **Unreleased**
- [ ] Docs updated if behaviour or the file format changed (`docs/project-format.md`)
- [ ] ADR added/updated if a decision changed
- [ ] Benchmark entry added if the change was justified by performance
- [ ] Deviations from vanilla Manim listed in `docs/deviations.md`

## Reporting bugs

Include the project JSON (or a minimal one), what you expected, what happened,
and the log file from `%LOCALAPPDATA%\ManimStudio\logs\manim-studio.log`
(Windows) or `~/.local/state/manim-studio/logs/`. Run with `-vv` for debug output.
