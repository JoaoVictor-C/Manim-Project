# GP — The golden path

- **Status:** In progress
- **Date:** 2026-10-15
- **Decided in:** [decision session 42](../logs/decision-sessions.md) (Terza, `fast`, confidence 0.88)
- **Why:** the user asked to make one typical job excellent before adding feature surface,
  to get real Manim code out of the Python export, and for evidence that 10+ minute videos
  hold up.

## The path

Create a typical animation, save, close, reopen and export it:

1. start the editor (the welcome), New;
2. add a title (Text), an equation (MathTex) and two shapes;
3. animate them with presets - from the browser and from a timeline row, one of them
   keyframed (Pop in) - and a clip from the row menu;
4. Arrange them;
5. Save; close the window; reopen from File > Open Recent;
6. export a draft video, and the Python scene.

**Excellent** means, measured:
- the outcome is right: the reopened project equals the saved one; the video has every frame
  and its frames match the editor's; the Python file compiles and renders;
- nothing is logged as a warning or an error, and no exception reaches a Qt slot;
- each step is quick (budgets measured on mains power and logged; the test has generous
  ceilings);
- the friction a script cannot judge is caught on screenshots of every step, reviewed.

## Steps

| step | content | who | acceptance |
|---|---|---|---|
| ✅ G1 | the walkthrough through real menu actions and input events (user actions counted, status messages, warnings, screenshots); `tests/ui/test_golden_path.py` (slow) | lead | the path runs end to end with the checks above |
| ✅ G2 | friction found by G1, fixed (placement, layer names, status hint, cache and save folders, worker teardown) | lead | the walkthrough's findings closed or listed |
| ✅ G3a | readable Python export of keyframed layers: the keyed transform applied on top of each frame's clip state, as the editor does | agent (Opus) | every built-in preset on a square, and `examples/euler.json`, export readable; frames match the editor's - done: a `Keyed` helper draws keys as data, clips play through `KeyedClip` (ADR 0046, B67) |
| G3b | readable export of objects on axes, equation parts, clips on turned or scaled objects | later | the four example projects export readable, or say exactly why not |
| G4 | a 15-minute project benchmark: open, first deep seek, scrub, edit latency, timeline repaint, memory, autosave, export | agent (Sonnet), on mains power | the numbers logged; anything that grows badly fixed or planned |

## Measured before the plan

- None of the four example projects exports as readable code today (blockers: keyframes,
  parts and objects on axes, clips on turned or scaled objects, a code layer).
- 7 of the 32 built-in presets (Pop in, Pulse, Drift up, Bounce, Spin, Grow, Shrink) write
  keyframes, so one of them makes a whole project export in the exact form.

## What the walk found (G1) and what changed (G2)

| finding | fix |
|---|---|
| every new object landed on the centre, on top of the others; Arrange then had nothing to spread | `core/engine/placement.py`: the first object at the centre, the next below, above or beside the others where it fits |
| layers were listed as `text-1`, `mathtex-1` | `Layer.label`: a text's own words until it is renamed |
| "Create a project..." stayed in the status bar after New and after opening a file | cleared once a project is open |
| Manim's cache went to `.cache/manim` under the folder the editor started from; Save and Export suggested that folder for a new project | `ui/session/places.py`: the user's cache folder; the last project's folder, else Documents |
| a worker torn down with the application raised in its restart (seen at script ends) | the late exit is ignored |
| the first Text takes about 1-3 s to appear (its build in the worker; "Building text..." shows) | measured, kept: the status bar says so |
| one keyframed preset (Pop in) makes the Python export exact | G3a |
