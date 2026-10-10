# 0023. Canvas viewport

- **Status:** Accepted
- **Date:** 2026-10-10
- **Deciders:** João Victor
- **Amends:** [0016](0016-canvas-hit-testing-and-stopwatch-rule.md) (canvas geometry)

## Context

The canvas always showed the whole video frame, letterboxed. Small objects (a
term of an equation) left their handles crowded, and objects outside the frame
were invisible although they could be clicked.

## Decision

- The canvas has a **view**: a Fit mode (the letterbox, following the widget)
  or an absolute scale in export pixels with a centre in Manim units. Zooming
  or panning leaves Fit; Ctrl+0 returns to it. The view is editor state: not
  saved, not undoable.
- The preview camera is **re-framed** to cover the whole widget, so the
  pasteboard around the frame shows (dimmed, with a frame border) at a cost of
  about 2 ms per frame at Fit (B36). The export camera is unchanged.
- All canvas geometry keeps going through `px_per_unit`, `to_units` and
  `units_transform`; handle sizes and hit tolerances stay in screen pixels.
- Ctrl+wheel zooms about the cursor, wheel pans, middle-drag pans; Space keeps
  Play/Pause.

## Consequences

- Zooming in is the fix for crowded handles; no gizmo change was needed.
- A larger widget renders more pixels even at Fit (the pasteboard).

## Evidence

- Measurements: B36 in [../logs/benchmarks.md](../logs/benchmarks.md).
- Design: [../logs/decision-sessions.md](../logs/decision-sessions.md), session 15.
- Plan: [../plans/p3a-viewport.md](../plans/p3a-viewport.md).
