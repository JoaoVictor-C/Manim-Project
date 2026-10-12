# P6b.2 — The Animate page

- **Status:** Done
- **Date:** 2026-10-12
- **Decided in:** [decision session 35](../logs/decision-sessions.md) (Terza, `fast`, confidence 0.88)
- **Evidence:** B56 in [../logs/benchmarks.md](../logs/benchmarks.md)
- **ADR:** [0041 — Workspace pages](../adr/0041-workspace-pages.md) (the page framework)

## Goal

**Done when** the Animate page (Shift+2) shows the selected layer's keyed transform values
as curves over time. You can select, retime, revalue, add and delete keys and set the eases
of their segments in that graph. Each edit is one undo step, and the canvas follows every
edit.

## Design

- **Layout:** the viewer and Properties are on top, the graph editor in the middle and the
  timeline at the bottom. The graph is as wide as the timeline, so both read time the same
  way; a graph beside the timeline would halve the width of both.
- **Curves:** x and y (the two parts of the position key), scale, rotation and opacity.
  Each curve has its own colour token (`curve_x` ... `curve_opacity`, at least 6:1 on the
  graph) and a checkbox in the legend. The graph offers only `keyable_props(layer)`, so a
  graph on axes (ADR 0024) shows opacity only. A value without keys is drawn as a dashed
  line at its base value.
- **Value axis:** each curve fills the plot over its own range: its values, at least a
  minimum span, plus 10 % padding; opacity always shows 0..1. One shared axis would draw
  opacity as a flat line beside rotation in degrees. The focused curve (the last one
  clicked) has the labelled value axis.
  - Ranges are frozen while a drag lasts. If the range were recomputed during the drag,
    dragging a key past the top would rescale the curve under the cursor.
  - Ctrl+wheel zooms all curves together, and a middle-button drag pans them.
- **A point is one track's key.** x and y share the position key, so moving either point in
  time moves both; moving one vertically changes only its own component. The timeline below
  still moves whole key-time columns.
- **Selection:** the shared selection holds (layer, key time), which Properties and the
  timeline use; the graph also keeps the property that was clicked.
  - After a click on a point in the graph, only that curve's key is highlighted.
  - After a click on a timeline diamond, every key at that time is highlighted.
  - Delete removes exactly the highlighted keys.
- **Drag:** every preview is built from the drag's start snapshot (as on the timeline).
  - Time follows `timeline.model.drag_keys` on the layer reduced to that one track: the
    same snap points and frame grid, and the key stays more than a frame from that track's
    neighbours. Alt turns snapping off, as on the timeline.
  - The value follows the frozen range; opacity is clamped to 0..1.
  - Shift keeps the drag on one axis.
  - Release records one undo step and Escape cancels the drag.
- **Other edits:**
  - Double-click on a curve adds a key holding the value the evaluator plays there.
  - Right-click on a segment offers the ease list or *Edit curve...* (the existing curve
    editor). Right-click on a key offers to delete it.
  - F frames all keys and the wheel zooms time.
  - The strip at the top scrubs the playhead, and `MainWindow.playheadMoved` keeps the
    playhead line current.
- **Sampling:** `graph_model.sample_track` walks the segments once (O(samples + keys)); a
  test checks it against `evaluator._sample` on random tracks (every ease, bezier presets,
  curved path segments). The curves are cached per view and per track, so a seek only
  strokes them again, and a drag resamples only the curve being dragged. The curves are
  stroked as separate segments: Qt strokes a wide antialiased polyline about 20 times
  slower (B56).
- **Core change:** `edits.retime_keys` and `edits.remove_keys` take `props=None`, as
  `set_key_ease` already did. None means every property, so existing callers behave as
  before.

## Steps

| step | content | acceptance |
|---|---|---|
| 1 | `props` on `retime_keys` / `remove_keys`; curve colour tokens | edit tests, theme tests |
| 2 | `ui/graph_model.py` (Qt-free): curves, ranges, sampling, view, hits, drag rule, edits | `tests/ui/test_graph_model.py` (parity with the evaluator) |
| 3 | `ui/graph_editor.py`, `ui/pages/animate.py`, registered after Compose; `playheadMoved` | `tests/ui/test_animate_page.py` through the real window |
| 4 | acceptance and mutation check | `tests/ui/test_acceptance_p6b2.py`; 38/38 mutants killed |
| 5 | B56, docs | benchmarks log, CHANGELOG, testing, architecture, README |
