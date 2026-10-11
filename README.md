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
MathTex, Tex, images, SVG drawings) on top; Delete removes the selected layer; Up/Down
(Ctrl+] / Ctrl+[) or dragging changes the stacking order; double-click renames.
**Ctrl+wheel** on the canvas zooms about the cursor, the wheel pans (Shift+wheel
sideways), and so does dragging with the middle button; **View > Fit** (Ctrl+0)
and **Actual Size** (Ctrl+1) set the view, which the readout under the canvas
shows. Around the frame, dimmed, you see what lies outside it.
On the canvas: click an object to select it (Alt+click: the one behind), drag
to move it (Shift: one axis, Escape cancels), arrow keys nudge it (Shift: 10 px).
The selected object has handles: drag a corner to scale it, the round knob to
rotate it (Shift snaps to 10 % / 15°). Both turn about the small cross, the
object's **anchor**: Ctrl+drag the cross to move it (Shift snaps to the box's
corners, edge midpoints and centre; Ctrl+double-click centres it) — the object
stays where it is, and from then on rotates and scales about that point, like a
pendulum about its top end. With **Keys** on for a property
(Properties > Transform), changing it sets a key at the playhead instead; with
**Edit > Auto-key** on, the first change already animates — move the playhead,
pose the object, and it moves there over time.

When the selected object has position keys, its **motion path** shows on the
canvas with a square per key: drag a square to move that key, double-click it
to make the key smooth (handles appear) or straight again, and drag a handle to
bend the path - the other handle of a smooth key turns with it (hold Alt to
move one handle only).

While you work, frames are rendered ahead of the playhead in a second process
and kept, so heavy scenes play and scrub smoothly once ready (the readout under
the canvas counts them; *View > Render Ahead* turns this off). Changing
something only re-renders the frames it affects.

Images and SVG drawings are read from their files: save a drawing again in
another program and it is redrawn when you come back to the editor (or press
F5). A file that is missing or cannot be read shows as a dashed box, and the
status bar says which.

Keyframes show as diamonds on each timeline row: click one to see its values
and easing in Properties, drag it to retime, press Delete to remove it, or
right-click a row to add a key at the playhead. Any easing list ends in
**Custom curve...**, which opens a curve editor with two draggable handles.

Clips are added from a row's right-click menu (**Add clip**), grouped into
*Appear / disappear*, *Emphasis* and *Turn into*. Select a clip to change it in
Properties: some have options there — the side a fade moves toward, the edge
something grows from, the colour of an Indicate, a Flash or a Circumscribe
(rectangle or circle). Circumscribe, Flash and FocusOn draw next to the object
without changing it, and work on single terms of an equation too.

**Parts** animate a piece of an equation on its own: select a MathTex or Tex
layer and use **Parts > Add part...** (type the TeX of the term, e.g. `b^2`) or
**Parts > Split into terms**. Parts sit under their equation in the Layers
panel and the timeline, get their own clips (Indicate a term, fade one out) and
keyframes, and move with the equation. On the canvas a click selects the whole
equation; double-click a term to select it, Esc to go back up.

To turn one equation into another, right-click its row on the timeline and
choose **Add clip > Turn into > TransformMatchingTex** and the target equation:
terms that appear in both fly to their new places, the rest fades. Terms match
by their parts' TeX where both equations have them, and by shape otherwise —
split the equations into terms when a symbol repeats.

**Graphs**: add **Axes** from the library (*Graphing*), select them and use
**Parts > Add graph...** with a function of x such as `sin(x)` or
`exp(-x**2)`. The graph sits on the axes and moves with them; animate it like
any layer (Create it, Turn it into another graph). A clip on the axes animates
the whole figure - fade it in or out, indicate it, or send it along a path, and
the graphs come along. Double-click a graph to edit
its formula, range and colour in Properties. **Parts > Add to axes** adds a
point, the area under a graph (or between two), Riemann rectangles, axis labels
or a graph label; pick their graph and range in Properties.

To make something travel along a shape - a dot along a graph, around a
circle - right-click its row and choose **Add clip > Move > MoveAlongPath** and
the layer to follow; the clip's Properties let you pick another path, and
**Turn: along** makes the object turn with the path as it goes.

**File > Export Python...** writes the project as a Manim scene you can keep
working on in code: plain, readable `self.play` code when the timeline allows
it, otherwise a scene that plays the project exactly through Manim Studio (its
header says why). `manim-studio python project.json scene.py` does the same.

**Plugins** add your own objects: put a `.py` file that registers an object
type in `~/.manim-studio/plugins` and restart the editor. It appears in the
library with its own controls in Properties and animates and exports like any
object; see `examples/plugins/pendulum.py` and *Help > Plugins...*. Plugins are
Python code you install, so they run without asking.

**Subtitles**: **Edit > Add Subtitle** (Ctrl+T) adds one at the playhead; type
it in Properties, where one style sets how all subtitles look. They have their
own row on the timeline, and **File > Import / Export Subtitles** reads and
writes `.srt` files. The exported video shows them and gets an `.srt` beside it.

**Sound**: **File > Import Audio...** adds a sound at the playhead. It appears
as a row with its waveform under the layers: drag it to move it, drag its edges
to trim it, and set its gain and fades in Properties. Playing the timeline plays
the sound in sync, and the exported video (and Python scene) carries it.

**Traced paths** draw where something has been: select an object and choose
**Add > Simulation > Traced path** (pick the point it follows and how long the
trail lasts in Properties). Plugins can add **simulations** - objects stepped
frame by frame, such as the swinging pendulum in
`examples/plugins/swinging_pendulum.py` - and traces follow them too.

**Numbers and connectors**: **Add > Text > Number** shows a value; give it a
*ChangeDecimalToValue* clip (in *Emphasis*) to count to another value. Select an
object and choose **Add > Shapes > Connector** to draw a line from the object
before it to it; the line follows both as they move, and Properties sets where
it ends, its arrow tips and its gap.

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
