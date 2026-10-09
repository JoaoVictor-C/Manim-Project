# Coding standards

Ruff enforces formatting and most lint rules (`pyproject.toml`); this page covers
what a linter cannot.

## Style

- Python 3.13, `from __future__ import annotations` at the top of every module.
- Type hints on all public functions. Prefer concrete types over `Any`.
- Line length 110. Run `ruff format` before committing.
- Names: modules `snake_case`, classes `PascalCase`, private helpers `_leading_underscore`.
  Qt overrides keep Qt's camelCase (`paintEvent`).
- `zip()` always with `strict=True` when lengths must match (they almost always do).

## Comments and docstrings

- Each module starts with a docstring saying what it is responsible for.
- Comment *why*, not *what*: Manim quirks, measured reasons, ADR numbers.
  Example: `# measured: removes the gen-2 GC hitches during playback (ADR 0009)`.
- Cite the ADR when code enforces one of its rules.

## Architecture rules (checked in review)

1. `core/` never imports Qt or `ui/`.
2. Only `core/adapter.py` imports Manim mobject/animation classes or reaches into
   animation internals. Other modules use generic `Mobject` APIs.
3. A frame is a pure function of `(project, t)`. Never mutate a checkpoint, a
   base mobject, or anything returned by `Evaluator.frame()`.
4. Every UI edit goes through `Evaluator.invalidate()` with the right edit class
   (ADR 0008). When unsure, use the broader class.
5. New clip kinds are added to `CLIP_KINDS` and must pass the random-access
   tests; deviations from vanilla Manim go in `docs/deviations.md`.
6. Schema changes that rename or change meaning bump `SCHEMA_VERSION` and ship a
   migration; update `docs/project-format.md`.

## Errors and logging

- Use `log = get_logger(__name__)` from `manim_studio.logging_config`; no `print`
  outside the CLI's progress output.
- Catch exceptions only where you can do something useful (show a dialog, skip a
  frame); log them with `log.exception(...)`.
- Validation errors from user files are shown to the user, not swallowed.

## Performance

- The frame budget is 33 ms. Anything on the per-frame path needs a measurement;
  record it in `docs/logs/benchmarks.md` if it informs a decision.
- Avoid `Mobject.copy()` (a deepcopy) per frame — it was the dominant cost (B1).
