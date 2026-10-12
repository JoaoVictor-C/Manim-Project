# P6b.4 — The Audio page

- **Status:** Done
- **Date:** 2026-10-12
- **Decided in:** [decision session 37](../logs/decision-sessions.md) (Terza, `fast`, confidence 0.90)
- **Evidence:** B58 in [../logs/benchmarks.md](../logs/benchmarks.md)
- **ADRs:** [0041 — Workspace pages](../adr/0041-workspace-pages.md) (the page framework),
  [0034 — Audio track](../adr/0034-audio-track.md), [0035 — Subtitle track](../adr/0035-subtitle-track.md)
- **Parent plan:** [p6b-pages.md](p6b-pages.md) (step P6b.4)

## Goal

**Done when** the Audio page (Shift+4) shows a table of the project's sounds and a table of its
subtitles, both editable in place (each edit one undo step, through `core/edits.py`), with import,
delete and play buttons, a level meter that reads the mix at the playhead, the subtitle style in the
Properties panel, the shared viewer and the shared timeline; an invalid edit is refused with the
reason in the status bar and the cell keeps its old value.

## Design

| piece | where | notes |
|---|---|---|
| cell text <-> value, and the `Edit` a cell edit makes | `core/tables.py` (pure) | `SOUND_COLUMNS`, `CUE_COLUMNS`; `sound_cell`, `cue_cell`, `sound_edit`, `cue_edit`, `parse_number` (`1.5`, `1,5`, `1.5 s`, `-6 dB`, `1:02.5`), `reason(exc)` (the first pydantic error without its prefix) |
| the meter's numbers | `core/levels.py` (pure) | `window_samples(project, t0, t1)` mixes only that span, straight from the decoded clips (gain and fades computed for the slice, same float32 arithmetic as `audio.clip_samples`, so it equals `audio.mix` there); `level_at(project, t)` = peak and RMS per channel of the 100 ms centred on `t` (clamped to the video; an empty window is silence) |
| table models | `ui/pages/audio.py` | one generic `QAbstractTableModel` over the document snapshot, rows keyed by id, rebuilt on every document change (`dataChanged` when the ids are unchanged, so the editor and selection survive); `setData` applies the `Edit` once or refuses with the reason |
| the page | `ui/pages/audio.py` | Sounds | Subtitles tables, viewer over the meter, Properties (subtitle style), the timeline below |
| playhead signal | `MainWindow.playheadMoved(float)` (shared with Animate) | emitted by `seek`, drives the meter while scrubbing and playing |

Selection: a click on a row selects the sound or subtitle in the shared `Selection` (a cue row also
seeks the playhead); a selection made elsewhere (the timeline, Properties) selects the row without
seeking. A re-entrancy flag separates the two.

## Steps

| step | content | acceptance |
|---|---|---|
| a | `core/tables.py`, `core/levels.py` with unit tests (cell round trips, every refusal, the window equals the full mix, known tone levels) | `tests/core/test_tables.py`, `tests/core/test_levels.py` |
| b | the page, models, buttons, meter, selection sync, registration, `playheadMoved` | `tests/ui/test_audio_page.py` |
| c | acceptance: import two sounds and an .srt, edit rows in both tables, timeline and evaluator follow, undo, the meter on a known tone | `tests/ui/test_acceptance_p6b4.py` (slow, ui) |
| d | B58 (`benchmarks/bench_audio_page.py`), mutation check, docs | `.cache/p6b4/mutate.py`: every non-equivalent mutant killed |
