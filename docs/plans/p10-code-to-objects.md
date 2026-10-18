# P10 - From Manim code to Studio objects

- **Status:** Done (P10.1: ADR 0051; P10.2: ADR 0052; P10.3: ADR 0053)
- **Date:** 2026-10-18
- **Why:** building the Pythagoras proof the user hand-built a right triangle from lines because they
  needed an object the library lacked, with transforms and clips on it. Asked: "can I just code,
  click a button and have it converted?". Today there are two escape hatches: *code layers* (a whole
  scene played into a frame cache: a picture, not objects - ADR 0019) and *plugins* (a Python
  function that builds an object - but a file in a plugin folder and an editor restart - ADR 0032).

| step | content | acceptance |
|---|---|---|
| P10.1 (done) | **Python object**: a layer whose spec holds construction code (`PARAMS` + `build(p)`) and its values; built in the editor after the project's code is trusted, drawn and animated like any object (transforms, keys, clips, parts-free, groups, themes), parameters as sliders in Properties, errors shown at their line, readable Python export writes the code out; started from the Code page with a template | write code, click Apply: the object is on the canvas; change a slider: it redraws; export Python renders the same frames |
| P10.2 (done) | **Freeze to shape**: turn a Python object (or any object) into plain path data (a `Shape` object: bezier points and styles) that needs no code and runs anywhere | the frozen object draws exactly the same pixels |
| P10.3 (done) | **Import Manim scene**: run a `construct()` under a recorder that watches `add`/`play`/`wait`; each mobject becomes a layer (a matching studio object when the recorder verifies it rebuilds the mobject exactly, else a Shape - not a Python object); known animations become clips with their start and duration; what cannot be expressed (updaters, `ValueTracker`, `always_redraw`) stays a code layer, and the import says which | a plain scene of Create/FadeIn/Write/Transform imports and exports back to equal frames |

## Decisions

- Objects are **not** converted by parsing the Python text: the code is *run* (in P10.3 under a
  recorder), so anything Manim can build works.
- The code must be a pure function of its parameters, as for plugins (checked by building twice);
  random or clock-dependent code is refused with the reason.
- Code runs only after the user trusts it (the same prompt and store as code layers, ADR 0019); an
  untrusted project shows a placeholder.
- Updaters and frame-to-frame state cannot become clips or objects: they stay code layers. Saying so
  in the importer is part of the feature.
- P10.3 keeps the **whole scene** as one code layer when any part of it cannot be reproduced
  exactly (the importer checks every recorded state against the layers); converted objects are
  never mixed with code. A Python-object fallback is not used: a Shape is the exact fallback.
