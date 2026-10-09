# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/) (0.x: anything may change).

## [Unreleased]

### Added
- `core/edits.py` (S1.1): `move_clip`, `trim_clip`, `update_clip`, `update_layer`
  return validated snapshots plus an edit kind computed by diffing; `Evaluator.apply(edit)`.
- Edit kind **timing** keeps every evaluator cache; morph animations are reused
  while their baked start/end transforms are unchanged (ADR 0013). Clip drags on
  the stress scene: 94 ms → 15–22 ms per step (B15).
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

- `ui/document.py` (S1.2): the open project as immutable snapshots with a
  `QUndoStack`; drags preview freely and record one undo step (Escape cancels).
  Edit menu with Undo/Redo; window title marks unsaved changes.

- `ui/timeline/model.py` (S1.3): pure timeline geometry — time↔x scale with zoom
  about the cursor, frame quantisation, 8 px snapping (frames, clip edges,
  playhead, 0, end), move/trim clamping that never produces an overlap.

- Timeline (S1.4–S1.6): under the canvas, one row per layer with its lifetime band
  and clip bars coloured by category; ruler scrubbing; drag a bar to move it or an
  edge to trim it (snaps to frames, clip edges and the playhead; Alt = frames only;
  Escape cancels); Ctrl+wheel zooms; drags are coalesced and record one undo step.
  Measured 19–24 ms per drag step in the editor (B16).
- Lifetime inference is a pure function (`schema.infer_lifetime`, `Project.lifetime`)
  shared by the evaluator and the timeline.

- S2 panels plan (`docs/plans/s2-panels.md`), proposed ADR 0015 (build worker,
  warm-then-commit), benchmarks B17–B20.
- Structural edits (S2.1): `add_layer` (id `<type>-<n>`, on top), `remove_layer`
  (also removes the morph clip into the deleted layer), `move_layer` (z-order, a
  cache-keeping timing edit), `add_clip`, `remove_clip`, `new_layer_id`,
  `new_clip_id`. The random-edit property test now mixes them in.
- Validation: duplicate clip ids on a lane and vector-only clip kinds on image
  layers are rejected.
- `Document.apply` records nothing for an edit that changes nothing.
- Build worker (S2.2, ADR 0015): `python -m manim_studio.worker` warms Manim's
  disk cache for Text/Tex/MathTex in another process; `ui/worker_process.py`
  queues requests during startup, restarts on a 20 s timeout or a crash, and
  falls back to synchronous builds if it cannot start (`MANIM_STUDIO_WORKER=0`
  disables it). LaTeX errors are reported as LaTeX's own message.
- `core/warm.py` and `ui/build_service.py`: panel edits are operations; one that
  builds a cold text object waits for the worker and is then re-run on the
  current snapshot, so edits and undos made meanwhile are kept; latest wins per
  field; a failed build commits nothing; nothing commits mid-drag.
- Object registry (S2.3): `adapter.MOBJECT_PARAMS` lists the constructor params
  each type exposes (kind, default, range, choices), `adapter.LIBRARY` the
  library sections, `adapter.default_spec()` new objects; 2D `point` params are
  lifted to 3D for Manim. A test proves every exposed param changes the object.
  The editor pre-warms the library's text defaults at startup.
- Layers dock (S2.4): the layer list front-to-back, an Add menu with the object
  library, Delete (with the morph cascade), Up/Down and drag-to-reorder for
  z-order, double-click to rename; each action is one undo step through the
  build service, and a new MathTex appears when the worker has built it.
- Properties dock (S2.5): for a layer — name, the object's params generated from
  the registry, fill/stroke style, position/scale/rotation/opacity (disabled when
  keyframed), lifetime in/out ("Auto" = inferred); for a clip — animation (same
  family only), start, duration, easing (Manim rate functions and CSS-style
  curves), morph target. One undo step per finished field; refused values
  revert with the reason in the status bar; new LaTeX shows in italics until
  the worker has built it. Selecting a layer or a timeline clip shows it.
