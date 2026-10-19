# 0055. Colour characters: one colour per drawn glyph, applied to a copy of the build

- **Status:** Accepted
- **Date:** 2026-10-18
- **Deciders:** João Victor

## Context

A user asked: "Is there a way to colour independently each character?" ADR 0049 colours a Text's
pieces with Manim's `t2c` (every match of a substring) and an equation's parts one at a time (a part
layer per TeX piece and occurrence). Neither colours many single characters quickly: the two `l`s of
"hello" are one `t2c` piece (every match is coloured), a gradient across an equation would be a part
layer per glyph, and Manim's `[a:b]` slice keys index the typed string, which drifts from what is
drawn as soon as there are spaces or ligatures.

What Manim draws is a list of glyphs: `family_members_with_points()` of the built Text, MathTex or
Tex. Spaces and line breaks draw nothing; a ligature (`ffi`) is one glyph. A Manim script colours a
character with `mob.family_members_with_points()[i].set_color(c)` (the same as `eq[0][i]` for a
one-string MathTex).

## Decision

- A Text, MathTex or Tex has an optional param `glyph_colours`: one entry per **drawn glyph**, in
  the order of the built object's `family_members_with_points()`, each a colour (`#rgb` or
  `#rrggbb`) or `null` (the object's own colour). It is indexed by glyph, not by position in the
  typed string. The layer validates it (a list of at most 5000 colours-or-null, on those three types
  only); `edits.set_glyph_colours` drops trailing nulls and removes the param when nothing is
  coloured, so old files and uncoloured objects save as before. At build time extra entries are
  ignored and missing ones are null, so editing the text never breaks the object.
- The colours are applied in the adapter **to a copy of the plain build** (`_build_cached` of the
  spec without `glyph_colours`, then `colour_glyphs`, which calls `glyph.set_color(c)` per glyph).
  The plain build stays cached: a colour edit runs no LaTeX and no Pango, and the build worker's
  warm key ignores the param (`warm.CACHE_NEUTRAL_PARAMS`). The spec JSON - colours included - is
  still the key of the coloured build, the evaluator's base and the frame cache.
- Order of the colours, from weakest to strongest: the object's `style.fill` and `t2c` (in the build)
  -> `glyph_colours` -> a part layer's own style (ADR 0049, applied by the evaluator on the tree's
  first state) -> a clip that changes colour while it plays (Indicate). Like part colour, the colour
  is in the object before any clip, so FadeIn, Write and morphs carry it and Indicate goes from the
  glyph's colour to its own and back; a morph's target keeps its own glyph colours.
- A theme recolours `style.fill` only: explicit glyph colours win over it and are kept. Freeze to
  shape freezes the built object, so its frozen pieces carry the colours (same pixels). Copy, paste
  and duplicate copy the param as it is.
- `adapter.glyph_count(spec)` and `adapter.glyph_labels(spec)` name the glyphs for the UI: a Text's
  characters without whitespace (ligatures matched to their letters); a TeX glyph's character read
  from dvisvgm's glyph id (`g<font>-<code>`): printable codes exactly, Greek (math) or ligatures
  (text) for 11-31, the minus for 0, "?" otherwise, a rule (fraction bar) as a dash; numbers when
  the walk does not match the glyphs. Labels are hints, never stored.
- **Colour characters...** (Properties object section, Layers context menu, Edit menu) opens a
  dialog that paints the glyph outlines (`adapter.glyph_outlines`) large in their current colours,
  with click / Shift+click / Ctrl+click / rubber band / Ctrl+A / Escape selection, a keyboard-driven
  strip of swatches, and Colour, Clear, Gradient (plain RGB, rounded half up), Rainbow, Alternate and
  Reset all; OK is one undo step "Colour characters". A part's colour wins in the preview as it does
  in the frame. When the object is a placeholder (no LaTeX for a new formula) the dialog says why
  and is disabled.
- The readable Python export writes the adapter's own `colour_glyphs` (via `inspect.getsource`) once
  and calls it after the constructor and the style; no new reason for the exact form.

## Consequences

- One edit colours any characters, including a gradient over a whole equation; no part layers or
  separate objects are needed for colour alone.
- Glyph colours are not layers: a coloured glyph cannot animate on its own (a part can).
- The list follows glyphs, so retyping a text keeps colours by position: inserting a letter shifts
  the colours after it. The dialog shows exactly which glyph has which colour.
- Each new colour list is one more entry in the build cache (a copy of a cached object).

## Alternatives considered

- **Colour in the evaluator only, like part style** (`_styled_base`) — every other consumer of a
  build (freeze, morph targets, thumbnails, the export's reference) would need the same step; the
  adapter copy gives them all the colours while keeping the expensive build cached.
- **Manim's `t2c` slice keys** (`{"[0:1]": RED}`) — they index the string, not the glyphs (spaces
  and ligatures shift them), exist only for Text, and a key per character is heavier than a list.
- **A part layer per glyph** — a tree of hundreds of layers for a gradient, and parts exist only on
  MathTex/Tex.
- **Pass the colours to Manim's constructor** — not a Manim keyword; and it would change the disk
  cache key for a colour edit.

## Evidence

- Tests: `tests/core/test_glyph_colours.py` ("hello"'s two l's, an equation per glyph against
  `set_color`, labels, validation, the edit, the plain build reused, warm key, t2c / fill / part
  composition, Indicate, Write and FadeIn, a morph target, a theme, freeze pixel identity, no LaTeX),
  `tests/core/test_glyph_colour_helpers.py`,
  `tests/core/test_python_export.py::test_glyph_colours_are_plain_code_that_builds_what_the_editor_builds`,
  `::test_readable_glyph_colours_render_what_the_editor_shows` (slow), `tests/ui/test_glyph_colours_ui.py`.
- Mutation check: 41 of 41 mutants of the guards killed (`.cache/mutate_glyphs.py`, not committed).
- Source: Manim `SVGMobject.get_mobjects_from` (the order glyphs are read), dvisvgm's glyph ids.
