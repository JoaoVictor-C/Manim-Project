# 0032. Plugins add object types

- **Status:** Accepted
- **Date:** 2026-10-11
- **Deciders:** João Victor

## Context

Users want their own objects (a pendulum, a circuit symbol, a molecule) in the
library, animated by clips like built-in ones. Code layers (ADR 0019) run
whole scenes but are not objects clips can act on.

## Decision

- **`manim_studio.plugins`** is the public API: `register(ObjectType(name,
  build, params, section, label, slow))`. `build(params)` returns a VMobject
  and depends only on its params; the editor centres it, styles it and animates
  it like any object. Names already taken are refused.
- **Discovery:** plugins load once, when `core.adapter` is imported, so every
  process (editor, build worker, preview, export, exported scenes) has the same
  types: Python entry points in the group `manim_studio.plugins`, then the `.py`
  files of the folders in `MANIM_STUDIO_PLUGINS` (default
  `~/.manim-studio/plugins`), in sorted order. A failing plugin is skipped and
  listed (Help → Plugins…).
- **Trust:** plugins are code the user installed; they run without a prompt (a plugin with a manifest is
  allowed once first: [0078](0078-plugin-manifest-and-permissions.md)).
  Project files never carry plugin code.
- **Determinism is checked:** the first build of a plugin type in a process is
  done twice and compared. A plugin that differs, raises or does not return a
  VMobject draws the dashed placeholder (ADR 0027) with the reason, as does a
  type no installed plugin provides.
- Slow types are warmed by the build worker; plugin objects make a Python
  export exact (ADR 0031).

## Consequences

- A frame now also depends on the installed plugins' code; changing a plugin
  needs a restart.
- Raster (non-VMobject) plugins are not supported yet.

## Evidence

- Probe: B45 in [../logs/benchmarks.md](../logs/benchmarks.md).
- Design: [../logs/decision-sessions.md](../logs/decision-sessions.md), session 24.
- Plan: [../plans/p4b-plugins.md](../plans/p4b-plugins.md).
