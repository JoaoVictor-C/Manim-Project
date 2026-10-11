# Phases 5 and 6 — built-in features, then the studio

- **Status:** Accepted
- **Date:** 2026-10-11
- **Decided in:** [decision session 27](../logs/decision-sessions.md) (Terza, `fast`, confidence 0.90)
- **Input:** the user's direction (built-in functionality first, then UI design and UX "like a real
  studio": presets, handles, workspace tabs like DaVinci Resolve's pages), and what building a real
  95 s explainer exposed (`examples/build_explainer.py`).

## Why this order

The user asked for functionality first. Each Phase 5 slice keeps its UI minimal inside today's
window (a timeline row, a Properties section, a menu item) and keeps its logic in `core` or in
self-contained widgets, so Phase 6 only has to re-host it. Phase 6 then makes one coherent design
pass: the look first (no layout), then the pages (all layout), then canvas interaction.

## Phase 5 — built-in features

| slice | what it delivers | why (from the explainer) |
|---|---|---|
| **P5a** subtitle track | subtitle cues on the project (start, end, text), their own timeline row, edited in Properties and on the timeline; one style for all (size, position, band); drawn over every frame and in the export; import and export `.srt`, an `.srt` beside the exported video | 17 subtitles were separate Text layers with hand-timed fades |
| **P5b** value readouts and connectors | a Number layer whose value is keyed (decimals, prefix, suffix); a connector line or arrow between two layers' points, redrawn every frame (the traced-point machinery of ADR 0033) | the slope readout was faked with 5 morphing formulas; ValueTracker/DecimalNumber and always_redraw were deferred in P4c |
| **P5c** markers and snapping | named markers on the ruler (M at the playhead), snapping of clips, keys, sounds and subtitles to markers and edges, "add a sound effect at this clip's start" | 31 sound cues were timed by hand |
| **P5d** clipboard and safety | duplicate (Ctrl+D), copy and paste (Ctrl+C / Ctrl+V) of layers, clips and sounds; autosave and crash recovery | presets and templates need copies; long sessions need a safety net |
| **P5e** presets and templates | animation presets (bundles of clips and keys applied to a layer: pop in, slide in, typewriter, bounce...), style themes, object templates (title card, lower third, callout); built-ins plus a user folder; Apply menus | no reusable styles or templates |

## Phase 6 — the studio

| slice | what it delivers |
|---|---|
| **P6a** design system | colour tokens, a dark studio stylesheet, an icon set, typography and spacing, applied app-wide; no layout changes |
| **P6b** workspace pages | pages like Resolve's: **Compose** (canvas, layers, timeline, properties), **Animate** (a large keyframe and curve editor), **Code** (code layers in a real editor with highlighting and run output), **Audio** (sounds, subtitles, levels), **Deliver** (export queue and settings, Python export); one app controller shares the document, selection, undo, playback and helper processes |
| **P6c** canvas interaction | on-canvas handles for more properties (line ends, sizes, radii, text boxes), snapping guides, selecting several layers with align and distribute |
| **P6d** polish | a presets browser, preferences, recent files, keyboard shortcuts help, first-run help and tooltips, and the sweep of visual bugs |
| **P6e** release preparation | version, release notes, packaging (nothing is published without the user) |

## Dependencies

- P5b connectors reuse ADR 0033's traced point; P5c extends snapping to the rows P5a adds;
  P5e templates can include subtitles and readouts, so it comes after P5a and P5b.
- P6a before P6b: the look is app-wide and independent of the window's structure, so pages are
  built once in their final style. P6c after P6b: the Compose page owns the canvas.
- Presets apply to one layer in P5e and to every selected layer once P6c adds multi-select.

## Risks

- **P6b, the page refactor.** 39 of the 51 UI test files drive the main window directly
  (`window.project`, `.layers`, `.canvas`, `.selection`, `.properties`, menus by path). The window
  keeps these paths as a compatibility layer over the Compose page, and the unchanged UI suite
  passing is P6b's first acceptance criterion.
- **P6c, multi-select**, reaches the selection, the Layers panel, the timeline, the canvas and
  Properties (mixed values) at once.
- **"Handlers"** is read as on-canvas handles (P6c); to be confirmed with the user.
- Phase 5 UIs are deliberately plain and will move into pages in P6b.

Every slice keeps the usual workflow: a probe when there is something to measure, a Terza
session, an ADR, a plan, tests first, mutation checks, an acceptance test, docs, a merge.
