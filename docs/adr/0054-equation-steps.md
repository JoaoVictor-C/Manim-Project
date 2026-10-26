# 0054. Equation steps: typed lines become one MathTex per step and morphs between them

- **Status:** Accepted
- **Date:** 2026-10-18
- **Deciders:** João Victor

## Context

In the Pythagoras project the user animated algebra step by step (`A = L \times L`, `L = a+b`,
`A = (a+b) \times (a+b)`, ...) by hand: one MathTex per step, a Transform clip from each to the
next, timing the clips so one step shows at a time, then colouring the terms that changed. Every
piece already existed - morph hand-offs (ADR 0005), TransformMatchingTex keyed by part TeX
(ADR 0020), part colour (ADR 0049) - but putting them together was "really mechanical work".

The feature is designed independently from the problem and Studio's own machinery; no
third-party algebra-animation library's code or documentation was consulted.

## Decision

- **A generator, not a new object type.** `edits.add_equation_steps(project, steps, ...)` returns
  one ordinary edit (one undo step) that adds one MathTex layer per step (`Step 1`, `Step 2`, ...)
  at one position, an entrance clip (Write or FadeIn) on the first, and a morph clip from each step
  to the next (`to_layer`). The first step appears at `start`; every animation lasts
  `step_duration` and is followed by `hold`; the last step stays. Lifetimes are not written:
  they follow from the clips as for any morph (the target appears when the morph ends, the source
  ends there), so exactly one step is visible at a time. The scene grows to hold the last step for
  `hold` when it grows with its content. Afterwards the layers are edited with the normal tools.
- **Plain layers, no group:** a v1 group cannot hold objects with parts, nor morphs between its
  members and the outside (ADR 0050).
- **Pure core** (`core/editing/equation_steps.py`, no Manim, no Qt): a small LaTeX tokenizer and tree
  (tokens, `{}`/`()`/`[]`/`\left...\right` groups, commands with arguments such as `\frac`,
  `\sqrt`, `\text`); `parse_steps` (one equation per non-empty line, `%` comments, at most 40
  steps of 400 characters); `derive(line, operation, term)` on `LHS = RHS` split at its one
  top-level `=` (add, subtract, multiply, divide, square, square root, reciprocal, `\ln`, `e^x`,
  substitute `symbol = value`), with parentheses only where they are needed - a sum is wrapped
  before `\cdot` or `^2`, a single term is not; a substituted value is bracketed where its
  neighbours would change its meaning (`2L` with `L = 3` is `2(3)`, `e^x` with `x = a+b` is
  `e^{a+b}`), and a symbol is a whole token (never the `a` of `\alpha`, never inside `\text{}`).
- **Planning a transition:** both steps are flattened into pieces (tokens, plus the brackets and
  command heads as *structural* pieces); a longest common subsequence, matching each piece as
  early as it can, says what both share. The morph is **TransformMatchingTex** when anything is
  shared (it matches glyphs by shape, so shared terms move to their new places and the rest fades,
  ADR 0020), else **Transform** (Studio's Transform is Manim's ReplacementTransform, ADR 0005).
- **Highlight new terms:** the pieces of a step outside the common subsequence, as runs of whole
  nodes (a fully new `\frac` argument is its content, not its braces; a run never starts or ends
  on `^`/`_`), become part keys `(tex, occurrence)`. With a highlight colour each becomes a part
  layer of that step with `style.fill` (ADR 0049); the next step's copies are plain, so the morph
  carries the colour away. Only TransformMatchingTex transitions are highlighted (a replacement
  has nothing to tell apart). A run whose key would find another place, or that `parts.resolve`
  orphans (e.g. a whole `\frac` as an unbraced superscript), is skipped and reported.
- **UI:** Layers > Add > **Equation steps...** and Animate > **Equation Steps...** open a dialog:
  the lines, **Derive the next line** (operation, term, Add line - from the last line or the
  selected step), a preview with the morph planned between steps, options (start = playhead, step
  duration, hold, font size, entrance, colour, colour new terms, place) remembered in the
  preferences. Each line is checked at once for what needs no LaTeX (unbalanced braces) and through
  the build worker for LaTeX (`BuildService.check`, which also warms the formulas for the edit);
  nothing builds LaTeX in the UI thread. On a computer without LaTeX the dialog says so and the
  steps are added at once (placeholders that say why) instead of waiting for builds that fail.

## Consequences

- A derivation of n steps is one dialog and one undo step instead of n objects, n-1 clips and
  manual timing; the result is the same document the user built by hand.
- The pieces that "stay" are chosen by the plan, but TransformMatchingTex matches glyphs by shape
  at render time: when a symbol repeats, which copy flies where follows glyph order (ADR 0020).
  Making terms parts on both sides would steer it; that is left to the user (Parts > Split into
  terms) to keep the layer list short.
- A highlighted step is built with part markers: one more LaTeX build per highlighted step (the
  worker warms it). A project with parts keeps the exact Python export (ADR 0031).
- No simplification or solving: the operations rewrite strings and do not know algebra.

## Alternatives considered

- **An "equation steps" object type** drawing every step itself - a second morph engine beside
  the evaluator's, and nothing the user could edit with the normal tools afterwards.
- **A computer-algebra dependency** for operations and simplification - a new dependency for a
  first slice that only needs string rewriting; kept for a later, optional slice (P11.2).
- **Parts on every shared term** for matching - a long layer list for every step, and glyph-shape
  matching already moves single-glyph terms well.

## Evidence

- Tests: `tests/core/editing/test_equation_steps.py` (lines, tokens, tree, every operation and its
  refusals, every derived line built by Manim, plans), `tests/core/editing/test_equation_steps_layers.py`
  (layers, clips, timing, lifetimes, scene length, highlight and skipped runs, frames that show
  one step at a time against hand-built MathTex, a highlighted step against the same equation
  coloured with `colour_part`, no LaTeX), `tests/ui/panels/test_equation_steps_ui.py` (dialog, checks
  through a fake worker, remembered options, one undo step, the real window).
- Plan: [../plans/p11-equation-steps.md](../plans/p11-equation-steps.md).
