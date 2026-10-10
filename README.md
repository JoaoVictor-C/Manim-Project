# Manim Studio

Animate with [Manim](https://www.manim.community/) the way you would in After
Effects or Premiere: layers, a timeline of animation clips, keyframes and easing
— no Python required. Manim itself renders every frame, so the preview is
exactly what gets exported.

**Status:** early development (0.1). The core engine, video export, the
previewer, an editable timeline with undo, panels to build a scene without JSON
(layers, object library, properties), moving objects on the canvas and
exporting from the editor work — enough to write an equation, move it, morph
it into another, fade it out and export the video without touching code or
JSON. See the [roadmap](docs/roadmap.md).

## Quick start (Windows)

Needs [uv](https://docs.astral.sh/uv/) and, for LaTeX equations, MiKTeX.
Details and troubleshooting: [docs/dev/setup.md](docs/dev/setup.md).

```bash
uv sync
```

Open the example in the previewer (Space play/pause, ←/→ step a frame):

```bash
uv run manim-studio edit examples/euler.json
```

In the timeline: click the ruler to scrub, drag a clip to move it, drag its edge
to trim it (it snaps to frames, clip edges and the playhead; hold Alt to snap to
frames only; Escape cancels), Ctrl+wheel to zoom, Ctrl+Z / Ctrl+Y to undo/redo.
Right-click a row to add an animation clip there, right-click a clip (or press
Delete) to remove it.

In the Layers panel: **Add** creates an object from the library (shapes, Text,
MathTex, Tex, images) on top; Delete removes the selected layer; Up/Down
(Ctrl+] / Ctrl+[) or dragging changes the stacking order; double-click renames.
On the canvas: click an object to select it (Alt+click: the one behind), drag
to move it (Shift: one axis, Escape cancels), arrow keys nudge it (Shift: 10 px).
The selected object has handles: drag a corner to scale it, the round knob to
rotate it (Shift snaps to 10 % / 15°). With **Keys** on for a property
(Properties > Transform), changing it sets a key at the playhead instead; with
**Edit > Auto-key** on, the first change already animates — move the playhead,
pose the object, and it moves there over time.

Keyframes show as diamonds on each timeline row: click one to see its values
and easing in Properties, drag it to retime, press Delete to remove it, or
right-click a row to add a key at the playhead. Any easing list ends in
**Custom curve...**, which opens a curve editor with two draggable handles.

**Parts** animate a piece of an equation on its own: select a MathTex or Tex
layer and use **Parts > Add part...** (type the TeX of the term, e.g. `b^2`) or
**Parts > Split into terms**. Parts sit under their equation in the Layers
panel and the timeline, get their own clips (Indicate a term, fade one out) and
keyframes, and move with the equation. On the canvas a click selects the whole
equation; double-click a term to select it, Esc to go back up.

**Code layers** are the escape hatch for what the timeline cannot express
(updaters, `ValueTracker`, `TracedPath`, simulations): **Add > Python > Code**
creates a layer holding a Manim `Scene`; edit it in Properties and press
Ctrl+Enter. Real Manim plays it once in a separate process and the editor
shows its frames, placed, scaled and faded like any layer. Code runs only if
you trust it: opening a project that contains someone else's code asks first,
and exporting from the command line needs `--trust-code`.

The Properties panel edits the selected layer or clip (a timeline click selects
a clip); each finished field is one undo step, and new LaTeX appears in italics
until it has been built.

**File > Export Video...** (Ctrl+E) renders what you see (saved or not) to MP4
in the background, with progress and Cancel; an existing video is only
replaced once the new one is complete.

Or render from the command line:

```bash
uv run manim-studio render examples/euler.json out/euler.mp4
```

## How it works

Manim's `play()` is a loop of `begin()` → `interpolate(alpha)` → `finish()`. Manim
Studio runs that loop itself from a JSON project, so any frame can be computed at
any time — that is what makes a scrubbable timeline possible.
More in [docs/architecture.md](docs/architecture.md).

## Repository layout

```
src/manim_studio/   application code (core engine, renderers, Qt UI, CLI)
tests/              pytest suite (core, render, ui)
benchmarks/         performance scripts
examples/           example projects
docs/               architecture, file format, ADRs, guides, logs
```

## Documentation

- [Documentation index](docs/README.md)
- [Architecture decision records](docs/adr/README.md)
- [Project file format](docs/project-format.md)
- [Contributing](CONTRIBUTING.md) · [Changelog](CHANGELOG.md)

## License

[MIT](LICENSE) © 2026 João Victor
