# 0076. Extract selection as code: selected layers become one code layer that draws the same

- **Status:** Accepted
- **Date:** 2026-10-31
- **Deciders:** João Victor

## Context

A scene often starts with the visual tools and reaches a point where the rest is easier to write by hand: a loop,
an updater, a value tracker. The readable Python export (ADR 0031) already writes a whole project as plain Manim
code, and a code layer (ADR 0019) already plays a Manim scene inside the project. What was missing was turning
part of a project into code in place, so the user goes on in the Code page without retyping what they built.

## Decision

- **Edit > Extract Selection as Code** (and **Extract as Code** in the Layers right-click menu) replaces the
  selected layers with one code layer, in one undo step; the new layer is selected and the Code page shown.
- `core/engine/extract_code.extract_as_code(project, layer_ids)` builds a small project of the selected layers
  (with their parts), their clips, keys and lifetimes moved so its clock starts at 0, the project's canvas, helpers
  and morph matching - and writes it with the readable export. The file's header becomes the extraction's, and its
  `config.` lines go: a code layer is rendered at the project's size and rate on a transparent background.
- **Time:** the code layer starts where the selection first appears (or its first clip or key), moved back to the
  frame grid so the scene's frames fall on the project's frames, and ends where the selection's last layer
  disappears (no end when one stays to the end). Its frames are the frames the layers drew.
- **Place:** the code layer takes the selection's place in the stack, and its objects keep their order inside it.
- **Nothing partial.** It is refused, with every reason, when:
  - the readable export cannot reproduce the selection (`readable_problems`: a camera layer, a pinned label, a
    smart morph, a part, a group, a code layer, a simulated layer...);
  - the project's camera is turned (ADR 0048): the code layer would be a flat picture of a 3D view;
  - a layer that is not selected is drawn between selected ones (it would end up above or below all of them);
  - a layer that is not selected uses a selected one (a morph into it, a path, a connector, a trace, a pin) -
    deleting the selection would delete or change it; or the selection uses a layer that is not selected.
- **Trust (ADR 0019).** The new code is code the editor wrote from the user's own layers, not code that arrived in
  a file, so the window trusts its hash - as it trusts the library's starter scenes - but only when every Python
  object and helper the code embeds (ADR 0051, 0058) was trusted already. Otherwise the code layer is not trusted
  and is asked about like any other; extraction never turns untrusted code into trusted code.

## Consequences

- The code is the readable export's: one variable per layer, `self.play` and `self.wait` in time order, the
  helpers it needs (a keyed layer's `Keyed`) written into it. A test renders a project before and after the
  extraction - shapes, a text, clips and keys - and the frames match.
- The code layer's frames are cached like any code layer's; editing the code renders it again.
- There is no way back to layers from the extracted code except Undo, or Convert to Layers (which plays the scene
  and keeps it as code when it cannot be taken apart).
