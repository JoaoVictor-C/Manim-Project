# 0070. Draft preview while editing: heavy edits are drawn small and marked, and in full when the user pauses

- **Status:** Accepted
- **Date:** 2026-10-31
- **Deciders:** João Victor

## Context

The canvas shows the exact Cairo frame ([0028](0028-render-ahead-cache.md)). When a frame is not in the render-ahead
cache - while an object is dragged, the playhead scrubbed over changed content, or a heavy scene played - the editor
draws it on the spot, and a scene with many objects or large text takes tens of milliseconds a frame: the drag
lags behind the mouse. "Half-resolution playback" exists but is a switch the user has to know about and remember to
turn back off.

## Decision

- The canvas notices heavy interaction by itself. A render that takes over 60 ms, arriving less than 0.3 s after the
  previous one (so a drag, a scrub or playback, not a click), starts a **draft**: the following frames are drawn at half
  size and a **DRAFT** badge shows. When no render has happened for 350 ms, the draft ends and the current frame is
  drawn in full.
- Light scenes never enter it (their renders are quick), and neither do frames served from the render-ahead cache,
  which are exact already. With **Half-resolution playback** on there is nothing to add.
- **View > Draft Preview While Editing** turns it off (remembered, on by default); turning it off leaves a draft at once.

## Consequences

- While dragging a heavy scene the picture is blurrier and marked; the pause redraws it, so the user always ends on the
  exact frame. Export is unaffected: it never goes through the canvas.
- The thresholds are fixed numbers measured against the editor's own frame costs, not tuned per machine.

## Alternatives considered

- **Always render the preview small** - blurry for everyone, when only heavy scenes need it.
- **Lower the rate instead of the size** - the mouse would still lead the picture by the same lag.

## Evidence

- Tests: `tests/ui/canvas/test_draft_preview.py`.
