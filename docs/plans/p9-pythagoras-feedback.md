# P9 - What the Pythagoras project asked for

- **Status:** In progress (U1, U2 and U5 shipped; U3, U4 and U6 planned)
- **Date:** 2026-10-18
- **Decided in:** [decision session 44](../logs/decision-sessions.md) (Terza, `fast`, stopped at confidence 0.84)
- **Why:** the user finished a real 30-second project (`Pythagoras.json`: 10 layers of text, 4 right triangles,
  MathTex transforms, 10 subtitles) and listed what was hard.

| # | the user's note | what was found | slice |
|---|---|---|---|
| 1 | scrolling the timeline moves the view but not the shown frame unless playing; add a lock | the view and the playhead are independent | **U3** *Follow playhead* toggle (view only; the wheel does not scrub) |
| 2 | moving keys/clips by hand; moving a preset means copying its start time into Appears at | Appears at is explicit, so it does not follow the clips | **U4** timeline multi-selection + *Shift timing* with the boundary clip carrying Appears at / Disappears at |
| 3 | right triangles had to be built as a sample | no such object | **U1 done**: Right triangle object (`RightTriangle`, same params as the user's file) |
| 4 | colour just a part of a text; many MathTex only to transform parts | part layers have no style | **U5 done**: part colour (ADR 0049): a part layer's `style`, a Text's `t2c` |
| 5 | auto-key ties a new object's movement to a key at its start | a one-key track at the first frame, or keys at 0 and at the playhead, turned the stopwatch on | **U2 done**: ADR 0018 amended - nothing to animate yet means a base edit |
| 6 | grouping; select several timelines/objects and move them together | no groups; selection of one clip at a time | **U4** (selection) and **U6** (Group, transform-only first) |

## Decisions and why (session 44)

- **U3** is a follow-only lock: the view stays on the playhead on seek, scrub, step and play; a manual scroll
  snaps back on the next move. Scroll-to-scrub would make a wheel turn change time (open question to the
  user: if they meant that, it is a one-line addition).
- **U4**: the selection is typed items (clip, key, row); Shift/Ctrl+click and a rubber band add; dragging any
  selected item moves all by the same snapped delta in one undo step; Edit > Shift Timing... takes a delta.
  The carry rule is only for the *boundary* clip: moving the first clip carries an explicit Appears at when it
  equalled that clip's start, the last clip likewise Disappears at; keys never carry. A partial selection that
  would leave the object ending before its animation gets a warning, not silent invisibility. A delta that
  would take anything below 0 is clamped for the whole selection (never partly applied).
- **U5**: a `style` on part layers (fill/stroke) applied in the evaluator's per-frame member output (on the
  copy, so no cache key changes); a clip's own colour wins while it plays. *As built (ADR 0049):* the
  colour goes on a copy of the build, the tree's state before any clip (no cache key changes), since
  colouring after the states would make Indicate jump from the part's colour to white at its start and back
  at its end; this way it goes red -> yellow -> red, as `set_color` does in Manim. Text pieces use
  Manim's `t2c`.
- **U6**: groups last, the riskiest for the evaluator's trees: transform-only (position, scale, rotation,
  opacity tracks), a collapsible row, no morph across the group boundary, exact export fallback.
- Order: U3 and U4 after P7.3 (the Animate rows rewrite the same timeline), U5 in parallel (evaluator and
  Properties only), U6 last.
