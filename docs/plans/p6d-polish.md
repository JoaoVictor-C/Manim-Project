# P6d — Polish

- **Status:** In progress
- **Date:** 2026-10-12
- **Decided in:** [decision session 40](../logs/decision-sessions.md) (Terza, `fast`, confidence 0.90)
- **Evidence:** B61 in [../logs/benchmarks.md](../logs/benchmarks.md)
- **ADR:** [0044 — Preferences, help and the presets browser](../adr/0044-preferences-help-presets-browser.md)

## Goal

**Done when** the editor remembers how it was left (recent files, window, panel sizes,
view toggles, the last page), greets a first start with a way in, lists its shortcuts,
lets presets be browsed with moving previews, and every page and dialog passes the
layout checks and a screenshot review at a small and a large window.

## Slices

| step | content | who | acceptance |
|---|---|---|---|
| ✅ P6d.1 | preferences (QSettings ini at `MANIM_STUDIO_SETTINGS`), File > Open Recent, remembered geometry, splitter sizes per page, view toggles, last page (restored when a project opens), the welcome on the empty viewer | agent (Sonnet), after the Deliver page | quit and start again: everything as left; a fresh settings file gives today's defaults |
| ✅ P6d.2 | Help > Keyboard Shortcuts (from the window's actions plus the canvas and timeline gestures); layout checks as tests over every page and dialog at 1024x640 (menu actions have tooltips outside an allowlist, nothing below its minimum size hint, no clipped non-wrapping labels) | agent (Sonnet), after the Deliver page | the checks pass; findings beyond trivial ones listed for P6d.4 |
| P6d.3 | presets browser: a dialog (Animate > Browse Presets..., the timeline row menu) with category tabs, search, animated thumbnails rendered in-process (B61) and cached per preset, playing on hover; applies to every selected layer at the playhead (or the clicked time); user presets included | agent (Sonnet), now | browse, preview and apply a preset to two layers in one undo step |
| P6d.4 | visual sweep: screenshots of every page and dialog at 1024x640 and 1920x1080, fixes | lead, last | a reviewed screenshot set with no clipped, overlapping or cramped controls |

## Notes

- Every test points `MANIM_STUDIO_SETTINGS` at a fresh file (conftest), so windows in
  tests start at defaults: Compose first, no restored geometry.
- The clipping check uses an allowlist for labels that wrap or elide by design (paths).
