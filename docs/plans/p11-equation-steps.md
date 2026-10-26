# P11 - Equation steps

- **Status:** P11.1 done; P11.2 later
- **Date:** 2026-10-18
- **Decision:** [ADR 0054](../adr/0054-equation-steps.md)
- **Why:** in the Pythagoras project (P9) the user animated algebra step by step by hand - one
  MathTex per step, Transform clips between them, colouring the parts that changed: "handling
  transformations with MathTex in complex situations can be really mechanical work".

## Goal

Type the steps (or derive them from the first), get a polished animation - one step at a time,
shared terms moving to their new places, new terms standing out - that stays editable afterwards
with the normal tools.

**Clean room:** designed independently from the problem and Studio's own machinery; no
third-party algebra-animation library's code or documentation was consulted.

## Slices

| slice | scope | state |
|---|---|---|
| **P11.1 steps generator** | `core/editing/equation_steps.py` (lines, a small LaTeX tokenizer, operations on both sides of `LHS = RHS`, transition planning), `edits.add_equation_steps` (one MathTex per step, entrance, morphs back to back, highlight of new terms as coloured parts), the Equation steps dialog (Layers > Add, Animate menu) with live checks through the build worker | **done** |
| **P11.2 later** | an optional computer-algebra extra (not a required dependency) for *simplify* and *solve for x* suggestions in the dialog; **highlight and annotate**: braces or brackets under a term with a note ("factor", "+2 both sides") between two steps | open |

## P11.1 as built

- Operations: add, subtract, multiply (`\cdot`), divide (`\frac`), square, square root,
  reciprocal, `\ln`, `e^{...}`, substitute `symbol = value`. "Move a term to the other side" was
  left out on purpose (subtract does it in two visible steps).
- Timing: the first step enters at `start`; every animation lasts the step duration and is
  followed by the hold; the last step stays and the scene grows to hold it.
- The morph is TransformMatchingTex when the steps share a piece, else Transform
  (ReplacementTransform). New runs of a step become part layers coloured with the highlight
  colour (only on matching transitions); runs the parts cannot isolate are skipped and reported.
- The dialog never builds LaTeX in the UI thread: syntax at once, LaTeX through the worker; on a
  computer without LaTeX the steps are added at once as placeholders.
- Tests: `tests/core/editing/test_equation_steps.py`, `tests/core/editing/test_equation_steps_layers.py`,
  `tests/ui/panels/test_equation_steps_ui.py`. No slow test: the frames are compared in-process.
- Mutation check: 56 mutants of the guards (core reading, operations and their parentheses,
  substitution contexts, transition planning, the generator's checks, timing, highlight and
  scene growth, the dialog's checks, `BuildService.check`, the panel's no-LaTeX path, selection
  and free spot). Five survived the first run: four got a test (a sign after an operator, a
  missing argument before `}` or `\right`, `\left(` beside a plain bracket, no worker request
  without LaTeX) and one guard was dead code and went; all the others are killed.

## Not done (P11.1)

- No simplification or solving (P11.2).
- Shared terms are matched by glyph shape at render time (ADR 0020); parts on shared terms
  would steer repeated symbols - left to Parts > Split into terms.
- Free-spot placement measures the steps only once their formulas are warm (else the centre), so
  the editor never builds LaTeX in the UI thread to place them.
