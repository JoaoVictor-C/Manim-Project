# 0080. Editable animation recipes: a sequence's animation reused on other layers, its parameters kept

- **Status:** Accepted
- **Date:** 2026-10-31
- **Deciders:** João Victor

## Context

A preset (ADR 0039) reuses one layer's clips and keys, flat: once applied, it is ordinary clips and keys, and
changing how long it lasts or how far apart its parts start means moving each piece. Many reusable animations
involve several layers - a title written while a shape grows, a list whose items come in one after the other -
and what the user wants to change afterwards is a handful of parameters: the whole length, the delay between
layers, which layer plays which part. Compound sequences (ADR 0079) gave a named handle on clips and keys of
several layers; recipes build on it.

## Decision

- **A recipe** is a library item (`kind: "recipe"`, saved with the user's presets as `recipe-<name>.json`,
  loaded by `library.load_library`). It has a `name`, a `description`, ordered **roles** (`slots`) and optional
  defaults `length` and `stagger`. A role is what one layer does: its `offset` from the recipe's start and a
  preset's clips (`PresetClip`) and keys (`PresetKey`), times from the role's own start, key values relative
  to the layer's transform there (position an offset, scale a factor, rotation a delta, opacity as it is).
- **Making one** (`recipes.make_recipe(project, sequence_id, name)`): each layer of the sequence becomes a role,
  in the order the layers start (ties: the order the members are listed). Key values are taken relative to
  the layer's sampled transform at the role's start. A recipe made from several layers whose starts are evenly
  spaced remembers that spacing as its `stagger`. Morphs and moves along a path need another layer and are
  refused.
- **Applying one** (`recipes.apply_recipe(project, recipe, layer_ids, at, length=None, stagger=None)`): the
  first layer takes the first role, and so on - the order of the layers is a parameter. A one-role recipe
  repeats over any number of layers; a recipe of several roles needs exactly that many (refused otherwise,
  saying how many). Each role is applied with `library.apply_preset`, so the same rules refuse it with the
  same reasons (a clip kind the object cannot take - `adapter.allowed_clip_kinds` -, a key it cannot have, a
  clip overlapping one already there), prefixed with the layer's name. The result is **a new sequence** named
  after the recipe whose `recipe` field names it, so it moves, retimes, duplicates and dissolves like any
  sequence. All of it is one `Edit`; the scene grows to hold it when it grows with its content.
- **Parameters.** `stagger` is the delay between the starts of consecutive layers (None: the roles' own
  offsets, 0 for a repeated role). `length` is the length of the whole: every layer's part is stretched by one
  factor, the delays kept, so the latest one ends `length` after the start
  (`sequences.fit_factor`: refused when the delays alone take the whole length). Keys land on frames; two keys
  of one property on one frame are refused.
- **Editing them afterwards** works on any sequence, not only recipes: `sequences.reparameterise_sequence(
  project, id, length, stagger, order)` applies the same rule to the members already there, per layer
  (`restagger_sequence` is it without a length); `retime_sequence` still scales everything, delays included.
  Both are built on one per-layer mapping (`t -> new start + (t - old start) * factor`), which retime uses
  with the same mapping for every layer.
- **Project format.** `Sequence.recipe: str | None`, saved only when set, so files without recipes save as
  before. The recipe itself is not in the project: the sequence carries everything that draws.
- **UI.** Animate > *Make Recipe from Sequence...* (the selected clip's or key's sequence, a name prompt),
  *Apply Recipe* (a submenu of the library's recipes, on the selected layers in the order they were picked,
  at the playhead) and *Recipe Parameters...* (length, delay or "keep the delays", for the selected clip's
  or key's sequence). Each is one undo step; a refusal is shown in the status bar.

## Consequences

- A recipe changes no rendering path: what it adds is clips, keys and a sequence, all of which existed.
- The Presets browser does not list recipes yet; they are in the Animate menu only.
- An applied recipe keeps no link to the recipe file beyond its name: editing the recipe later does not change
  scenes that used it, and a sequence edited by hand keeps its `recipe` name.

## Alternatives considered

- **Re-applying the recipe to change a parameter** (remove the instance, apply again) - it would lose the
  user's own changes to the applied clips (an ease, a param), and needs the recipe file at hand.
- **Length as a plain retime** (scaling the delays too) - simpler, but then the delay and the length cannot
  both be what the user typed.
- **A slot as a placeholder layer id inside clip and key references** - a recipe holds no ids at all: roles
  are positional, which is all the layer order needs.

## Evidence

- Tests: `tests/core/editing/test_recipes.py` (make, apply at 3 s with another length and stagger, a render
  equal to the hand-built animation, the recipe file's round trip, refusals, parameters afterwards),
  `tests/ui/shell/test_recipe_ui.py`.
