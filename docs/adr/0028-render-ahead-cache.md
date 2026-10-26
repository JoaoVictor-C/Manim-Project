# 0028. Render-ahead cache

- **Status:** Accepted
- **Date:** 2026-10-10
- **Deciders:** João Victor
- **Amends:** [0009](0009-playback-scheduling.md) (playback samples the frame grid)

## Context

A preview frame at widget size costs 58 ms on the stress scene and 131 ms on a
heavier one (B41): heavy projects play at a few frames per second. The evaluator
is pure Python on the UI thread, so rendering ahead there would block input for
as long as a frame takes.

## Decision

- A long-lived **preview render process** (`python -m manim_studio.processes.preview`)
  with its own evaluator renders frames ahead of the playhead. It starts when a
  project opens, stops with the window, and can be turned off (View → Render
  Ahead). It reads the code cache but never runs code.
- Frames are on the canvas **fps grid**, and playback shows grid frames, as the
  export does. Canvas and process build the camera with one function, so a
  cached frame is the live frame, bit for bit.
- The editor keeps zlib-compressed frames (512 MB), dropping those farthest from
  the playhead. Frames are tagged with the view and project generation they were
  rendered for; others are discarded.
- An edit drops only the frames it can change: the editor diffs the projects and
  drops the lifetimes (before and after) of the changed layers and of what
  depends on them (morph partners, the layer's object, layers moving along it).
  A canvas or view change drops everything; finished code renders and reloaded
  media drop their layers' frames.
- The selection outline is drawn from the selected object alone
  (`Evaluator.object_frame`), so cached frames keep it. A frame not in the cache
  is rendered live, as before.

## Consequences

- Once cached, playback and scrubbing cost a decompress (8-12 ms) whatever the
  scene; editing a late layer keeps the early frames.
- A second Manim process uses memory; projects are kept twice.
- A media file saved between two checks can briefly differ between cached and
  live frames (as for the export, ADR 0027).

## Evidence

- Measurements: B41 in [../logs/benchmarks.md](../logs/benchmarks.md).
- Design: [../logs/decision-sessions.md](../logs/decision-sessions.md), session 20.
- Plan: [../plans/p3f-render-ahead.md](../plans/p3f-render-ahead.md).
