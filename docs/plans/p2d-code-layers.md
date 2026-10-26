# P2d — Code layers: implementation plan

- **Status:** ✅ Done (2026-10-10) — `tests/acceptance/test_acceptance_p2d.py`
- **Date:** 2026-10-09
- **Decided in:** [decision session 11](../logs/decision-sessions.md) (Terza, `balanced`, confidence 0.90)
- **Evidence:** benchmarks B30, B31 in [../logs/benchmarks.md](../logs/benchmarks.md)
- **ADR:** [0019 — Code layers](../adr/0019-code-layers.md)

## Goal

The escape hatch for what the visual model cannot express: updaters,
`ValueTracker`, `TracedPath`, `always_redraw`. A **code layer** holds a user's
Manim `Scene`; real Manim plays it once, with its own clock, into a frame cache
that the editor composites with the other layers. **Done when** a code layer
drawing an updater-driven `TracedPath` sits under an equation, scrubs randomly
exactly as it plays, exports exactly as the editor shows it, and an untrusted
project runs nothing (acceptance test).

## Model

- `Spec(type="Code", params={"code": "<one Scene subclass>"})` on a root layer:
  spec edit kinds, Properties fields, the project format and clip allow-lists
  work unchanged. `from manim import *` and `numpy as np` are implied.
- No clips (`allowed_clip_kinds("Code") == ()`), no parts, no morphs; lifetime,
  base transform, keyframes and opacity apply.
- Time: `frame = floor((t - lifetime start) * fps)`, held on the last frame.

## Running code

- **Never in the editor process.** A render runs in a single-use **warm spare**:
  a process started in advance that has already imported Manim, takes one job
  on stdin, writes the cache, streams JSON progress, and exits (B30: a cold
  process needs 6.6–8.7 s to its first frame, a warm one ~0.9 s). Spares are
  started lazily while a code layer exists, at most two alive; one job per
  layer is in flight and newer code supersedes it; Cancel and a timeout kill it.
- Capture: a `CairoRenderer` subclass keeps frames instead of writing a video
  (`write_to_movie` off, transparent background, the project's pixel size, fps
  and frame height — editor units and code units coincide).
- The export CLI renders missing code layers inline, only with `--trust-code`.

## Cache

- In the editor's cache dir, beside Manim's own: `code/<key>/`, one file per
  frame holding a zlib'd premultiplied RGBA crop, and an index (offset and size
  per frame, frame count). Key: sha256 of the code, width, height, fps, frame
  height, Manim version and format version.
- Eviction by a size cap (oldest access first), never the open project's keys.
  Export prefers an existing entry (non-deterministic code can differ after an
  eviction — documented).

## Drawing

- The evaluator routes `Code` through its one base-object entry point to a
  `CodeFrame` (a point-less `Mobject` carrying the decoded crop, its offset and
  the layer's matrix and opacity).
- `render_frame` splits capture runs at `CodeFrame`s and paints each crop with
  Cairo between runs (B30: no measurable cost; the matrix and `paint_with_alpha`
  give the layer transform and opacity). A placeholder box when no frames exist.
- Hit-testing by the crop's alpha; the outline is the transformed crop box.

## Trust

Opening a project file must never run its code silently.

- Trust is decided at render time by the code's sha256 against a per-user
  store; code applied in the editor is trusted.
- Opening a project with untrusted code asks once ("runs Python on your
  computer"); untrusted layers draw the placeholder and never run.
- Export passes `--trust-code` only when every code layer is trusted.

## UI

Library entry "Code" with a starter scene; the code in Properties (monospace,
Ctrl+Enter applies), a status line (queued / rendering / ready / error with the
user's line number); stale frames stay while a re-render runs.

## Not in v1

Clips on code layers, looping, parameters passed from the editor into the code,
audio, OpenGL scenes, several scenes per layer.

## Work breakdown

| step | content | acceptance |
|---|---|---|
| P2d.1 | schema rules, code cache (write/read/evict), `CodeFrame`, compositing, hit-test, trust store | hand-built cache composites exactly over and under mobjects; hold; transform; alpha hit; every library type builds through the evaluator |
| P2d.2 | runner (`python -m manim_studio.processes.code_runner`) and CLI | real render of a TracedPath scene; syntax and runtime errors report the user's line; export renders inline only when trusted |
| P2d.3 | render service with warm spares | latency to first frame with a warm spare; supersede; cancel; crash; lazy start |
| P2d.4 | UI: library, editor, status, trust prompt, placeholder, export flag | edits through the UI; untrusted project asks and runs nothing |
| P2d.5 | acceptance + docs | TracedPath under an equation: scrub = play, export = editor |

## Outcome

Done on 2026-10-10. Differences from the plan:

- Manim's camera with a transparent background already holds **premultiplied**
  pixels (Cairo's own surface: `#ff8000` at 50 % reads `[128, 64, 0, 128]`), so
  the cache stores crops as they come; premultiplying again darkened edges.
- With a warm spare, an edit reaches the cache in 0.15-0.24 s for a 1 s scene
  (B31) — faster than expected because the runner writes frames as they come.
- Spares run only while a *trusted* code layer exists (untrusted code never
  needs one), and they have no Qt parent: deleting a just-exited `QProcess`
  through its parent aborted Qt, so the service releases them itself.
- A user's `class Wait(Scene)` shadows Manim's `Wait`; the runner finds the
  scene by identity, not by name.
- The evaluator reads frames from the renderer's cache (one place for both).
- The library section is "Python" (an item and a section both named "Code"
  were ambiguous).
- Code layers have no Style section (fill and stroke mean nothing to them).
