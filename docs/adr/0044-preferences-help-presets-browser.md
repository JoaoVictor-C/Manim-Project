# 0044. Preferences, help and the presets browser

- **Status:** Accepted
- **Date:** 2026-10-12
- **Deciders:** João Victor

## Context

The editor forgot everything between starts (recent files, the window, panel sizes,
view toggles), a first start showed an empty canvas with no hint, shortcuts were only
discoverable through menus, and presets could only be picked by name from a menu.

## Decision

- **Preferences** live in one QSettings file in ini format at `MANIM_STUDIO_SETTINGS`
  (default: the user configuration folder): recent files (ten, missing ones dropped),
  the window's geometry and state, each page's splitter sizes, the view toggles (snap
  to objects, half-resolution playback, render ahead) and the last page, which is
  restored when a project opens. Tests point it at a fresh file each.
- **Help:** a first-run welcome on the empty viewer (New, Open, the example, recent
  files) until a project opens; Help > Keyboard Shortcuts generated from the window's
  own actions plus the canvas and timeline gestures.
- **Layout checks** run as tests over every page and dialog at 1024x640: menu actions
  carry tooltips (an allowlist for self-explanatory ones), nothing is squeezed below its
  minimum size hint, non-wrapping labels are not clipped.
- **Presets browser:** a dialog (Animate > Browse Presets..., and the timeline row menu)
  with category tabs, search and animated thumbnails - each preset drawn on a square by
  the in-process evaluator, rendered when the dialog opens and cached per preset; it
  applies to every selected layer at the playhead (or the clicked time).

## Consequences

- One settings file to inspect or delete; the registry is never used.
- The thumbnails are real frames, so a preset previews exactly what it does.

## Evidence

- B61 in [../logs/benchmarks.md](../logs/benchmarks.md): 1.7 ms per 8-frame thumbnail
  (median, 6 ms worst), 62 ms for all 32 built-in presets; frames checked non-empty.
- Design: [../logs/decision-sessions.md](../logs/decision-sessions.md), session 40.
- Plan: [../plans/p6d-polish.md](../plans/p6d-polish.md).
