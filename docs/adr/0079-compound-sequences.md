# 0079. Compound sequences: named clips and keys that move, retime and copy together

- **Status:** Accepted
- **Date:** 2026-10-31
- **Deciders:** João Victor

## Context

A passage of a video is often several clips and keys on several layers - a title fading in while a shape is
drawn and moved - that belong together. Moving it meant picking every piece again (U4b) each time, retiming it
meant moving each piece by hand, and reusing it later in the scene meant copying them one by one. A group
(ADR 0050) is about objects, not their timing; ripple editing (ADR 0071) moves everything after a point, not one
passage. Editable animation recipes (item 16) need the same thing: a named handle on a set of clips and keys.

## Decision

- `Project.sequences: list[Sequence]`. A `Sequence` has an `id` (unique among every id of the project), a `name`,
  an optional `colour` and its members: clips by `(layer, clip)` (clip ids are unique on their layer only) and
  keys by `(layer, track, t)` - one property's key, on its frame.
- **An annotation, not a primitive.** Nothing renders a sequence: the evaluator, the export and the readable
  Python export never read it, and the frame cache treats a change to the sequences alone as changing no frame
  (`sequences` is among the parts that draw nothing). A test renders a project with and without a sequence and
  compares the pixels.
- **Members stay valid by themselves.** The project's validator drops members that are gone - a deleted clip,
  key or layer - and a sequence left with none; because every edit validates the new snapshot, this happens
  inside the edit that removed them, so undo is one step and no edit needs to know about sequences. Edits that
  *move* keys say so: `shift_timing` (and so ripple, timeline drags and Shift Timing) and `retime_keys` carry the
  members of the keys they move (`edits.carried_keys`). A clip or key is in one sequence at most; a file that
  puts one in two is refused. A copied clip or layer is not a member: it is a clip of its own.
- **The core API** (`core/editing/sequences.py`, no Qt), for the timeline and for what builds on it:
  - `Members(clips, keys)` and `members_from_selection(project, selection)` (the timeline's picks, a key pick of
    every property expanded to each property's key);
  - `span(project, sequence)` - its earliest member start to its latest member end (pure);
    `selection_of(sequence)` - its members as a `shift_timing.Selection`; `sequence_of_clip`, `sequence_of_key`;
  - edits, each one `Edit` (one undo step): `make_sequence(project, name, members)` (refused when empty, when a
    member is unknown or already in a sequence), `dissolve_sequence`, `rename_sequence`, `set_sequence_colour`,
    `move_sequence(project, id, delta)` (`shift_timing`: keys on frames, a boundary clip's explicit Appears at
    / Disappears at carried, never below 0 s, refused whole with the schema's reason; the scene grows),
    `retime_sequence(project, id, new_length)` (member starts and clip durations scaled about the sequence's
    start, keys on frames, an explicit lifetime on a member clip's edge scaled with it; refused when two keys of
    one property would share a frame, or with the schema's reason) and `duplicate_sequence(project, id, at)`
    (clips and keys copied on their own layers with fresh clip ids, starting at `at`, as a new sequence named
    "<name> copy"; refused when a copied key lands on a key already there, or with the schema's reason).
- **Timeline.** Each sequence is a thin bar in its colour (the accent by default) with its name, along the top
  of its first member row over its span, and a dashed outline down to its last member row. Only the bar is hit:
  a click picks every member (the first clip is the primary), a drag moves the sequence with `move_sequence`,
  snapping as group drags do (Alt: free), in one undo step.
- **Edit menu.** *Make Sequence from Selection...* names the selected clips and keys (the timeline's picks, or
  the one selected); *Dissolve Sequence* removes the sequence of the selected clip or key, leaving them where
  they are.

## Consequences

- Sequences need nothing from rendering, the beat sheet or ripple; files without sequences save as before.
- Retiming and duplicating have no menu yet: they are in the core API for the recipes (item 16) and later UI.
- A clip moved to another layer leaves its sequence (its reference names the layer).

## Alternatives considered

- **A nested timeline (a real compound clip)** that renders its own clock - a new rendering primitive with its
  own cache and export path, for what is, today, a way to select and move things together.
- **Pruning members in each deleting edit** - every present and future edit would have to remember sequences;
  the validator sees every snapshot once.

## Evidence

- Tests: `tests/core/editing/test_sequences.py`, `tests/ui/timeline/test_sequences_ui.py`.
