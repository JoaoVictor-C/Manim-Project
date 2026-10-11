# 0035. A subtitle track: cues in one lane, drawn over the frame

- **Status:** Accepted
- **Date:** 2026-10-11
- **Deciders:** João Victor

## Context

The 95 s explainer needed 17 subtitles; each had to be a separate Text layer with
hand-timed fades. Videos usually carry subtitles, burned in or as an `.srt`.
Manim's `Scene.add_subcaption` writes an `.srt` next to the video.

## Decision

- **Model.** A project has subtitle cues (`id`, `start`, `end`, `text`) in one lane
  (they never overlap) and one subtitle style (font size, vertical position,
  colour, a band behind the text with its colour and opacity, fade time, burn-in
  on/off, maximum line width). Both are saved only when used.
- **Drawing.** Subtitles are an overlay drawn after every layer: `Evaluator.frame`
  adds it and the canvas draws it; `frame_layers` stays layers only, so clicking
  on the canvas never selects a subtitle. A cue's text is wrapped at word
  boundaries by a character budget (about 0.18 units per character at size 26,
  B48), built once per text and style, and scaled down if a line is still wider
  than the maximum width. Cues fade in and out by opacity.
- **Caches.** Cue edits re-render only the frames of the cues they touch (before
  and after the edit); style edits re-render every cue's frames; no layer cache is
  dropped. New cue text is built ahead by the build worker in the background,
  without holding the edit (a cold line costs ~0.4 s, B48; an imported file of 100
  cues would otherwise wait ~40 s).
- **Editing.** One Subtitles row on the timeline, between the layers and the
  sounds: cue bars show their text; drag to move or trim, Delete removes.
  Properties edit the selected cue and the style. Edit > Add Subtitle places a cue
  at the playhead (2 s, or up to the next cue). File > Import / Export Subtitles
  reads and writes `.srt`; the reader accepts a byte-order mark, CRLF, missing
  indices, comma or dot milliseconds, strips formatting tags and trims overlapping
  cues into one lane.
- **Export.** Subtitles are burned into the video when burn-in is on, and an `.srt`
  is always written beside the exported video. Python exports call
  `add_subcaption` for every cue, so `manim render` writes the same `.srt`; burned-in
  subtitles make the export exact (the scene draws them as the editor does).

## Consequences

- The first time a new cue is drawn in the editor it may take ~0.4 s to build.
- Two people speaking at once need two lines in one cue.

## Evidence

- Probe: B48 in [../logs/benchmarks.md](../logs/benchmarks.md).
- Design: [../logs/decision-sessions.md](../logs/decision-sessions.md), session 28.
- Plan: [../plans/p5a-subtitles.md](../plans/p5a-subtitles.md).
