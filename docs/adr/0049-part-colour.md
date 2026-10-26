# 0049. Part colour: a part layer's style, and a Text's t2c

- **Status:** Accepted
- **Date:** 2026-10-18
- **Deciders:** João Victor

## Context

The Pythagoras project (P9, row 4) needed one word or one term in a colour. The only way was a
separate object per coloured piece, then morphs to put the equation back together: "mechanical
work". Part layers (ADR 0012) already isolate one span of a MathTex/Tex as glyph indices of the
root's build, but they had no colour. A Pango `Text` has no part layers; Manim colours its pieces
with `t2c={substring: colour}`, which it bakes into the glyphs it builds (and hashes into its own SVG
cache key, `Text._text2hash`).

The plan (decision session 44) asked for the colour to be applied in the evaluator's per-frame member
output, on a copy, so no cache key changes, with a clip's own colour winning while it plays. Two ways
were compared on Indicate over a red part:

- **after the states, per frame**, skipping glyphs under a clip that changes colour: Indicate starts
  from the build's white (its working copy is a copy of the uncoloured state), so the part would jump red -> white when the clip starts and white -> red when it
  ends;
- **before the clips**, on the tree's first state: Indicate goes red -> yellow -> red, exactly as
  `eq[0][3:5].set_color(RED)` before `self.play(Indicate(...))` does in Manim.

## Decision

- A part layer has an optional `style` with the keys `Spec.style` uses (`fill`, `stroke`,
  `fill_opacity`, `stroke_opacity`, `stroke_width`); only part layers may have one, values are
  checked, and it is left out of the saved file when empty.
- The evaluator colours the part's glyphs (its region: a nested part's glyphs too, an inner part's
  colour winning) on a **copy of the root's build**, the tree's state before any clip
  (`Evaluator._styled_base`). Every later state starts from it, so a clip that changes colour wins
  while it plays and the part's colour is back after it; FadeIn, Write and morphs carry the colour.
  The build, its cache and every cache key stay as they were (no LaTeX run for a colour edit).
- A colour edit is a `spec` edit of the part (`edits.classify`): the evaluator drops the whole tree's
  states (not its build), and the frame cache redraws the whole object while it is alive.
- `edits.set_part_style` sets or clears keys; `edits.colour_part` colours the n-th match of a TeX in
  one edit, adding the part layer when there is none. Properties: a part has Fill and Stroke; a
  MathTex/Tex has **Colour a part** (TeX, occurrence, Colour...); Layers has **Colour part...** on an
  equation and **Colour this part...** on a part. A key that no longer matches is orphaned as before
  (the "Not drawn" note) and colours nothing.
- A `Text` takes Manim's own `t2c` in its params (validated: non-empty pieces, `#rrggbb` colours),
  built as `Text(text, t2c=...)`: every match of a piece is coloured (Manim's rule; its `[a:b]` slice
  keys work too). A Text with pieces takes its `style.fill` as `color=`, because `set_fill` afterwards
  would paint over the pieces. Properties lists the pieces (x stops colouring one) and colours
  another (`edits.set_text_colour`).
- The readable Python export writes `Text(..., t2c={...}, color=...)`. A project with parts, coloured
  or not, keeps the exact export (ADR 0031); the style travels in the embedded project.

## Consequences

- Colouring part of an equation no longer needs separate objects; the user's MathTex chains for
  colour alone go away (transforms between equations stay ADR 0020's job).
- A colour edit recomputes the tree's states (one copy, then the clips' `finish()` as idle work),
  like any clip edit; drawing a frame costs nothing more.
- Text pieces are not layers: they cannot animate on their own (an equation's parts can).

## Alternatives considered

- **Per-frame colour after the cached states** (the plan's wording) — the jumps above at the start
  and end of every colour clip, and a different look from the same Manim script.
- **Part layers on Text** — Pango glyph indices do not map to substrings once spaces and ligatures
  go (Manim drops spaces from `Text.text`); `t2c` is Manim's own answer and exports as itself.
- **Colour in the build (markers coloured in LaTeX)** — every colour edit would be a LaTeX run, and
  a no-LaTeX computer could not even show the placeholder's reason any differently.

## Evidence

- Tests: `tests/core/features/test_part_colour.py` (drawing against Manim's `set_color`, Indicate, FadeIn,
  nested parts, the build cache untouched, invalidation, orphans, t2c build and cache, fill beside
  t2c), `tests/core/engine/test_python_export.py::test_a_text_with_coloured_pieces_is_plain_t2c_code_that_builds_what_the_editor_builds`,
  `::test_readable_t2c_code_renders_what_the_editor_shows` (slow), `tests/ui/panels/test_part_colour_ui.py`.
- Plan: [../plans/p9-pythagoras-feedback.md](../plans/p9-pythagoras-feedback.md) (U5).
- Source: Manim `Text._text2hash` (t2c in its cache key), `Text._text2settings` (t2c as Pango colour).
