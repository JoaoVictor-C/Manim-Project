# 0053. Import Manim scenes: record the scene once, rebuild it exactly or keep it as code

- **Status:** Accepted
- **Date:** 2026-10-18
- **Deciders:** João Victor

## Context

"Is it possible to generate Manim Studio objects through Manim CE code, without me doing it by
hand: I just code, click a button and it is converted?" P10.1 (ADR 0051) gave Python objects and
P10.2 (ADR 0052) freezing; P10.3 ([plan](../plans/p10-code-to-objects.md)) imports a whole
`Scene.construct()`. Manim's model differs from the editor's: a mobject is mutated by every
animation and by code between plays, groups are animated whole or member by member, `.animate`
interpolates points in straight lines, AnimationGroups begin their animations together, a
Succession adds its objects again, z-indexes sort the drawing. A translation that is right "most
of the time" would draw other frames than the user's scene without saying so.

## Decision

- **Run, do not parse.** The file is executed in a **separate process**
  (`python -m manim_studio.processes.scene_recorder`, ADR 0019: never in the editor; warmed while the user
  picks the file; killed after **60 s**) under a recorder: a subclass of the user's scene whose
  `add`, `remove`, `add_sound` and `add_subcaption` watch Manim's own, and a renderer that keeps
  the clock and draws nothing (each `play` advances once to its end, Manim's `skip_animations`).
  Everything Manim does happens - later code sees every mobject exactly as Manim leaves it.
- **The recording is plain JSON** (`core/exchange/scene_import.py` needs no Manim): every distinct drawn
  piece as shape data (`adapter.piece_data`); steps in time order - what is drawn (in Manim's
  drawing order, z-index sort included) whenever it changes between plays, user adds and removes,
  plays with each animation flattened out of AnimationGroup/Succession/LaggedStart (its start and
  run time inside the play, when it was *begun*, its target as it began and ended, the Studio clip
  kind, ease and params it maps to), waits, sounds, subcaptions; objects with the user's variable
  name and line; problems with their line.
- **Built-in objects only when verified.** For a Circle, Dot, Square, Rectangle, Triangle, Star,
  Line, Arrow, Text, MathTex or Tex the recorder guesses the params from the object (a radius, a
  text's string and font size), fits size, turn and place to its points, then rebuilds it with
  `adapter.build_mobject` + style + transform and compares every piece: points within 1e-6, the
  same colours and widths. Anything else - or a failed check - is a **Shape** (ADR 0052): the exact
  drawing. MathTex keeps its string (editable equations); it then needs LaTeX to draw, and the
  report says so (Freeze to Shape removes the need).
- **Layers are groups of pieces.** The drawn pieces are split into the fewest groups every object
  the code added, removed or animated is made of (and runs of pieces in each object's order): a
  VGroup animated as one is one layer; its members become layers when the code animates them on
  their own. A layer lives while its pieces are drawn *as the layer would draw them*; code that
  changes them between plays, a removal and a new add, or being brought in front (re-added; a
  Succession adds its objects again) end it and start a new layer (explicit Appears/Disappears
  set only when inference would differ). Layer order: the constraints of every frame, topologically
  sorted.
- **Clips, keys and morphs.** Registered kinds become clips (ease checked numerically against the
  animation Studio would make; params bound by name; a direction made local when the layer is
  turned or scaled). A clip over a group whose parts are layers is split over them only when each
  part is timed by `lag_ratio` as in the whole (Create, Uncreate, DrawBorderThenFill, Write,
  FadeIn/FadeOut without `scale`). `.animate` and other self-transforms become **keys** only when
  the change is a move, a uniform scale or a fade (straight-line interpolation then matches the
  keys' exactly); `Rotate`/`Rotating` become rotation keys about a fixed point of the object (the
  anchor). Transform-like morphs hand the layer off to a new layer (ADR 0005): the morph's target
  is the target object when nothing later depends on how the source was aligned, else the aligned
  source; `TransformFromCopy` plays from a copy layer. Clips are refused on a layer whose transform
  would change them (a Circumscribe on a scaled object...).
- **Verify, never approximate.** Every state the recording holds - each animation's target as it
  begins and ends, what is drawn after each play and between plays - is compared with what the
  layers draw then. **Anything** not reproducible - a recorder problem (updaters, `always_redraw`,
  ValueTracker, camera scenes, custom or unknown animations, FocusOn which the editor plays
  differently, overshooting eases on content clips, keyword arguments that are points), a failed
  check, an order layers cannot follow - makes the **whole scene one code layer** (ADR 0019) with
  the reasons and lines; converted objects are never mixed with it.
- **Product.** File > Import Manim Scene... (chooses the scene when the file has several; asks once
  per file text, TrustStore) adds the layers on top from 0 s as one undo step "Import Manim scene"
  and selects them; the Code page's **Convert to layers** replaces a code layer by its scene from
  the layer's start (refused, with the report, when it must stay code); a non-modal report lists
  what became what. `manim-studio import scene.py [--scene Name] -o project.json` prints the report
  (exit 0 also for a code layer, 2 when the scene cannot run).

## Consequences

- Plain scenes (Create/FadeIn/Write/Transform/`.animate` moves/Rotate/groups) become editable
  layers whose frames are Manim's own; the import of a 27-second scene takes ~3 s (B72).
- A scene with one updater imports as one code layer: predictable, but nothing of it is editable.
  Mixing a convertible prefix with code is a later step.
- Members of a group are separate layers, not a Studio group (ADR 0050 groups have no clips; keys
  per member are exact). MathTex parts animated separately become shapes, not part layers.
- Imported scenes keep Manim units; a project with another frame height shows them at its scale
  (the report says so). Subtitles are not burned in (Manim only writes an .srt).

## Alternatives considered

- **Parse the Python** - only a subset of Manim, and wrong for code that computes positions.
- **Run in the editor process** - user code in the editor (ADR 0019 forbids it) and no way to stop a
  scene that never ends.
- **Approximate what does not fit** (a smooth ease for an unknown one, a fade for `set_opacity`) -
  frames would differ without a word; the import keeps the scene as code instead.
- **Import the convertible prefix and keep the rest as code** - predictable rules for where code
  starts are harder than "all or code"; left for later.

## Evidence

- Tests: `tests/processes/test_scene_recorder.py`, `tests/core/exchange/test_scene_import.py` (scenes recorded with
  every frame Manim draws - pixels - compared with the editor's frames; hand-built recordings; a
  readable export imported back; two slow tests against a real `manim render`),
  `tests/test_import_cli.py`, `tests/ui/services/test_scene_import_ui.py`. Ten guards mutation-checked.
- Benchmark B72 ([logs/benchmarks.md](../logs/benchmarks.md), `benchmarks/bench_scene_import.py`).
- Plan: [../plans/p10-code-to-objects.md](../plans/p10-code-to-objects.md).
