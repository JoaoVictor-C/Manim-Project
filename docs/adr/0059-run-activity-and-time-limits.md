# 0059. Code runs show that they run, and their time limits can be lifted

- **Status:** Accepted
- **Date:** 2026-10-25
- **Deciders:** João Victor

## Context

A code layer renders in another process, from seconds to minutes (the 5-minute physics video of
`examples/angular_momentum/` has scenes of 25-50 s of Manim each). The only sign was a 4 px bar and the seconds
on **Run**, visible on the Code page only, so on any other page there was no hint that a render was going on
or why the picture was a placeholder. Renders are also stopped after 120 s, the build worker after 20 s on a
request and a Python object's build after 30 s: right against an endless loop, wrong for a scene that really
needs ten minutes, with no way past it.

## Decision

- **Show it everywhere.** `ui/style/render_activity.py`: one spinner glyph (a full turn a second) used by
  - a **status-bar indicator** on every page: *spinner Rendering Orbit · 340 frames · 12 s · 1 waiting*
    (*· no time limit* when lifted); hidden when idle; a click opens the layer on the Code page;
  - a **badge on the canvas** (top right) with the same line;
  - the **explorer rows** (accent colour, turning spinner; a waiting row shows ...) and the **tabs** of the
    layers that render;
  - a thicker, accent-coloured progress bar and a spinner on **Run** (*Running... 12.3 s*).
  `CodeRenderService.active()` lists what renders (longest first) and what waits; nothing here changes a
  frame or the project.
- **A switch for the limits.** `core/code/limits.py` holds one process-wide flag, `unlimited()`, and the defaults
  (`RENDER_LIMIT` 120 s, `BUILD_LIMIT` 20 s). The Code page's **No time limit** toggle (next to Run, remembered
  as the option `code_no_time_limit`, applied at startup) lifts all three: the render watchdog, the build
  worker's timeout, and `python_object.time_limit`. The build worker is told in each request (`no_limit`), not
  through its environment, so a worker started before the toggle obeys it. **Cancel** stays: it is how a run
  without a limit ends. Toggling drops the remembered Python builds, since a build the old limit stopped may
  now finish.
- **Not changed:** the command-line `render` never limited code layers; `scene_recorder`'s 60 s import limit is a
  separate import step with its own dialog; a timeout error's hint now points to the switch.

## Consequences

- The editor can sit on a runaway loop forever when the switch is on; the indicator says so (*no time limit*)
  and Cancel works because renders are separate processes. A Python object's endless loop runs in the build
  worker, which Cancel does not reach (it has no process of its own, ADR 0051): the switch is therefore
  an explicit choice, off by default and not saved per project.
- One more timer (100 ms) runs only while something renders.

## Alternatives considered

- **A per-run limit field (seconds).** More knobs for little gain: "no limit" and the defaults cover the cases.
- **A per-layer or per-project limit.** The limit protects the editor, which is a property of the session, not
  of the file; a project must not be able to switch off a safety on someone else's computer.
- **Environment variable to the processes.** A spare started before the toggle would not see it.

## Evidence

- Test: `tests/core/code/test_limits.py`, `tests/ui/style/test_render_activity.py`,
  `tests/ui/services/test_code_render.py::test_no_time_limit_lets_a_long_render_go_on`
- Source: [limits.py](../../src/manim_studio/core/code/limits.py),
  [render_activity.py](../../src/manim_studio/ui/style/render_activity.py)
