# P5e — Presets, templates and themes

- **Status:** Done
- **Date:** 2026-10-11
- **Decided in:** [decision session 32](../logs/decision-sessions.md) (Terza, `fast`, confidence 0.90)
- **Evidence:** B52 in [../logs/benchmarks.md](../logs/benchmarks.md)
- **ADR:** [0039 — Presets, templates and themes](../adr/0039-presets-templates-themes.md)

## Goal

**Done when** a layer gets a pop-in, slide-in, typewriter, bounce or fade-out from a
menu at the playhead (refused with a reason where it cannot apply), a theme recolours
the selection or the whole scene, a title card or lower third is inserted from
*Add > Templates*, and the user's own presets and templates are saved and offered.

## Core (`core/editing/library.py`, pure)

- `Preset`, `PresetClip`, `PresetKey`, `Theme`, `Template` models; `load_item(path)`,
  `load_library(folders)` -> items and problems; `builtin_folder()`, `user_folder()`.
- `apply_preset(project, layer_id, preset, t) -> Edit` (whole or `EditError` with the
  reason), the hold rule, kind fallbacks, relative keys.
- `apply_theme(project, theme, layer_ids | None) -> Edit`.
- `preset_from_layer(layer, name, category)`, `template_from(project, root_id, name)`.
- `insert_template(project, template, t)` via `core/editing/clipboard.py` (P5d).

## Built-ins (`src/manim_studio/data/library/*.json`)

- Presets: Fade in, Pop in, Slide in from left / right / below, Typewriter, Draw,
  Grow from edge, Spin in; Indicate, Pulse (scale keys), Wiggle, Circle it, Flash;
  Fade out, Shrink out, Slide out, Unwrite; Drift up, Bounce (scale keys).
- Themes: Manim (black), Chalkboard, Paper, Blueprint, Midnight.
- Templates: title card, section header, lower third, callout, equation reveal, counter.

## Steps

| step | content | acceptance |
|---|---|---|
| P5e.1 | library format and loading, presets, themes, menus | every built-in preset applies to the types it names, frames before the playhead unchanged, refusals with reasons, undo is one step |
| P5e.2 | templates and saving (after P5d) | each built-in template inserts and draws; saved items reload |
| P5e.3 | acceptance, docs | the Goal's scenario through the UI |
