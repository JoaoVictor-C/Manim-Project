# Objects

Everything on the canvas is an object (a *layer*): it has a type with its own parameters, a
style, a transform (position, anchor, scale, rotation, opacity), a lifetime, and a lane of
animation clips. Objects are added from the **Add** button of the Layers panel (or a
right-click on empty space there: **Add object**); new ones are placed at the centre or, if
that is taken, beside the others, and the new object is selected.

## The object library

| Add menu section | objects | parameters in Properties |
|---|---|---|
| **Shapes** | Circle, Square, Rectangle, Triangle, RightTriangle, Star, Dot, Line, Arrow, Connector | radius, side length, width/height, points, line ends, ... |
| **Text** | Text, MathTex, Tex, Number | the text or LaTeX, font size; Text also font, weight, slant |
| **Media** | Image, SVG | the file (an SVG also its height) |
| **Graphing** | Axes | x and y ranges and tick steps, width, height, numbers |
| **Simulation** | Traced path | the object traced, the point on it, how long the trail lasts |
| **Python** | Code (a code layer) | the Manim code |
| **Templates** | Callout, Counter, Equation reveal, Lower third, Section header, Title card, and your own | - |

Plugins can add more sections (see [Plugins](#plugins)). Every object has a **Style** group
(fill colour and opacity, stroke colour and width) and the **Transform** and **Lifetime**
groups described in [Animation](animation.md#keyframes).

### Right triangle

**Add > Shapes > RightTriangle**: a base length (0.5-8) and the acute angle at the end of the
base (15-75°), with the right angle marked. Fill and colour it like any shape. The readable
Python export writes it out as plain shapes.

### Text and equations

- **Text** is plain text drawn by Manim's `Text` (font, weight, slant). **MathTex** is LaTeX
  math (`a^2 + b^2 = c^2`) and **Tex** LaTeX text (`The \textbf{area}`); both need LaTeX (see
  [Troubleshooting](troubleshooting.md#equations-show-a-dashed-box)). Apply a LaTeX field with
  `Ctrl+Enter`; until it is built, the field shows it in italics.
- **Number** shows a value with a number of decimal places, an optional unit and sign. A
  *ChangeDecimalToValue* clip (in **Add clip > Emphasis**) counts it to another value.

### Parts of an equation

A **part** is a term of a MathTex or Tex that animates on its own - indicate `b^2`, fade one
term out - while still moving with its equation. Select the equation and use the Layers
panel's **Parts** button:

- **Add part...** - type the TeX of the term (for example `b^2`); **Occurrence** in Properties
  picks which one when it repeats.
- **Split into terms** - one part per term.

Parts sit under their equation in Layers and on the timeline and get their own clips and keys.
On the canvas a click selects the whole equation; double-click a term to select it, `Escape`
goes back up. To turn one equation into another, see
[TransformMatchingTex](animation.md#turning-one-object-into-another).

### Colouring part of a text

- **An equation:** Properties has **Colour a part** (the TeX, which occurrence, **Colour...**),
  and Layers has **Parts > Colour part...** (right-click too). Either makes the part if needed
  and sets its colour in one undo step. A part layer also has Fill and Stroke colours of its
  own. The colour is applied before the clips, as Manim's `set_color` would: an Indicate goes
  from the part's colour to its own and back.
- **A Text:** Properties has **Colour a piece** (the text to colour, **Colour...**), stored as
  Manim's own `t2c` and listed there.

## Groups

Select two or more objects and choose **Edit > Group** (`Ctrl+G`); **Edit > Ungroup**
(`Ctrl+Shift+G`) takes them out again, each looking as it did (a group with keys asks to bake
them first). A group draws nothing itself: its position, scale, rotation, anchor and opacity -
base values and keys - carry its objects, which keep their own clips, keys and lifetimes. A
click on one of its objects selects the group, which moves, scales and turns as one;
double-click enters it. Its lifetime is its objects' span unless you set one.

Not yet possible: clips on a group itself, groups inside groups, and equations with parts or
axes with graphs inside a group. A project with groups exports its Python scene in the exact
form ([why](exporting.md#readable-or-exact)).

## Images and SVG drawings

**Add > Media > Image** (PNG, JPG, BMP, GIF) or **SVG** asks for the file. Files are referenced
by their absolute path, not copied into the project. Save a drawing again in another program
and it is redrawn when you come back to the editor (or press `F5`, **View > Reload Media**). A
file that is missing or cannot be read shows as a dashed box and the status bar says which.
The elements of an SVG cannot be animated separately.

## Axes and graphs

1. **Add > Graphing > Axes**, then set the ranges, tick steps, size and numbers in Properties.
2. With the axes selected, **Parts > Add graph...** and type a function of `x`, such as
   `sin(x)`, `x**2/10 - 1` or `exp(-x**2)`. Allowed: numbers, `x`, `pi`, `e`, `+ - * / **` and
   `sin cos tan exp log sqrt abs` - nothing else, and nothing is ever run as Python.
3. **Parts > Add to axes** adds a **Point**, the **Area** under a graph (or between two),
   **Riemann rectangles**, **Axis labels** or a **Graph label**; pick their graph and range in
   Properties.

The graph sits on the axes and moves with them. Double-click a graph on the canvas to edit its
formula and range in Properties. A clip on the axes animates the whole figure (fade it, indicate
it, send it along a path) and the graphs come along; a graph can also be created, or turned into
another graph, on its own. A graph keeps only its opacity as a keyable property.

## Connectors and traced paths

- **Connector:** select an object, then **Add > Shapes > Connector**: a line from the object
  before it (in the Layers order) to it. It follows both as they move; Properties sets its two
  objects, whether it ends at their edges or centres, arrow tips, the gap at its ends and offset points.
  Connectors have no clips of their own.
- **Traced path:** select an object, then **Add > Simulation > Traced path**: it draws where
  that object (or a point offset from its centre) has been; **Fade after** makes the trail fade
  (0 = never). Traced paths have no clips.

## Python objects

A **Python object** is an object built by your own Manim code. It moves, styles, keys,
animates, groups and morphs like any other object, and its parameters become fields in
Properties.

**Create one** on the Code page (`Shift+3`): **New Python object** starts from a right
triangle; the arrow on the button offers templates (**Right triangle**, **Matrix**). Edit the
code and press **Run** (`Ctrl+Enter`); errors show under the editor at their line. Python
objects are listed on the Code page with the code layers (rename with `F2`, delete with
`Delete`). They are not in the Add menu.

**Write one:** the code defines, at top level, `PARAMS` and `build(p)`:

```python
PARAMS = {
    "angle": (30.0, 5.0, 85.0),  # a number with (default, minimum, maximum)
    "side": (3.0, 0.5, 8.0),
    "label": "c",                # text
    "filled": True,              # True/False
    "colour": "#58c4dd",         # a colour: "#rgb" or "#rrggbb"
}


def build(p):
    base = p["side"]
    height = base * math.tan(math.radians(p["angle"]))
    triangle = Polygon(ORIGIN, RIGHT * base, UP * height, color=p["colour"])
    if p["filled"]:
        triangle.set_fill(p["colour"], opacity=0.5)
    return VGroup(triangle, MathTex(p["label"]).next_to(triangle, UP))
```

The rules:

- `PARAMS` maps names to defaults, and the default's type is the field's type: a float, an int,
  `True`/`False`, text, or a colour when the text is `#rgb`/`#rrggbb`. A number may be
  `(default, minimum, maximum)` (all ints make an integer field). `PARAMS` is read **without
  running the code**, so it must be written with plain values only - no expressions or names.
  A file with no `PARAMS` has no parameters.
- `build(p)` gets the defaults overridden by your values and must return a Manim **VMobject**
  (a shape, a text, a `VGroup`) - not an image. The result is centred; Style and Transform apply
  on top.
- The code runs with `from manim import *` already done, and `np` (numpy), `math` and `m`
  (manim) available.
- `build(p)` must draw the same thing every time for the same `p`: the first build is done
  twice and refused when the drawings differ (no unseeded random numbers, no clock).
- A build is stopped after 30 seconds (this counts the LaTeX it waits for). Code is limited to
  64 KB.
- Running new code keeps the values of parameters that still exist and still fit.

**Trust:** code you write or start from a template is trusted on your computer. Opening a
project that contains someone else's Python objects or code layers asks first
("Run code from this project?"); until you trust it, the object is drawn as a dashed placeholder
saying "code not trusted yet". From the command line, `--trust-code` runs it. See
[Troubleshooting](troubleshooting.md#run-code-from-this-project).

**Limits:** no parts or child objects on a Python object. In the readable Python export each
distinct code is written once at the top of the file (`build` renamed `_build_<name>`); code
whose top-level names clash with another object's or Manim's, or code that fails, makes the
export exact.

### Freeze to shape

**Edit > Freeze to Shape** (also **Freeze to Shape** in the Layers right-click menu and a
**Freeze to shape** button in Properties) turns the selected object - a Python object, a shape,
a Text, an equation, an SVG - into a **Shape**: the vector paths and colours it draws now, kept
as data. It draws the same pixels and keeps its place, keys, clips and lifetime, but needs no
code, no trust prompt and no LaTeX, so a finished project plays on a computer without them.
There are no parameters to edit afterwards (Style still recolours it); one undo step turns it
back. Objects that cannot be frozen (placeholders, groups, code layers, images, parts, objects
with clips that need their old type) are refused with the reason in the status bar. (Added in
P10.2, ADR 0052.)

## Import a Manim scene

Already have a Manim Community scene in a `.py` file? **File > Import Manim Scene...** turns it
into layers and clips you can edit like anything built in the editor. The editor asks which
scene to use when the file has several, and asks once, per file text, before it runs the Python in
it ("This runs the Python in ... on your computer").

- **How it works:** the file runs once, in a separate process, under a recorder: Manim plays the
  scene as usual but nothing is drawn or written, and the recorder notes every object that was
  added or removed, every animation with its start, duration and ease, and every wait. The result
  is added on top of your layers from 0 s, as one undo step ("Import Manim scene"), and selected.
- **Objects:** a circle, square, rectangle, triangle, star, dot, line, arrow, text or equation
  becomes the matching object with its parameters, but only when rebuilding it gives the same
  points and colours. Anything else (an arc, an SVG, axes, a `VGroup` animated as a whole) becomes
  an exact [Shape](#freeze-to-shape). A `VGroup` whose members are animated separately becomes one
  layer per member.
- **Animations:** `Create`, `Write`, `FadeIn`, `FadeOut`, `Indicate`, `Circumscribe`, `Flash` and
  the others the timeline has become clips; `Transform`, `ReplacementTransform` and the like become
  morphs; `.animate` that only moves, scales evenly, fades or turns becomes keyframes.
- **When it cannot be redone exactly** - updaters, `always_redraw`, `ValueTracker`, camera scenes,
  custom animation classes, or an `.animate` that does something else - the whole scene stays one
  [code layer](#code-layers) so the frames stay right, and a report says which feature and which
  line caused it. (Mixing converted objects with code is not done yet.)
- **From a code layer:** the Code page's **Convert to layers** does the same for a code layer you
  already have, replacing it in one undo step; it refuses, and shows the report, when the scene
  has to stay code.
- **From the command line:** `manim-studio import scene.py [--scene Name] -o project.json` writes
  the project and prints the report.
- **Equations:** running a scene that has equations needs LaTeX, and imported equations need it to
  be drawn; [Freeze to shape](#freeze-to-shape) removes that need.

## Code layers

A **code layer** holds a whole Manim `Scene` for what the timeline cannot express (updaters,
`ValueTracker`, custom simulations). **Add > Python > Code**, or **New code layer** on the Code
page. Edit it on the Code page (highlighting, line numbers, auto-indent) and press **Run**
(`Ctrl+Enter`): real Manim plays it once in a separate process and the editor shows its
frames, placed, scaled and faded like any layer. Typing alone never runs anything; text not
run yet is kept, marked "Unapplied changes", while you switch layers or pages, and **Revert**
drops it. A render error shows under the editor; click its line number to jump there.

A code layer is a picture, not an object: clips cannot act on it (animate it in its code). The
same trust rules as Python objects apply. Exporting a project with code layers from the command
line needs `--trust-code` for layers not rendered yet.

## Plugins

Plugins add object types written in Python: put a `.py` file that registers a type in
`~/.manim-studio/plugins` (or a folder named in `MANIM_STUDIO_PLUGINS`) and restart the editor.
It appears in the Add menu with its own fields in Properties. Plugins can also add
**simulations** - objects stepped frame by frame - that traced paths can follow. See
`examples/plugins/pendulum.py` and `examples/plugins/swinging_pendulum.py`, and
**Help > Plugins...** for what loaded and what failed. Plugins are code you install yourself,
so they run without asking. Their objects export in the exact Python form.

## The scene and the camera

With nothing selected, Properties shows the **Scene**: length, **Grow with content** (the
scene lengthens by itself when an edit places something past its end, in the same undo step;
it never shrinks by itself), size, frame rate, background and **Fit Length to Content**. On the
timeline the scene's end is a line you can drag on the ruler; the part past it is dimmed.

The **Camera** group (Tilt, Turn, Roll - Manim's phi, theta, gamma - and **Reset Camera**)
views the flat scene from an angle; the default is the flat 2D view. Any other camera is used
in the canvas, the frames rendered ahead and the export, and the Python export writes a
`ThreeDScene`. While it is turned, the canvas has no handles and ignores clicks. There are no
3D objects in this version.

## Themes and templates

- **View > Themes** (Blueprint, Chalkboard, Manim, Midnight, Paper) recolours the selected
  objects, or the whole scene (background included) when nothing is selected.
- **Add > Templates** inserts a ready-made group of objects with their animation at the
  playhead. **Animate > Save Object as Template...** saves the selected object, with everything
  under it, as your own. Your templates and presets live in the user library folder (see
  [where files live](troubleshooting.md#where-files-live)).

## See also

- [Animation](animation.md) - clips, presets, keyframes, morphs
- [The editor](the-editor.md#canvas-gestures) - canvas gestures
- [Exporting](exporting.md#readable-or-exact) - what exports readable
- [Project file format](../project-format.md) - how objects are stored
- [User guide index](index.md)
