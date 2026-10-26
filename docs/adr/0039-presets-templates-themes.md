# 0039. Presets, templates and themes

- **Status:** Accepted
- **Date:** 2026-10-11
- **Deciders:** João Victor

## Context

Real projects repeat themselves: in the explainer 93 of 105 clips share their
kind, duration and ease with another clip, and 30 layers are exactly a FadeIn
then a FadeOut (B52). Each was added by hand. Groups of layers (a section
header) were rebuilt each time, and colours were set one object at a time.

## Decision

- **Library items are data**: JSON files with `format: "manim-studio-library"`,
  `version: 1`, a `kind` (`preset`, `template` or `theme`) and a `name`. Built-ins
  ship with the package (`src/manim_studio/data/library/`); the user's own live in a
  user folder (`MANIM_STUDIO_LIBRARY` overrides it). A file that cannot be read, or
  has a newer version, is skipped with a message (like plugins, ADR 0032).
- **A preset** (category entrance, emphasis, exit or motion) lists clips - kinds
  in order of preference (the first one the object accepts is used, so one
  *Typewriter* writes letters on Text and draws elsewhere), an offset from the
  application time, a duration, an ease and params - and key tracks of `(dt,
  value, ease)` relative to the layer's transform when applied: position as an
  offset, scale as a factor, rotation as a delta, opacity as it is.
  - It is applied to the selected layer **starting at the playhead** (from a
    timeline row's menu: at the clicked time, like *Add clip*), whole or not
    at all: it is refused, with the reason, when no kind fits the object, when the
    object cannot have one of its keys (a graph on axes only fades), when a clip
    would overlap a clip of the layer or of its object, or when it runs past the end.
  - Keys replace keys on the same frames. When a track has no key before the
    playhead and the preset's first value differs from the current one, a key
    holding the current value is added one frame earlier: a track holds its first
    key backwards in time, and nothing before the playhead may change.
  - It is one undo step, and works on parts.
- **A theme** sets the background, text, shape and accent colours. It recolours the
  selected object, or every layer and the background when nothing is selected, by
  kind: text fill; shape stroke and fill (keeping the fill's opacity); graphs,
  connectors and traces in the accent. One undo step; nothing is stored in the project.
- **A template** is a project fragment (layers whose times start at 0) inserted at
  the playhead with fresh ids through the clipboard (ADR 0038), then selected.
  Built-ins: title card, section header, lower third, callout (a box, a label and an
  arrow to its own anchor dot), equation reveal, counter (a Number and a label).
- **Saving**: *Save as Preset* (the selected layer's clips and keys from the
  earliest) and *Save as Template* (the selected object with everything under it)
  write user files.
- **Menus**: *Animate > Apply Preset > category > preset* (also in the timeline's
  row menu), *Add > Templates*, *View > Themes*.
- **Exports**: presets, templates and themes make ordinary clips, keys, layers and
  styles, so both Python forms are unaffected.

## Consequences

- A preset's end position becomes a key: moving the object afterwards edits keys.
- A theme overwrites colours chosen on purpose (scoped to the selection; undoable),
  and new objects keep Manim's colours.
- One layer at a time until multi-select (P6c).

## Evidence

- B52 in [../logs/benchmarks.md](../logs/benchmarks.md).
- Design: [../logs/decision-sessions.md](../logs/decision-sessions.md), session 32.
- Plan: [../plans/p5e-presets.md](../plans/p5e-presets.md).
