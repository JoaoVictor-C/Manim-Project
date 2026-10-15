# P6b — Workspace pages

- **Status:** Done (P6b.1 by the lead; P6b.2-P6b.5 by agents, merged 2026-10-12)
- **Date:** 2026-10-11
- **Decided in:** [decision session 34](../logs/decision-sessions.md) (Terza, `fast`, confidence 0.92)
- **Evidence:** B55 in [../logs/benchmarks.md](../logs/benchmarks.md)
- **ADR:** [0041 — Workspace pages](../adr/0041-workspace-pages.md)

## Goal

**Done when** the editor has five pages - Compose, Animate, Code, Audio, Deliver -
switched from a page bar and Shift+1..5, sharing one document, selection, undo and
playback, and every existing UI test passes unchanged.

## Steps

| step | content | acceptance |
|---|---|---|
| ✅ P6b.1 | `ui/pages/` (`Page`, `PageHost`, `Shared`), the page bar, View > Pages, Compose; docks removed | the UI suite unchanged; switching, parking, sizes, hidden panels |
| ✅ P6b.2 | **Animate**: viewer + Properties over a graph editor of the selected layer's tracks (value over time; drag keys in time and value; eases) and the timeline | edit keys in the graph, undo, the canvas follows |
| ✅ P6b.3 | **Code**: code layers listed; an editor with Python highlighting, line numbers, Run (Ctrl+Enter), status and error output with line links; the viewer | edit, trust, run, see errors at their line |
| ✅ P6b.4 | **Audio**: sounds table (name, file, start, trim, gain, fades), subtitles table (start, end, text), import buttons, the timeline and viewer | edit both tables, import, undo |
| ✅ P6b.5 | **Deliver**: export settings (file, size presets, fps, range, quality, subtitles), a queue of exports run one after another, the Python export with a readable/exact preview | queue two exports, both files right; save the Python scene |

The pages after P6b.1 are independent modules and can be built in parallel; each
registers in `MainWindow.__init__` (the page tuple) before the menus are built.
