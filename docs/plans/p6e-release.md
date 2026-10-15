# P6e — Release preparation

- **Status:** In progress
- **Date:** 2026-10-15
- **Decided in:** [decision session 41](../logs/decision-sessions.md) (Terza, `fast`, confidence 0.91)
- **Evidence:** B62 in [../logs/benchmarks.md](../logs/benchmarks.md)
- **ADR:** [0045 — Releases: a wheel, a release check, nothing published by itself](../adr/0045-releases.md)

## Goal

**Done when** a proposed 0.2.0 is ready on this machine - wheel, sdist, release notes,
third-party notices - and has passed the release check, and the user has been asked
about the version, a tag, a push and a publication. Nothing leaves the machine before
the user says so.

## Steps

| step | content | acceptance |
|---|---|---|
| ✅ P6e.1 | `manim-studio --version` (the version comes from pyproject through the package metadata); `scripts/release_check.py` (build, a fresh venv with only the wheel, `--version`, a render of a committed example with its frames counted, the editor offscreen with its pages and presets, every user folder redirected); `THIRD-PARTY-NOTICES.md` | the check passes on the current tree (B62) |
| P6e.2 | after P6d: version 0.2.0 in pyproject (proposed), the CHANGELOG's `[0.2.0] - unreleased` heading with a summary, release notes `docs/releases/0.2.0.md` (what is new, requirements, `uv tool install <wheel>`, upgrade notes, known limits), the release check again | the notes describe the final feature set; the check passes on 0.2.0 |
| P6e.3 | ask the user: the version, a local tag, any push, any publication | the user's answer |

## Not in this release

- A standalone Windows bundle (PyInstaller or similar): Cairo, Pango and FFmpeg would be
  bundled and LaTeX would still be needed separately; worth it only after the wheel.
