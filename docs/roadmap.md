# Roadmap

Each slice ends with something runnable and its tests. Order decided in
[decision session 2](logs/decision-sessions.md).

## Phase 0 — core ✅ (2026-10-09)

- Project schema, Manim adapter, random-access evaluator with checkpoints
- Cairo export to MP4 and `manim-studio render`
- Incremental invalidation with edit classes
- Test suite (random access, transforms, invalidation, Qt-vs-Cairo, UI smoke)
- Benchmarks B1–B9
- **S0 previewer**: `manim-studio edit` — open/save, scrub, play, step, idle checkpoints

## Phase 1 — editor MVP ✅ (2026-10-09)

| slice | scope | done when |
|---|---|---|
| ✅ **S1 timeline** — [plan](plans/s1-timeline.md) | QGraphicsView: one row per layer, clip bars draggable and resizable, playhead scrub, overlap prevented (drags clamp at neighbours), undo/redo | dragging a clip updates the canvas live (≤ 33 ms per applied step; B16: 19–24 ms in the editor) |
| ✅ **S2 panels** — [plan](plans/s2-panels.md) | layer list (reorder = z-order), object library, properties panel generated from the adapter registry | a new MathTex layer with a Write clip can be built without editing JSON (`tests/ui/test_acceptance_s2.py`) |
| ✅ **S3 canvas interaction** — [plan](plans/s3-canvas.md) | hit-testing with `qt_paths`, selection outline, move gizmo with the stopwatch rule (no keyframes → base value; keyframes → key at playhead), `QUndoStack` | move an object, undo, redo (`tests/ui/test_acceptance_s3.py`; B24: 18.5 ms per drag step) |
| ✅ **S4 export dialog** — [plan](plans/s4-export.md) | `QProcess` running `manim-studio render`, progress, cancel | export from the UI without freezing it (`tests/ui/test_export_dialog.py`; B26) |

**Smallest useful v1:** write an equation, move it, morph it into a second
equation, fade it out, export MP4 — without touching code or JSON. ✅ Reached:
`tests/ui/test_acceptance_v1.py` does exactly this through the menus, panels,
timeline and canvas, with the real build worker and renderer.

## Phase 2

- ✅ **P2c** — [plan](plans/p2c-part-layers.md): part layers (ADR 0012) — animate
  the terms of an equation as their own layers
- ✅ **P2e** — [plan](plans/p2e-matching-tex.md): TransformMatchingTex between equations (ADR 0020)
- ✅ **P2d** — [plan](plans/p2d-code-layers.md): code layers (ADR 0019) — a layer
  holding user-written Manim code, rendered into a frame cache and composited
  (for what the visual model cannot express: updaters, ValueTracker, simulations)
- ✅ **P2a** — [plan](plans/p2a-gizmos.md): scale / rotate gizmos, keyable transform properties, auto-key
- ✅ **P2f** — [plan](plans/p2f-anchor-gizmo.md): anchor (pivot) gizmo (ADR 0021) —
  rotate and scale about any point: pendulums, clock hands, hinges
- ✅ **P2b** — [plan](plans/p2b-keyframes.md): keyframes on the timeline, key view, easing curve editor
- ✅ **P2g** — [plan](plans/p2g-clip-kinds.md): more clip kinds, clip parameters and
  overlay clips (Circumscribe, Flash, FocusOn) through the allow-list harness (ADR 0022)

## Phase 3

- ✅ **P3b** — [plan](plans/p3b-graphs.md): axes and function graphs as child layers (ADR 0024)
- ✅ **P3e** — [plan](plans/p3e-svg.md): SVG layers; media files tracked on disk, missing files drawn as placeholders (ADR 0027)
- ✅ **P3c** — [plan](plans/p3c-move-along-path.md): MoveAlongPath clips along another layer's shape (ADR 0025)
- ✅ **P3d** — [plan](plans/p3d-curved-paths.md): curved position paths between keys (ADR 0026)
- ✅ **P3a** — [plan](plans/p3a-viewport.md): viewport zoom/pan with a re-framed camera (ADR 0023)
- ✅ **P3f** — [plan](plans/p3f-render-ahead.md): frames rendered ahead in a preview process, played from a cache (ADR 0028)

