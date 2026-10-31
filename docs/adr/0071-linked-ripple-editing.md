# 0071. Linked ripple editing: open or close time at a point and let what follows move with it

- **Status:** Accepted
- **Date:** 2026-10-31
- **Deciders:** João Victor

## Context

Changing the length of one part of a video - a longer pause before the conclusion, a beat cut by two seconds -
meant selecting everything after it by hand and shifting it (`shift_timing`, U4, moves any
selection by one amount). Missing a sound, a subtitle or a marker left the narration out of step with the picture,
and there was no way to see what a move would touch before making it.

## Decision

- `core/editing/ripple.py`. `affected(project, at, scope)` is everything in the **scope** (clips, keys, sounds,
  subtitles, markers, each on or off) that *starts* at or after `at`; `ripple(project, at, delta, scope)` moves
  exactly that with `shift_timing` (so keys stay on frames, an explicit Appears at / Disappears at travels with its
  boundary clip, nothing goes below 0 s, and an edit the schema refuses is refused whole, with its reason) and grows
  the scene to hold what moved later. Items that start before the point stay; one that spans it keeps its start and
  length.
- A **beat** is the span between two markers (the lead-in before the first, and the last to the end of the scene);
  `retime_beat` gives it another length by rippling at its end, refusing a length that would cut a clip inside it.
- **Edit > Ripple Edit...** (Ctrl+Alt+R) has two modes, insert or remove time at a point (the playhead by default)
  and change a beat's length, check boxes for the scope, and a line that says what would move, or why the edit cannot
  be made, before it is applied. One undo step.

## Consequences

- Closing a gap that would put two clips of one layer on top of each other is refused, not squeezed.
- Stretching what is inside a beat in proportion is not offered: a beat's content keeps its timing and what follows
  moves. It is the base for the beat sheet that links cards to beats.

## Alternatives considered

- **Ripple as a mode of dragging on the timeline** - the dialog shows the preview and the scope without a gesture
  to learn; a drag mode can be built on `affected`/`ripple` later.

## Evidence

- Tests: `tests/core/editing/test_ripple.py`, `tests/ui/shell/test_ripple_dialog.py`.
