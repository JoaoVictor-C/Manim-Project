# 0037. Markers and snapping

- **Status:** Accepted
- **Date:** 2026-10-11
- **Deciders:** João Victor

## Context

The explainer's 31 sound effects were timed by hand, and nothing marks a moment
on the timeline ("the formula appears", "the second section"). Drags snapped to
clip edges and the playhead only, not to keys, sounds or subtitles.

## Decision

- **Markers are part of the project**: a sorted list of markers (id, time, name,
  colour, default amber), at most one per frame, ids unique among layers, sounds,
  subtitles and markers, left out of the file when there are none. Marker edits
  are timing edits: no cached frame is dropped (they join the parts render-ahead
  ignores, like sounds) and they undo like any edit.
- **On the ruler** a marker is a named flag. Click selects it (Properties: name,
  time, colour), drag moves it with snapping and stops at the last free frame
  (never onto another marker), right-click renames, deletes or adds a sound there,
  and Delete in the timeline removes a selected marker. Selecting a marker clears
  the clip, key, sound and subtitle selection, so Delete is never ambiguous.
  **Edit > Add Marker (M)** adds one at the playhead frame, or selects the marker
  already there; **Previous Marker ([)** and **Next Marker (])** move the playhead.
  Shift+arrows are not used: the canvas nudges objects with them.
- **Snapping**: every drag (clips, keys, sounds, subtitles, markers) snaps to one
  list of points: 0, the end, the playhead, markers, clip edges, key times, sound
  and subtitle edges, without the dragged item's own points. The nearest point
  within 8 px wins (no ranking), a guide line shows it while the drag rests on it,
  and Alt turns snapping off.
- **Sound at a moment**: a clip's menu has *Add sound at start* and *Add sound at
  end*, a marker's *Add sound here*; each lists the project's sound files (the
  last added first, files that cannot be read left out) and *Other file...*, and
  adds the whole file there like File > Import Audio.
- **Exports**: markers change no frame. The readable Python scene ignores them;
  the exact scene carries them in its embedded project.

## Consequences

- Markers are not moved onto the new frame grid when the fps changes (neither are clips).
- Every key time is a snap point, so densely keyed projects may feel sticky (Alt).
- M adds a marker while a combo box has focus (text fields keep their letters).

## Evidence

- B50 in [../logs/benchmarks.md](../logs/benchmarks.md): 27 of the explainer's 31
  hand-timed sounds start on a clip edge; 183 snap points are gathered and searched
  in 0.05 ms per mouse move.
- Design: [../logs/decision-sessions.md](../logs/decision-sessions.md), session 30.
- Plan: [../plans/p5c-markers.md](../plans/p5c-markers.md).
