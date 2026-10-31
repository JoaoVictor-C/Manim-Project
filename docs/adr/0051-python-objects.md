# 0051. Python objects: objects built by the user's own Manim code

- **Status:** Accepted
- **Date:** 2026-10-18
- **Deciders:** João Victor

## Context

Building the Pythagoras proof the user hand-built a right triangle from lines because the
library lacked it, and asked to "just code with Manim CE, click a button and have it
converted". Two escape hatches existed: code layers (ADR 0019: a whole scene played into a
frame cache - a picture, not an object clips act on) and plugins (ADR 0032: a function that
builds an object - but a file in a plugin folder and a restart). P10
([plan](../plans/p10-code-to-objects.md)) adds the missing middle: an object whose construction
code lives in the project.

## Decision

- **Spec:** `Spec(type="Python", params={"code": source, "values": {name: value}})`, a root
  object type. The source defines `PARAMS = {name: default}` and `def build(p)` returning a
  Manim **VMobject**; `p` is the defaults overridden by `values`.
- **`PARAMS` is read without running the code** (`ast.literal_eval` of the top-level
  assignment), so Properties lists the parameters of code that may not run yet. The type
  comes from the default: float, int, bool, text, colour (`#rgb`/`#rrggbb`); a number may be
  `(default, minimum, maximum)`. A non-literal `PARAMS` is an error at its line. Values must
  be of the declared type, within the limits and name a declared parameter (file format
  check); code that cannot be read is accepted and shows its error. Code is at most 64 KB.
- A parameter may instead use a literal descriptor with an explicit type and default. It can
  set `min`, `max`, `step`, `unit`, `label`, and choices; types are float, int, bool, text,
  colour, choice, and 2D point. `HANDLES` maps labels to point parameters or pairs of numeric
  parameters; canvas dragging edits those values within their declared bounds.
- **Trust is the code layers' trust** (ADR 0019): the same sha256 store, the same prompt when
  opening a file (it lists Python objects with code layers), code applied on the Code page or
  added from the starter is trusted, `--trust-code` trusts everything in that process, and an
  exported exact scene (a Python file the user runs) trusts everything. Every process (editor,
  build worker, preview process, export) asks the store itself, re-read when the file changes.
  Untrusted code draws the dashed placeholder (ADR 0027) with "code not trusted yet". The
  trust state is part of the object's build signature (like a media file's stat), so trusting
  rebuilds exactly those objects (`Evaluator.check_media`).
- **Building** runs the code in a fresh namespace with `from manim import *`, `m` (manim),
  `np` and `math`. Like a plugin, the first build of each code in a process is done twice and
  refused when the drawings differ. Any failure - an exception, `SystemExit`, no `build`, not a
  VMobject - is the placeholder with the message and the **line of the user's code** (the
  innermost traceback frame in it). The result is centred on the origin and `Spec.style` is
  applied on top - only what the user set. Builds are cached by the spec JSON, which also keys
  the frame caches.
- **Time limit:** a build is stopped after 10 s by a trace function that checks the clock on
  every Python call and every line of the user's code (`TimeLimit`, not an `Exception`, so
  `except Exception` in the code does not swallow it); cost ~1.6x on a build, only while the
  user's code runs. New trusted code is also built first by the **build worker** (its warm key
  is the code alone, built with the defaults): a build stopped there fails the edit, which is
  dropped with the reason, and a call that never returns to Python is killed by the worker's
  own watchdog (ADR 0015) - the editor never runs that code.
- **Not a library entry:** created from the Code page ("New Python object", a right triangle
  with `angle` and `side`); the Code page lists Python objects with code layers. Run applies
  new code as one undo step, keeping the values of parameters still declared that still fit.
- **Like any object:** clips (the allow-list of any vector object), keys, groups, morphs,
  themes (coloured like a shape; Style can be reset). Parts and child objects are refused.
- **Readable Python export:** each distinct code is written once at the file's top level as the
  user wrote it, `build` renamed `_build_<variable>` and `PARAMS` `<VARIABLE>_PARAMS`; the
  object is `_build_x({...every value...})` then the usual style and transform calls. Code
  whose top-level names would clash with another object's or with Manim's makes the export
  exact, as does an object that draws the placeholder because its code fails.

## Consequences

- Any Manim construction becomes an editable, animatable object without a plugin or restart.
- A project now carries code that runs in the editor process (after trust), unlike code layers.
- The time limit cannot stop a single long C call in-process (only the worker covers that, for
  code applied in the editor).
- Raster results (`ImageMobject`) are refused: vector-only clips need a VMobject.

## Alternatives considered

- **Parse the Python into studio objects** - only a subset of Manim; the code is run instead.
- **Run Python objects in a separate process always** - every value change would cross a process
  boundary and copy the mobject; trust plus a time limit keep the editor responsive.
- **Wrap each code in a function in the export** - re-indents multi-line strings and breaks
  `from x import *`; renaming two names keeps the user's code as written.

## Evidence

- Tests: `tests/core/code/test_python_objects.py`, `tests/ui/code/test_python_objects_ui.py`,
  `tests/processes/test_worker_messages.py::test_new_python_code_stopped_by_its_time_limit_fails_the_request`;
  the slow `test_the_readable_export_renders_what_the_editor_shows` compares rendered frames.
- Plan: [../plans/p10-code-to-objects.md](../plans/p10-code-to-objects.md).
