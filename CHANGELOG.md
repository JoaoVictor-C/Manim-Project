# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/) (0.x: anything may change).

## [Unreleased]

### Added
- MIT license.
- Project structure: `cli.py`, `logging_config.py`, `ui/` (canvas split from main window),
  `benchmarks/`, tests split into `core/`, `render/`, `ui/` with shared `support.py`.
- Logging: console (`-v`/`-vv`) and per-user rotating log file (ADR 0011).
- Documentation: architecture, project format, roadmap, ADRs 0001–0012,
  developer setup/coding standards/testing guides, benchmark and decision-session logs,
  `CONTRIBUTING.md`, `.editorconfig`.
- Test: Qt paths vs Cairo fidelity (`tests/render/test_qt_paths.py`).
- Test: idle checkpoint precompute drains (`test_missing_checkpoints_drain`).
- Tooling: ruff (lint + format), pytest markers `latex` and `ui`, dev dependency group.

- Validation: unknown clip kinds, non-positive durations, negative starts,
  morph target rules, clips after a morph, duplicate layer ids, unsupported
  schema versions, bezier x outside [0, 1] are rejected on load.
- Tests: 45 → 200 (images, schema, adapter, easing, lifetime, export, CLI,
  logging, editor behaviour, seeded property tests); coverage 77 % → 93 %; `pytest-cov`.

- S1 timeline plan (`docs/plans/s1-timeline.md`), proposed ADRs 0013–0014, benchmarks B10–B14.

### Changed
- Clip-kind metadata moved from the adapter into `schema.CLIP_KIND_INFO`, so
  documents validate without importing Manim; `adapter.ANIMATION_CLASSES` maps kinds to Manim.
- `pillow<13` pinned: Manim 0.22 uses an argument Pillow 13 removes.
- Manim pinned to exactly 0.22.0 (ADR 0003).
- `render/qt_preview.py` renamed to `render/qt_paths.py` (it serves overlays and
  hit-testing, not preview content — ADR 0006).
- `DESIGN.md` replaced by `docs/architecture.md`, `docs/roadmap.md` and the ADRs.
- `zip()` calls on equal-length sequences are now `strict=True`.

### Fixed
- Image layers rendered wrong opacity whenever they moved or had an opacity
  keyframe: the scratch copy shared the source's pixel array and used
  `ImageMobject.set_opacity`, which overwrites alpha in place.
- A clip after a morph on the same layer crashed the evaluator (`ValueError`);
  such projects are now rejected on load.
- A clip outside a layer's explicit lifetime made the layer visible again.
- `manim-studio render` printed a traceback for missing or invalid project files;
  it now prints one error line and exits with code 2.
- Qt tests crashed the run when a `QGuiApplication` was created before a
  `QApplication`; all Qt tests now share one session `qt_app`.
- Author name encoding in `pyproject.toml`.

## [0.1.0] - 2026-10-09

### Added
- Project schema (layers, clips, keyframes, easing incl. cubic-bezier).
- Manim adapter with 16 clip kinds and 12 mobject types; Wiggle pivot patch.
- Random-access evaluator: checkpoints, clip-owned working mobjects, numpy layer
  transforms, world-space morph hand-offs, incremental invalidation with edit classes.
- Cairo export to MP4 via PyAV; `manim-studio render`.
- S0 previewer: `manim-studio edit` with scrub, play, frame step, idle checkpoint
  precompute, `gc.freeze()`, half-resolution playback.
- Example project `examples/euler.json`, preview benchmark.
