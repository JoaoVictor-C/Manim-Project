# 0045. Releases: a wheel, a release check, nothing published by itself

- **Status:** Accepted
- **Date:** 2026-10-15
- **Deciders:** João Victor

## Context

0.1.0 was declared in the changelog but never built or checked as a package. The editor
now reads data files at run time (the built-in presets, themes and templates), opens
five pages and starts helper processes, and its tests only ever ran from the source tree.

## Decision

- A release is a **wheel and an sdist** from `uv build`, installed with
  `uv tool install <wheel>` (or `pip`). LaTeX stays a stated requirement. No standalone
  bundle yet.
- The version lives only in `pyproject.toml`; the package reads it from its metadata
  (`manim_studio.__version__`) and `manim-studio --version` prints it with the Manim and
  Python versions.
- **`scripts/release_check.py`** must pass before a release: it builds into a work folder
  (the system temp folder by default, an ASCII path), makes a fresh Python 3.13 venv with
  only the wheel, checks `--version`, renders a committed example and counts its frames,
  and opens the editor offscreen from the installed package with every user folder
  redirected, checking its pages and built-in library.
- `THIRD-PARTY-NOTICES.md` lists the dependencies and their licenses.
- **Nothing is published by itself:** the version, a tag, a push, a PyPI upload or a
  GitHub release each wait for the user.

## Consequences

- After changing the version, `uv sync` refreshes the installed metadata (the version test
  compares the two).
- The release check takes about half a minute and needs network access only for
  packages missing from uv's cache.

## Evidence

- B62 in [../logs/benchmarks.md](../logs/benchmarks.md): every file under `src/` is in the
  wheel; the whole check passes in about 31 s.
- Design: [../logs/decision-sessions.md](../logs/decision-sessions.md), session 41.
- Plan: [../plans/p6e-release.md](../plans/p6e-release.md).
