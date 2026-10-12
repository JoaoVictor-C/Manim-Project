# P6a — The design system

- **Status:** Done
- **Date:** 2026-10-11
- **Decided in:** [decision session 33](../logs/decision-sessions.md) (Terza, `fast`, confidence 0.91)
- **Evidence:** B54 in [../logs/benchmarks.md](../logs/benchmarks.md)
- **ADR:** [0040 — The design system](../adr/0040-design-system.md)

## Goal

**Done when** the whole editor - menus, docks, fields, buttons, the timeline, the
canvas overlays and the curve editor - takes its colours, spacing and fonts from one
token set, buttons show icons, every text meets its contrast target, and the UI test
suite passes unchanged under the theme.

## Steps

| step | content | acceptance |
|---|---|---|
| P6a.1 | `ui/theme.py` (tokens, palette, stylesheet, fonts, contrast), applied by `run()` and the test fixture | contrast test, no stylesheet warnings, the UI suite under the theme |
| P6a.2 | `ui/icons.py`; icon buttons (Layers panel, transport); every colour literal in `ui/` moved to tokens; the pending property | icons resolve, no literal outside `theme.py`, screenshots reviewed |
| P6a.3 | docs | README screenshot notes, architecture, CHANGELOG |
