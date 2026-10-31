# Architecture Decision Records

An ADR records one significant decision: the context, what was decided, the
consequences, and the evidence behind it. ADRs are immutable once accepted —
to change a decision, write a new ADR that supersedes the old one and update
the old one's status.

## When to write one

Write an ADR when a change:

- alters how the document model maps to Manim (evaluator, clips, keyframes);
- adds or replaces a dependency, renderer, file format or process boundary;
- changes a rule other code relies on (overlap rule, invalidation, allow-list);
- is expensive to reverse.

Bug fixes, refactors and new clip kinds that pass the existing harness do not
need one.

## How

1. Copy [template.md](template.md) to `NNNN-short-title.md` (next free number).
2. Status `Proposed`; open it for discussion (PR or issue).
3. Back claims with evidence: a test, a benchmark in [../logs/benchmarks.md](../logs/benchmarks.md),
   or a source reference. Unmeasured claims are labelled as such.
4. On acceptance set `Accepted` and add it to the index below.

## Index

| # | Title | Status |
|---|---|---|
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions | Accepted |
| [0002](0002-editor-owns-manims-clock.md) | The editor owns Manim's clock | Accepted |
| [0003](0003-stack-python-pyside6-pinned-manim.md) | Stack: Python 3.13, uv, PySide6, pinned Manim behind an adapter | Accepted |
| [0004](0004-one-clip-lane-per-layer-keyframes-for-motion.md) | One clip lane per layer; motion and style as keyframes | Accepted |
| [0005](0005-morph-clips-are-world-space-hand-offs.md) | Morph clips are world-space hand-offs | Accepted |
| [0006](0006-preview-renders-with-manims-cairo-camera.md) | Preview renders with Manim's Cairo camera | Accepted |
| [0007](0007-allow-list-and-adapter-patches.md) | Allow-list and adapter patches for unsafe animations | Accepted |
| [0008](0008-incremental-invalidation-edit-classes.md) | Incremental invalidation with edit classes | Accepted |
| [0009](0009-playback-scheduling.md) | Playback scheduling: frame dropping, idle checkpoints, gc.freeze | Accepted |
| [0010](0010-python-round-trip-is-export-only.md) | Python round-trip is one-way export | Accepted |
| [0011](0011-logging.md) | Logging: console plus per-user rotating file | Accepted |
| [0012](0012-layer-tree-and-part-layers.md) | Layer tree and part layers | Proposed |
| [0013](0013-timing-edits-keep-caches.md) | Edit kinds: timing edits keep caches | Accepted |
| [0014](0014-document-snapshots-and-undo.md) | Document snapshots and undo | Accepted |
| [0015](0015-build-worker-warm-then-commit.md) | Build worker: warm Manim's disk cache, then commit | Accepted |
| [0016](0016-canvas-hit-testing-and-stopwatch-rule.md) | Canvas editing: hit-testing and the stopwatch rule | Accepted |
| [0017](0017-export-process-and-safe-output.md) | Exports run in a process and replace the output only when complete | Accepted |
| [0018](0018-keyable-properties-and-auto-key.md) | Keyable properties and auto-key | Accepted |
| [0019](0019-code-layers.md) | Code layers | Accepted |
| [0020](0020-matching-morphs.md) | Matching morphs between equations | Accepted |
| [0021](0021-anchor-point.md) | The anchor point | Accepted |
| [0022](0022-clip-params-and-overlays.md) | Clip parameters and overlay clips | Accepted |
| [0023](0023-canvas-viewport.md) | Canvas viewport | Accepted |
| [0024](0024-axes-and-graphs.md) | Child objects: axes and graphs | Accepted |
| [0025](0025-move-along-path.md) | Moving along another layer's path | Accepted |
| [0026](0026-curved-position-paths.md) | Curved position paths | Accepted |
| [0027](0027-svg-layers-and-media-files.md) | SVG layers and media files | Accepted |
| [0028](0028-render-ahead-cache.md) | Render-ahead cache | Accepted |
| [0029](0029-child-objects-in-the-tree.md) | Child objects animate with their object | Accepted |
| [0030](0030-objects-on-axes.md) | Points, areas, rectangles and labels on axes | Accepted |
| [0031](0031-python-export.md) | Python export: readable when it can be, exact otherwise | Accepted |
| [0032](0032-plugin-api.md) | Plugins add object types | Accepted |
| [0033](0033-simulated-layers.md) | Simulated layers: traced paths and plugin simulations | Accepted |
| [0034](0034-audio-track.md) | An audio track: project audio clips, one mix, the sound card as clock | Accepted |
| [0035](0035-subtitle-track.md) | A subtitle track: cues in one lane, drawn over the frame | Accepted |
| [0036](0036-readouts-and-connectors.md) | Value readouts and connectors | Accepted |
| [0037](0037-markers-and-snapping.md) | Markers and snapping | Accepted |
| [0038](0038-clipboard-and-recovery.md) | Clipboard, duplicate and crash recovery | Accepted |
| [0039](0039-presets-templates-themes.md) | Presets, templates and themes | Accepted |
| [0040](0040-design-system.md) | The design system | Accepted |
| [0041](0041-workspace-pages.md) | Workspace pages | Accepted |
| [0042](0042-deliver-options.md) | Deliver options: size, fps, range, quality, subtitles and a render queue | Accepted |
| [0043](0043-canvas-interaction.md) | Canvas interaction: handles, guides, several objects | Accepted |
| [0044](0044-preferences-help-presets-browser.md) | Preferences, help and the presets browser | Accepted |
| [0045](0045-releases.md) | Releases: a wheel, a release check, nothing published by itself | Accepted |
| [0046](0046-readable-export-of-keyframes.md) | Readable Python export of keyframed layers | Accepted |
| [0047](0047-property-rows-and-graph-for-selection.md) | Property rows on the timeline; the graph shows the chosen properties | Accepted |
| [0048](0048-3d-capable-camera-fixed-for-2d.md) | 3D-capable project, camera fixed for 2D | Accepted |
| [0049](0049-part-colour.md) | Part colour: a part layer's style, and a Text's t2c | Accepted |
| [0050](0050-groups.md) | Groups: a root that draws nothing and carries its children | Accepted |
| [0051](0051-python-objects.md) | Python objects: objects built by the user's own Manim code | Accepted |
| [0052](0052-shape-objects-and-freezing.md) | Shape objects and freezing: an object kept as the vector data it draws | Accepted |
| [0053](0053-import-manim-scenes.md) | Importing a Manim scene: run it under a recorder, convert what can be redone exactly | Accepted |
| [0054](0054-equation-steps.md) | Equation steps: typed lines become one MathTex per step and morphs between them | Accepted |
| [0055](0055-glyph-colours.md) | Colour characters: one colour per drawn glyph, applied to a copy of the build | Accepted |
| [0056](0056-smart-morph-matching.md) | Smart morph matching: pieces, holes and start points paired by the editor | Accepted |
| [0057](0057-code-workspace.md) | The Code workspace: presets, an import window, safe online sources and drag and drop | Accepted |
| [0058](0058-helpers.md) | Helpers: reusable Python modules in the project, imported by name by code layers and Python objects | Accepted |
| [0059](0059-run-activity-and-time-limits.md) | Code runs show that they run (status bar, canvas, explorer) and their time limits can be lifted | Accepted |
| [0060](0060-voice-providers-and-narration.md) | Voice providers and narration: speech made from subtitles, by engines that are plugins | Accepted |
| [0061](0061-incremental-code-layers.md) | Incremental code layers: cheaper renders, chapters that are proved against the full render, layers you declare | Accepted |
| [0062](0062-package-layout.md) | Package layout: folders named for what the code does, and layers that a test checks | Accepted |
| [0063](0063-lumen-interface.md) | Lumen: a new interface built on the existing design system (tokens, bundled fonts, cards, top bar, palette, toasts) | Accepted |
| [0064](0064-helper-lifetime-and-memory.md) | Helper lifetime and memory: helpers end with the editor and rest when idle, numpy's threads and the editor's leaks are bounded | Accepted |
| [0065](0065-parallel-export-and-gpu-encoding.md) | Parallel export and GPU encoding: frames drawn by several processes, encoded by the graphics card when it pays | Accepted |
| [0066](0066-export-health-report.md) | Export health report: what will be slow or will not work, found before the export starts | Accepted |
| [0067](0067-code-errors-know-their-time.md) | Code errors know their time: an error says how far the scene got, and the page can show that frame | Accepted |
| [0068](0068-named-project-snapshots.md) | Named project snapshots: milestones kept beside the file, apart from undo | Accepted |
| [0069](0069-script-to-timeline.md) | Script to timeline: a written script becomes timed subtitle cues, with optional placeholders | Accepted |
| [0070](0070-draft-preview-while-editing.md) | Draft preview while editing: heavy edits are drawn small and marked, and in full when the user pauses | Accepted |
| [0071](0071-linked-ripple-editing.md) | Linked ripple editing: open or close time at a point and let what follows move with it | Accepted |
| [0072](0072-camera-layer.md) | Camera layer: the view pans, zooms and rolls by one layer's keys | Accepted |
| [0073](0073-visual-beat-sheet.md) | Visual beat sheet: the video beat by beat between the markers, with pictures and a Markdown copy | Accepted |
