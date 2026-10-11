# P5a — Subtitle track

- **Status:** Done
- **Date:** 2026-10-11
- **Decided in:** [decision session 28](../logs/decision-sessions.md) (Terza, `fast`, confidence 0.90)
- **Evidence:** B48 in [../logs/benchmarks.md](../logs/benchmarks.md)
- **ADR:** [0035 — A subtitle track](../adr/0035-subtitle-track.md)

## Goal

**Done when** subtitles can be typed or imported from an `.srt`, placed and timed on
their own timeline row, styled once for the whole video, seen in the editor and
in frames rendered ahead, burned into the exported video with an `.srt` beside it,
and carried by both Python export forms.

## Schema

- `Cue(id, start >= 0, end > start, text)`, `SubtitleStyle(font_size=26,
  y=-3.52, colour="#f8fafc", band=True, band_colour="#020617", band_opacity=0.72,
  fade=0.15, burn_in=True, max_width=12.5)`.
- `Project.subtitles: list[Cue]` (sorted, no overlaps), `Project.subtitle_style`;
  both omitted when empty / default. Ids unique among layers, sounds and cues.

## Core

- `core/subtitles.py`: `wrap(text, style)`, `read_srt(text) -> list[Cue]`,
  `write_srt(cues) -> str`, `place_cue(project, t) -> (start, end) | None`,
  `changed_spans(old, new)`.
- `adapter.subtitle_mobject(text, style)` (cached; band + text, scaled to fit).
- `Evaluator.overlay(t)`; `frame(t) = layers + overlay`.
- `frame_cache.changed_spans`: subtitle cue spans, all cue spans on a style change.
- Edits: `add_cue`, `update_cue`, `trim_cue`, `remove_cue`, `set_subtitles`
  (import), `set_subtitle_style` — kind timing, no layers.
- `warm`: cue texts for the build worker (not waited for).
- Export: burned in via `frame()`; `<video>.srt` written beside the video.
- Python export: `add_subcaption` per cue (both forms); burned in -> exact.

## UI

- Canvas draws layers + overlay.
- Timeline: a Subtitles row (between layers and sounds) with cue bars; move, trim,
  Delete; right-click: Add subtitle here / Delete subtitle.
- Selection: `subtitle_id`; Properties: cue (start, end, text) + style.
- Edit > Add Subtitle; File > Import Subtitles... / Export Subtitles...

## Steps

| step | content | acceptance |
|---|---|---|
| P5a.1 | schema, subtitles module, drawing, caches, edits, export, Python export | random access with cues equals sequential; .srt round trip and tolerant reading; wide text fits; render-ahead spans; export frames + sidecar; both Python forms |
| P5a.2 | canvas, timeline row, selection, Properties, menus | add, edit, move, trim, delete, import and export from the UI |
| P5a.3 | acceptance, docs | import an .srt, edit cues and style, export a video whose frames and .srt match the editor; exact Python scene |
