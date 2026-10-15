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
| G1 | the walkthrough through real menu actions and input events (user actions counted, status messages, warnings, screenshots); `tests/ui/test_golden_path.py` (slow) | lead | the path runs end to end with the checks above |
| G2 | friction found by G1, fixed | lead | the walkthrough's findings closed or listed |
| G3a | readable Python export of keyframed layers: the keyed transform applied on top of each frame's clip state, as the editor does | agent (Opus) | every built-in preset on a square, and `examples/euler.json`, export readable; frames match the editor's |
| G3b | readable export of objects on axes, equation parts, clips on turned or scaled objects | later | the four example projects export readable, or say exactly why not |
| G4 | a 15-minute project benchmark: open, first deep seek, scrub, edit latency, timeline repaint, memory, autosave, export | agent (Sonnet), on mains power | the numbers logged; anything that grows badly fixed or planned |

## Measured before the plan

- None of the four example projects exports as readable code today (blockers: keyframes,
  parts and objects on axes, clips on turned or scaled objects, a code layer).
- 7 of the 32 built-in presets (Pop in, Pulse, Drift up, Bounce, Spin, Grow, Shrink) write
  keyframes, so one of them makes a whole project export in the exact form.