- ✅ **P3g** — [plan](plans/p3g-child-trees.md): graphs animate with their axes; turning along a path (ADR 0029)
- ✅ **P3h** — [plan](plans/p3h-axes-objects.md): points, areas, Riemann rectangles and labels on axes (ADR 0030)

## Phase 4

- ✅ **P4a** — [plan](plans/p4a-python-export.md): one-way Python export, readable or exact (ADR 0010, 0031)
- ✅ **P4b** — [plan](plans/p4b-plugins.md): plugins add object types (ADR 0032)
- ✅ **P4c** — [plan](plans/p4c-simulated-layers.md): simulated layers - traced paths and plugin simulations (ADR 0033)
- ✅ **P4d** — [plan](plans/p4d-audio.md): an audio track (ADR 0034)

## Phase 5 — built-in features

Plan for Phases 5 and 6: [plans/phases-5-6.md](plans/phases-5-6.md) (decision session 27).

- ✅ **P5a** — [plan](plans/p5a-subtitles.md): subtitle track: cues on their own row, styled, burned into the export, `.srt` in and out (ADR 0035)
- ✅ **P5b** — [plan](plans/p5b-readouts.md): value readouts (a Number counting with clips) and connectors between objects (ADR 0036)
- ✅ **P5c** — [plan](plans/p5c-markers.md): markers and snapping on every row; a sound effect at a clip's start
- ✅ **P5d** — [plan](plans/p5d-clipboard.md): duplicate, cut, copy and paste of layers, clips, sounds and subtitles; autosave and crash recovery (ADR 0038)
- ✅ **P5e** — [plan](plans/p5e-presets.md): presets and templates: animation presets, style themes, object templates

## Phase 6 — the studio

- ✅ **P6a** — [plan](plans/p6a-design-system.md): design system: tokens, dark studio stylesheet, icons, typography
- ✅ **P6b** — [plan](plans/p6b-pages.md): workspace pages like DaVinci Resolve's: Compose, Animate, Code, Audio, Deliver
- ✅ **P6c** — [plan](plans/p6c-canvas.md): canvas interaction: more on-canvas handles, snapping guides, multi-select with align/distribute
- ✅ **P6d** — [plan](plans/p6d-polish.md): presets browser, preferences, recent files, shortcuts help, onboarding, visual-bug sweep
- **P6e** — [plan](plans/p6e-release.md): release preparation (0.3.0 prepared and proposed; the release itself waits for the maintainer, ADR 0045)
- **GP** — [plan](plans/golden-path.md): the golden path - create, save, reopen and export a typical animation, excellently; readable Python export; 10+ minute scenes
- **P7** — [plan](plans/p7-studio-workflow.md): studio workflow - scene length, row selection, code layer management, Animate like After Effects and Unity, scaling for long scenes, 3D preparation (P7.1 and P7.3-P7.5 done; P7.2 mostly done)
- ✅ **P9** — [plan](plans/p9-pythagoras-feedback.md): what the Pythagoras project asked for - auto-key and right triangles, timeline follow lock, multi-select and shift timing, part colour, groups (U1-U6 done)
- **P10** — [plan](plans/p10-code-to-objects.md): from code to objects - Python objects built by the user's Manim code (P10.1 done, ADR 0051), templates P10.3 import a whole Manim scene as layers and clips: done, ADR 0053.
- **P12** — [plan](plans/p12-code-workspace.md): the Code workspace - replace / skip / keep both on export, an import window, online presets, drag and drop to the timeline and canvas (ADR 0057)
- **P11** — [plan](plans/p11-equation-steps.md): equation steps - type a derivation, get one MathTex per step and the morphs between them (P11.1 done, ADR 0054); simplify/solve suggestions and annotations later
- ✅ **Colour characters** — one colour per drawn glyph of a Text, MathTex or Tex: a dialog to click glyphs, gradients, rainbow, alternate (ADR 0055)
