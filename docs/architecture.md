# Architecture

Manim Studio is a desktop editor where you animate visually — layers, a timeline
of clips, keyframes — and **Manim Community Edition** does the rendering. This
page is the map; the *why* behind each rule is in the [ADRs](adr/README.md).

## The idea in one paragraph

Manim's `Scene.play()` is just a loop: `begin()`, then `interpolate(t / run_time)`
every frame, then `finish()`. The editor runs that loop itself, driven by the
timeline, so it can compute **any frame at any time in any order** from a JSON
document. Preview and export use the same evaluator and the same Manim renderer,
so what you see is what you export ([ADR 0002](adr/0002-editor-owns-manims-clock.md),
[ADR 0006](adr/0006-preview-renders-with-manims-cairo-camera.md)).

## Modules

```
src/manim_studio/
├── cli.py               entry point: `manim-studio render | edit`
├── worker.py            build worker process: warms Manim's text cache (ADR 0015)
├── code_runner.py       renders a code layer's Scene into the frame cache (single-use process)
├── logging_config.py    console + rotating file logging (ADR 0011)
├── core/                no Qt imports allowed here
│   ├── schema.py        project document (pydantic): Project, Layer, Clip, Keyframe
│   ├── edits.py         edits → new validated snapshot + edit kind (ADR 0013, 0014)
│   ├── parts.py         part layers: keys → exact TeX spans, markers, split terms (ADR 0012)
│   ├── code_cache.py    code layer frames: cropped premultiplied zlib frames, eviction (ADR 0019)
│   ├── code_frame.py    a cached frame as a mobject; painted by Cairo, hit by alpha (ADR 0019)
│   ├── trust.py         which code may run: hashes in a per-user store (ADR 0019)
│   ├── warm.py          which edits build cold text objects: warm keys, gate (ADR 0015)
│   ├── adapter.py       the ONLY module that knows Manim classes: builders,
│   │                    clip registry / allow-list, easing, patches (ADR 0003, 0007)
│   └── evaluator.py     frame(t), checkpoints, keyframes, invalidate (ADR 0002, 0008)
├── render/
│   ├── cairo_export.py  Manim Cairo camera → frames → PyAV/libx264
│   ├── qt_paths.py      Manim geometry → QPainterPath (outlines)
│   └── hit_test.py      which layers are under a canvas point (ADR 0016)
└── ui/                  PySide6
    ├── document.py      current snapshot, QUndoStack, drag previews, `changed` (ADR 0014)
    ├── build_service.py every panel edit: apply now, or after the worker warmed it (ADR 0015)
    ├── code_render.py   keeps code layers rendered with warm single-use spares (ADR 0019)
    ├── selection.py     the one selection shared by every view (ADR 0016)
    ├── canvas_tools.py  click to select; move, scale, rotate, nudge; stopwatch rule (ADR 0016, 0018)
    ├── gizmo.py         handle geometry: oriented box, scale/angle from drags, pivot snaps (pure)
    ├── curve_editor.py  easing curve editor: bezier handles, presets, fitted named eases
    ├── export_job.py    one export in a `manim-studio render` process (ADR 0017)
    ├── export_dialog.py File > Export Video: progress, cancel, open folder
    ├── worker_process.py QProcess client for worker.py: queue, timeout, restart
    ├── timeline/
    │   ├── model.py     pure geometry: TimeScale, snapping, clamping (no Qt)
    │   └── view.py      QGraphicsView: rows, clip bars, ruler, playhead, drags
    ├── main_window.py   menus, transport, playback & idle scheduling (ADR 0009)
    └── canvas.py        letterboxed Cairo frame at the playhead
```

### Dependency rules

```
ui ──► render ──► core.evaluator ──► core.adapter ──► manim
 │                     │                  │
 └──────────► core.schema ◄───────────────┘
```

- `core` never imports `ui` or Qt. It must stay usable headless (CLI, tests, export workers).
- Only `core/adapter.py` names Manim mobject/animation classes or touches
  animation internals. `evaluator` may use the generic `Mobject` API
  (`copy`, `get_family`, `points`, rgba arrays).
- `render` may import `core`; `ui` may import everything.
- Everything logs through `logging_config.get_logger(__name__)`.

## Data flow

```
project.json ─► Project (schema) ─► Evaluator.frame(t) ─► [Mobject …] ─┬─► Cairo camera ─► QImage (canvas)
                                         ▲                             ├─► Cairo camera ─► PyAV (export)
UI command ─► edited Project ─► invalidate(layer_ids, edit class)      └─► qt_paths (selection, hit-test)
```

### Processes

The editor runs one helper process, the **build worker** (`python -m
manim_studio.worker`). New Text/Tex/MathTex objects take 0.5–1.3 s to build the
first time and cannot be built in a thread without freezing the UI (B17, B18);
the worker builds them, Manim's disk cache keeps the result, and the edit is
committed once the editor's own build will be a cache hit (ADR 0015).
Exports run as a second process (`manim-studio render --progress json`), so the
editor keeps working while a video renders (ADR 0017).

## Core concepts

| concept | meaning | where |
|---|---|---|
| Layer | one object, lifetime, keyframe tracks, one clip lane; list order = z-order | ADR 0004 |
| Clip | a Manim animation on a layer's lane; categories content / emphasis / morph | ADR 0004, 0005 |
| Keyframes | position, scale, rotation, opacity applied after clips | ADR 0004 |
| Checkpoint | cached state of a layer after a clip | ADR 0002 |
| Edit kind | timing / transform / clip / spec, computed by `core/edits.py` — decides what `Evaluator.apply` drops | ADR 0008, 0013 |
| Allow-list | clip kinds × mobject types verified random-access-safe | ADR 0007 |
| Warm key | disk-cache identity of a text object; an edit building a cold key waits for the worker | ADR 0015 |

The document format is specified in [project-format.md](project-format.md).

## Performance budget

30 fps playback = 33 ms per frame for evaluate + render. Current numbers and
how they were measured: [logs/benchmarks.md](logs/benchmarks.md).

## Known limitations

- Flat layers only; parts of objects cannot be animated separately yet (ADR 0012, proposed).
- No updaters / `TracedPath` / 3D.
- `qt_paths` does not draw `ImageMobject` (only needed for hit-testing).
- Deliberate differences from vanilla Manim: [deviations.md](deviations.md).
