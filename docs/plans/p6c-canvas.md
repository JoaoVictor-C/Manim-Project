# P6c — Canvas interaction

- **Status:** Done
- **Date:** 2026-10-12
- **Decided in:** [decision session 39](../logs/decision-sessions.md) (Terza, `fast`, confidence 0.92)
- **Evidence:** B60 in [../logs/benchmarks.md](../logs/benchmarks.md)
- **ADR:** [0043 — Canvas interaction](../adr/0043-canvas-interaction.md)

## Goal

**Done when** an object's size, radius, ends and font size are dragged on the canvas,
moves snap to other objects with a visible guide, several objects are selected,
moved, deleted, copied and given a preset together, and Arrange lines them up.

## P6c.1 — parameter handles and snapping guides

- `ui/param_handles.py` (pure): for a spec, its handles (name, local point, param,
  how a local point maps to the param value) and `value_at(handle, local)`; clamps from
  the registry.
- `MoveTool`: hit order parameter handle > corner > knob > pivot > body; a handle drag
  previews `edits.update_layer(spec=...)`; Shift steps; Escape cancels; one undo step.
- `ui/snap_guides.py` (pure): box edges/centres of other visible objects and the frame;
  `snap(box, candidates, radius)` -> offset and guide lines; the canvas draws them.

## P6c.2 — several objects (after the pages merge)

- `Selection.layer_ids` (primary = `layer_id`); canvas Shift+click and marquee; Layers
  ExtendedSelection; group move; Delete, clipboard, presets, themes on all (checklist:
  the 28 readers of `selection.layer_id` in canvas_tools, layers_panel, main_window,
  clipboard_actions, plus the pages); Properties' note; Arrange menu (align, distribute).

## Steps

| step | content | acceptance |
|---|---|---|
| ✅ P6c.1 | parameter handles, snapping guides | every handle type dragged on a turned, scaled object; guides; undo; Escape |
| ✅ P6c.2 | multi-select, group actions, Arrange | marquee, group move/delete/copy/preset, align and distribute |
