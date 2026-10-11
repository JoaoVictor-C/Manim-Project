# P5c — Markers and snapping

- **Status:** In progress
- **Date:** 2026-10-11
- **Decided in:** [decision session 30](../logs/decision-sessions.md) (Terza, `fast`, confidence 0.91)
- **Evidence:** B50 in [../logs/benchmarks.md](../logs/benchmarks.md)
- **ADR:** [0037 — Markers and snapping](../adr/0037-markers-and-snapping.md)

## Goal

**Done when** named markers can be added at the playhead (M), moved, renamed and
deleted on the ruler and jumped between ([ and ]); every timeline drag snaps to
markers and to clip, key, sound and subtitle edges with a visible guide; and a
sound can be added at a clip's start or end or at a marker in two clicks.

## Core

- `schema.Marker(id, t >= 0, name="", colour="#f59e0b")`; `Project.markers` sorted,
  one per frame (`frame_index` at the canvas fps), ids unique with layers, audio and
  cues; serializer omits an empty list.
- `edits.add_marker(project, t, name="")` (on the frame grid; returns the marker id),
  `update_marker`, `remove_marker`: kind `timing`, no layers; `new_layer_id` covers
  marker ids. `frame_cache._NOT_CANVAS` gains `markers`.
- `timeline.model.snap_candidates(project, playhead, exclude)`: `exclude` is a set of
  item keys - `("clip", layer, clip)`, `("key", layer, t)`, `("audio", id)`,
  `("cue", id)`, `("marker", id)`; returns sorted points. `snapped_to(t, candidates)`
  tells the view whether to draw the guide.
- `model.marker_drag(project, marker_id, proposed, ...)`: snap, then keep the last free
  frame.

## UI

- `selection.marker_id` / `set_marker` (exclusive).
- Ruler: flags with names, hit-testing, drag, context menu (Rename..., Delete,
  Add sound here), Delete key, guide line while snapped.
- Edit menu: Add Marker (M), Previous Marker ([), Next Marker (]).
- Properties: name, time, colour of the selected marker.
- Clip menu: Add sound at start / at end; submenus of the project's sound files.

## Steps

| step | content | acceptance |
|---|---|---|
| P5c.1 | Marker schema and edits, unified snap candidates, marker drag rule | validation, edits keep frames, every drag kind snaps to every point kind, exclusion |
| P5c.2 | ruler, menus, Properties, guide line, sound at a clip or marker | add/move/rename/delete/jump in the editor, sounds placed in two clicks |
| P5c.3 | acceptance, docs | the Goal's scenario through the UI, render-ahead untouched by marker edits, export unchanged |
