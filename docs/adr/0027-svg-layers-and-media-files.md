# 0027. SVG layers and media files

- **Status:** Accepted
- **Date:** 2026-10-10
- **Deciders:** João Victor

## Context

Logos, icons and diagrams drawn elsewhere could only come in as images, which
cannot be drawn on (Create, Write, DrawBorderThenFill). Media layers also had
two problems: an image edited on disk kept its old build (the cache was keyed by
the spec alone), and a missing file broke every frame the layer was in.

## Decision

- An **`SVGMobject`** layer: a file path and a height. The file's colours are
  kept; style fields, when set, override them. All clip kinds apply, vector ones
  included. MoveAlongPath along an SVG (or any group) follows its **longest**
  drawn path.
- **Media files are tracked by signature** (modification time and size). Builds
  are cached by spec and signature; the evaluator remembers which signature each
  layer was built from, and a changed file is treated as a spec edit of that
  layer. Files are checked when a project loads, when the editor is re-activated
  and from **View → Reload Media** - not on every frame, and without watchers.
- **Missing, unreadable, malformed or empty media never fail** a load, a frame or
  an export: the builder draws a dashed placeholder the layer's size, and the
  editor names the files in the status bar. The export uses the same builder.
- Paths are absolute for now. SVG elements as separate layers come later.

## Consequences

- A frame depends on the media files' contents as well as the project; an edit
  made while an export runs may mix versions.
- A program writing a file while the editor stays focused is only noticed on
  Reload Media.
- Moving a project to another machine shows placeholders until the files are
  re-picked (project-relative paths are a follow-up).

## Evidence

- Measurements: B40 in [../logs/benchmarks.md](../logs/benchmarks.md).
- Design: [../logs/decision-sessions.md](../logs/decision-sessions.md), session 19.
- Plan: [../plans/p3e-svg.md](../plans/p3e-svg.md).
