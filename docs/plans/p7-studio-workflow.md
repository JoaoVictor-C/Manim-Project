# P7 — Studio workflow

- **Status:** In progress
- **Date:** 2026-10-17
- **Decided in:** [decision session 43](../logs/decision-sessions.md) (Terza, `fast`, confidence 0.90)
- **Evidence:** B64 (the 15-minute scene) and B65 (the 3D camera at the default view) in
  [../logs/benchmarks.md](../logs/benchmarks.md)
- **Why:** the user asked for the video's length to be set (dynamically or by hand), for an
  object's timeline row to select it, for code layers to be renamed and deleted, for a less
  confusing Animate page (researching how other apps do it), for Unity as a reference, and
  whether to prepare for 3D.

## Slices

| step | content | who | acceptance |
|---|---|---|---|
| P7.1 | **Scene settings** (duration, size, fps, background) in Properties when nothing is selected and in Edit > Scene Settings; **dynamic length**: the scene grows to cover anything an edit places past its end (same undo step, never shrinks by itself; Fit Length to Content trims; the end is draggable on the ruler), the timeline lets clips, keys, sounds and subtitles go past the end up to its visible width; **timeline rows select** their object (name or empty row; Shift/Ctrl add); **Code page** rename and delete | lead | each by real input in the window, one undo step each |
| P7.2 | B64's scaling problems: the quadratic timeline rebuild and `Evaluator.invalidate` indexed (first), audio memory and mixing per span, render-ahead eviction in O(log n), a capped evaluator cache, a lower Fit Timeline zoom | agent (Sonnet) | B64 re-run: linear rebuild, a layer move in a 300-layer window well under 50 ms, a 15-minute sound under 200 MB |
| P7.3 | **Animate** like After Effects and Unity: each object's timeline row expands into one sub-row per property (value at the playhead, a key diamond to add or remove a key there, keys dragged in their sub-row on the one time axis), Curves only for the selected sub-rows instead of five overlaid ranges, a Record button (Auto-key) and A to frame all keys | agent (Opus), after P7.2's timeline part | the page explains itself: add, move, ease and delete keys on one property without the graph |
| P7.4 | from Unity: F frames everything, Shift+F frames the selection | lead | |
| P7.5 | **3D preparation**: an ADR ("always 3D-capable, camera fixed for 2D"), a camera in the project (default = today's view), Manim's ThreeDCamera only when the camera differs from the default, a test that default-camera frames stay bit-identical | lead or agent | the showcase renders identically; a tilted camera renders a 3D view |

## Decisions and why

- **Dynamic length** is a post-pass on every edit (one tested function covers clips, keys,
  sounds, cues, presets, paste and templates), never shrinking by itself: a scene that
  shrank would cut an ending silently. The schema already accepts content past the end.
- **Animate**: the timeline already shows one key diamond per row, so a separate dope sheet
  would show every key twice; expanding rows (After Effects' twirl-down, Unity's property
  list) keeps one time axis. Curves stay, but for the chosen properties only - five value
  ranges overlaid on one graph was the main confusion.
- **Unity**: Layers ≈ Hierarchy, Properties ≈ Inspector, the canvas ≈ Scene view already.
  Tool modes (Q/W/E/R/T) are not adopted on a 2D canvas, which shows every handle at once;
  they come with 3D, where gizmos overlap. A Scene view / Game view split comes with 3D too.
- **3D**: measured (B65), Manim's ThreeDCamera at the default orientation draws today's
  scenes pixel-identically at about 25 % more time per frame. So the editor becomes
  3D-capable without slowing 2D: the 2D camera keeps drawing while the camera is the
  default. 3D transforms and objects (P8) come with the first 3D content, not before.
