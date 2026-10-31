# 0073. Visual beat sheet: the video beat by beat, between the markers

- **Status:** Accepted
- **Date:** 2026-10-31
- **Deciders:** João Victor

## Context

Markers name moments on the ruler and the ripple edit (ADR 0071) already treats the span between two of them as a
beat, but nothing showed the video as that list: what comes in, what is said and which sound plays in each part.
Reviewing the structure meant scrubbing the whole timeline.

## Decision

- `core/editing/beat_sheet.py` builds the sheet from the project and changes nothing: one `Row` per beat
  (`ripple.beats`) with the root objects whose lifetime starts in it (the camera never counts), the subtitles that
  start in it and the sounds that start in it, plus the time its picture is drawn at. `to_markdown` writes the same
  sheet as text for notes or review.
- **Edit > Beat Sheet...** (Ctrl+Alt+B) lists the rows with a small picture each, drawn one per event-loop tick so
  the window opens at once. Double-clicking a row moves the playhead to the start of its beat; **Copy as
  Markdown** puts the text on the clipboard.
- The ripple dialog named an icon that does not exist and failed to paint when shown; it now uses the
  chapters icon, and a test shows and paints it.

## Consequences

- Markers are the only way to divide the video; a project without any is one beat.
- The sheet is read-only. Renaming or moving a beat is done with the markers and the ripple edit.