- `adapter.EASE_NAMES`, `adapter.BEZIER_PRESETS`.
- Keyframe edits (S3.1, ADR 0016): `edits.set_key` (frame-quantized; replaces a
  key within half a frame; new keys inherit the previous ease unless it does
  not end at 1) and `edits.clear_track` (keeps the value at a time as the base);
  `Evaluator.frame_layers(t)` names the layer of each drawn object;
  `evaluator.layer_transform`; `Document.apply(..., merge_key, merge)` merges
  repeated edits (an arrow key held down) into one undo step.
- Hit-testing (S3.2, `render/hit_test.py`): all layers under a point,
  front-most first; only what is drawn counts (alpha > 0.02); text by its box,
  images by their rectangle, shapes by fill (nonzero winding) or within 4 px of
  their stroke. 0.8 ms per click on the stress scene.
- Shared selection (S3.3, `ui/selection.py`): one layer/clip selection for the
  canvas, Layers panel, timeline and Properties; deleted clips fall back to
  their layer, deleted layers clear it.
- Canvas editing (S3.4-S3.5, `ui/canvas_tools.py`): click selects the
  front-most object (Alt+click: the one behind), the selection is outlined with
  its box and anchor; drag moves it (one undo step, Shift = one axis, Escape
  cancels); arrow keys nudge 1 px / 10 px with Shift, a held key is one undo
  step. Layers with position keyframes get a key at the playhead (snapped to the
  frame); others get their base position changed. Morphing layers cannot be
  dragged while their morph plays.
- Stopwatch toggle (S3.6): Properties > Transform > Keyframes turns position
  keyframes on (one key at the playhead holding the current value) or off
  (keeps the value at the playhead as the base). Base fields of a keyframed
  property are disabled live.
- `manim-studio render --cache-dir DIR --progress json` (S4.1): choose Manim's
  cache, and report progress as flushed JSON lines for the editor. Exports write
  `<name>.partial.mp4` and replace the output only when complete, so a failed or
  cancelled export never damages a previous video; a locked output (open in a
  player) is saved as `<name> (2).mp4` with a warning (ADR 0017).
- `ui/export_job.py` (S4.2): one export in a separate process — snapshot to a
  JSON file in the cache, live progress, `finished(path, warning)` /
  `failed(message)`, `cancel()` that leaves no partial file. A folder given as
  the output is now a clear error instead of a misleading "in use" rename.
- P2a transform gizmos plan (`docs/plans/p2a-gizmos.md`), proposed ADR 0018.
- Phase 1 complete: `tests/ui/test_acceptance_v1.py` writes an equation, moves
  it, morphs it into a second equation, fades it out and exports MP4 through
  the UI alone.
- Export dialog (S4.3-S4.4): File > Export Video... (Ctrl+E) exports the scene
  as it is (saved or not) in the background — "Starting...", frame progress and
  time left, Cancel, Open folder; quitting during an export asks first. The UI
  stays responsive (B26: p99 14 ms timer lateness).
- S4 export plan (`docs/plans/s4-export.md`), proposed ADR 0017, benchmark B25.
- S3 acceptance (`tests/ui/test_acceptance_s3.py`): move an object on the
  canvas, undo, redo, and animate it by moving it with keyframes on; benchmark
  B24 (`benchmarks/bench_canvas_drag.py`): 18.5 ms per drag step in the window.
- S3 canvas interaction plan (`docs/plans/s3-canvas.md`), proposed ADR 0016,
  benchmarks B21–B23 (`benchmarks/bench_canvas_interaction.py`).
- New, Open and closing the window ask before discarding unsaved changes
  (Save / Discard / Cancel).
- File > New (S2.7). S2 acceptance: a MathTex layer with a Write clip is built
  from an empty project through the panels and the timeline alone.
- Timeline clips (S2.6): right-click a row to add a clip at that time (1 s,
  shortened to fit the gap; morphs pick a layer that is not yet a target; not
  offered after a morph), right-click a clip to delete it, Delete key removes
  the selected clip. Placement is the pure `timeline.model.place_new_clip`.
- `Document.dragFinished` signal; `adapter.cache_dir()`; `schema.TEXT_TYPES`, `schema.RASTER_TYPES`.

### Changed
- Timeline rows list the front-most layer first, matching the Layers panel.
- `Evaluator.invalidate(..., transform_only=...)` replaced by `invalidate(..., kind=...)` / `apply(edit)`.
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
