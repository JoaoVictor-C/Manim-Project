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

The round handles on an object's edges change its own size - a rectangle's width
or height, a circle's radius, a text's size (Shift: steps of 4 points) - and the
ones on a line's ends move that end only. Moved objects and dragged handles snap
to the edges and centres of the other objects and of the frame, and a yellow guide
shows where; hold Alt while dragging to place freely, or turn it off with
**View > Snap to Objects** (Ctrl+;).

Shift+click adds objects to the selection (or takes one out), and a drag from an
empty part of the canvas selects everything the rectangle touches; in Layers,
Ctrl+click and Shift+click do the same. Selected objects move, nudge, copy, delete
and take presets and themes together, and **Arrange** lines them up (Align Left,
Centre, Right, Top, Middle, Bottom; a single object aligns to the frame) or spaces
three or more evenly (Distribute).

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

**Markers**: press **M** to mark the playhead's moment (name it in
Properties), jump between markers with **[** and **]**, and drag the flags on
the ruler. Every drag on the timeline snaps to markers and to the edges of
clips, keys, sounds and subtitles (hold Alt to stop it). Right-click a clip to
add a sound at its start or end, or a marker to add one there.

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

**The Animate page** (Shift+2, or *Animate* on the bar at the bottom) shows the
selected object's keyframes as curves of value over time: x, y, scale, rotation and
opacity, each in its own colour, which the legend switches on and off.
- Drag a key sideways to retime it or up and down to change its value (Shift keeps it
  on one axis, Escape cancels).
- Double-click a curve to add a key; Delete removes the selected one.
- Right-click between two keys to pick the ease of that stretch, or shape it in the
  curve editor.
- F fits all keys; the wheel zooms time and Ctrl+wheel the values.

**Presets, themes and templates**: select an object and pick a preset from
**Animate > Apply Preset** (or right-click its timeline row): it plays from the
playhead. **View > Themes** recolours the selection, or the whole scene when
nothing is selected. **Add > Templates** inserts a title card, lower third,
callout and more. Save your own with *Save Animation as Preset* and *Save Object
as Template*.

**Copy, paste and recovery**: **Edit > Duplicate** (Ctrl+D) copies the selected
layer, clip, sound or subtitle right next to it; **Cut / Copy / Paste** (Ctrl+X /
C / V) move them through the clipboard, also into another project or another
Manim Studio window. A layer is copied with its parts or graphs, its keys and
clips, and pastes above the selected layer; a clip pastes onto the selected layer
at the playhead, a sound or subtitle at the playhead. While you have unsaved
changes a recovery copy is written every 30 seconds; if Manim Studio closes
without saving, it offers to restore your work the next time it starts (or when
you open that file).

**Code layers** are the escape hatch for what the timeline cannot express
(updaters, `ValueTracker`, `TracedPath`, simulations): **Add > Python > Code**
creates a layer holding a Manim `Scene`; edit it in Properties and press
Ctrl+Enter. Real Manim plays it once in a separate process and the editor
shows its frames, placed, scaled and faded like any layer. Code runs only if
you trust it: opening a project that contains someone else's code asks first,
and exporting from the command line needs `--trust-code`.

**The Audio page** (the page bar at the bottom, or **View > Pages**) lists the sounds
and the subtitles as tables: double-click a cell to change a sound's start, trim,
duration, gain or fades, or a subtitle's times and text; each change is one undo
step and an invalid one (two subtitles overlapping, fades longer than the sound) is
refused with the reason in the status bar. Pick a subtitle's row to jump to it, and
watch the level meter for the peak and RMS of the sound at the playhead.

The Properties panel edits the selected layer or clip (a timeline click selects
a clip); each finished field is one undo step, and new LaTeX appears in italics
until it has been built.

**File > Export Video...** (Ctrl+E) renders what you see (saved or not) to MP4
in the background, with progress and Cancel; an existing video is only
replaced once the new one is complete.

The **Deliver** page (Shift+5) is the full export: choose the file, a size
(480p to 2160p at your canvas's proportions, or your own), the frame rate, a range
(the whole scene, from-to, or between two markers), the quality and what happens to
subtitles, add it to the queue, and let several exports render one after another
while you keep editing - each uses the project as it was when you added it. It
also previews the Python scene (readable code, or an exact scene and why) and saves it.

Or render from the command line:

```bash
uv run manim-studio render examples/euler.json out/euler.mp4
```

The timeline opens showing the whole scene; **View > Fit Timeline** (Shift+F) brings it
back after zooming (Ctrl+wheel).

Press **F1** (Help > Keyboard Shortcuts) for every shortcut and mouse gesture, with
a search field.

## The look

The editor uses one dark studio theme: neutral greys, a blue accent and Phosphor
icons, with every text measured for contrast. Your project's colours (objects,
background, markers, subtitles) are always shown and exported exactly as you set
them.

**Code page** (Shift+3 in the page bar): code layers get an editor of their own beside the canvas, with
Python highlighting, line numbers and auto-indent. Ctrl+Enter (or Run) trusts and applies the text as
one undo step; typing alone never runs anything, and unapplied text is kept (and marked) while you
switch layers or pages. A render error shows under the editor, and clicking its line number moves
the cursor to that line.

**Preferences** (P6d.1): Manim Studio remembers how you left it - the recent files (File > Open
Recent), the window, the size of every panel on every page, the view toggles (snap to objects,
half-resolution playback, render ahead) and the page you were on, which comes back when you open a
project. Until a project is open the viewer greets you with New, Open..., Open Example and your
recent files. Everything lives in one ini file, `manim-studio.ini` in your user configuration
folder (`MANIM_STUDIO_SETTINGS` moves it); delete it to start fresh.

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
