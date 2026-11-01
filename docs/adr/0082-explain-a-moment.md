# 0082. Explain a moment: which layers, clips and keys make the frame, stepped through

- **Status:** Accepted
- **Date:** 2026-10-31
- **Deciders:** João Victor

## Context

Example projects are the quickest way to learn the editor, but a finished scene only shows its result: to see
how a moment was made the user had to scrub, click every layer and read its clips and keys one by one. The
beat sheet (ADR 0073) tells the story beat by beat but not which settings produce a given frame.

## Decision

- `core/editing/explain.py` reads the project and changes nothing:
  - `moments(project)` lists the times where something changes - 0, markers, layers appearing and leaving
    (`Project.lifetime`), clip starts and ends, key times, subtitle starts and ends and sound starts - put on
    frames inside the scene, without repeats, in order, and thinned evenly to 200 (first and last kept).
    `step(times, t, direction)` gives the neighbour.
  - `explain(project, t)` returns an `Explanation`: the visible layers with their type and lifetime (why they
    are shown; never the camera), the running clips with progress 0..1 in time and their easing, the keyed
    properties moving between two different keys with their value at `t` (sampled by the evaluator's own rule,
    imported lazily as `edits` does, so the module stays importable without the engine), the subtitles shown,
    the sounds playing and the beat (`ripple.beats`). Each item has a plain sentence ("Circle is drawn in by
    Create, 40% through, linear easing"); `to_text` writes them under Running, Moving, On screen, Said and
    Heard.
- **Edit > Explain This Moment...** (Ctrl+Alt+E) opens a window beside the editor, not modal. It explains the
  playhead and follows it (`playheadMoved`) and edits (`document.changed`) while shown. **Previous** and
  **Next** move the playhead to the neighbouring moment; clicking an item selects its layer (and its clip) in
  the editor, so the settings can be inspected and changed there - the remix. **Copy as text** puts the
  explanation on the clipboard. One window is kept and raised again.

## Consequences

- It works on any open project, examples included; nothing is stored in the project.
- Progress is in time, not eased; the easing is named beside it. Held keys (equal values either side) are not
  listed as moving.
- Code layers and plugin objects are explained by their layer, clips and keys only: what their code draws is
  not looked into.
