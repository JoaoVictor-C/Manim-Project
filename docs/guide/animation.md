# Animation

An object animates in two ways, which combine:

- **Clips** - Manim animations (Write, FadeIn, Indicate, Transform...) on the object's row of
  the timeline. Each object has one lane of clips that do not overlap.
- **Keyframes** - values of its transform (position, scale, rotation, opacity) at given times,
  applied after the clips, with an easing between keys.

The object's **lifetime** decides when it is on screen. By default it appears at its first clip
when that clip brings it in (Write, FadeIn...), when a morph into it ends, or else at 0 s, and it
disappears after its first exit clip (FadeOut, Uncreate...) or morph into another object.
**Appears at** / **Disappears at** in Properties override this (empty = Auto).

## Clips

Right-click an object's row on the timeline and choose **Add clip**: the clip is placed at the
clicked time, where there is room. The menu is grouped:

| group | clips |
|---|---|
| **Appear / disappear** | Create, Uncreate, Write, Unwrite, DrawBorderThenFill, FadeIn, FadeOut, GrowFromCenter, GrowFromEdge, SpinInFromNothing, SpiralIn, ShrinkToCenter, AddTextLetterByLetter and RemoveTextLetterByLetter (Text only) |
| **Emphasis** | Indicate, Wiggle, ApplyWave, Circumscribe, Flash, FocusOn, ChangeDecimalToValue (Number only) |
| **Move** | MoveAlongPath (choose the object whose shape to follow) |
| **Turn into** | Transform, ClockwiseTransform, CounterclockwiseTransform, FadeTransform, FadeTransformPieces, TransformMatchingShapes, TransformMatchingTex (choose the target object) |

Only the clips that work on that kind of object are offered (images, for example, cannot be
written). Circumscribe, Flash and FocusOn draw next to the object without changing it, and work
on single parts of an equation too.

Select a clip (click it) to edit it in Properties: its **Animation** kind, **Start**,
**Duration**, **Easing**, and the options some clips have - the direction a FadeIn/FadeOut
moves (**Moving**), the edge GrowFromEdge grows from, the colour (and scale) of an Indicate, the
colour of a Flash or FocusOn, a Circumscribe's shape (rectangle or circle) and colour, a
ChangeDecimalToValue's target value, a MoveAlongPath's path and **Turn: along** (the object
turns with the path).

On the timeline, drag a clip to move it and its edges to trim it; drags snap (`Alt`: no
snapping, `Escape` cancels). `Delete` or right-click > **Delete ... clip** removes it.

### Turning one object into another

**Add clip > Turn into > *kind* > *target***: the object turns into the target object, which
takes over at the end of the clip (the source disappears there, the target appears). Keys on
either object have no effect during the morph, which always lands exactly on the target. **TransformMatchingTex** (between two equations) flies
terms that appear in both to their new places and fades the rest; terms match by their parts'
TeX where both equations have [parts](objects.md#parts-of-an-equation), and by shape otherwise -
split the equations into terms when a symbol repeats. A part cannot be turned into something
else; its equation can.

**Transform**, **ClockwiseTransform** and **CounterclockwiseTransform** have a **Matching**
choice in Properties (ADR 0056). **Smart**, which new morphs get, pairs the pieces of the two
objects by where they sit in their object, their size and their outline (a letter turns into the
letter nearest its place; the same letter nearby keeps its shape), holes with holes (the hole of
an "o" closes in the middle of a square instead of flying off), and starts each outline where its
points travel least, so a circle does not twist into a square and a square into the same square
turned does not spin at all; corners land on corners. A piece with no partner shrinks to a point
and fades where it would be in the other object (the marks of a right angle melt away), or grows
from one (new letters appear in their place). Colours blend evenly (blue into red does not pass
through a dark purple), and the first and last frames are exactly the two objects. **Classic** is
Manim's own Transform, which pairs everything in order: older projects and imported scenes keep
it. Limits: the matching is by shape and place, not meaning - two different letters still pass
through in-between blobs; an identical letter far away is not flown across (use
TransformMatchingShapes for that); a piece never splits in two. A project with a smart morph is
exported as the exact Python scene. To use the same morph in your own Manim Community scenes,
copy [`examples/smart_transform.py`](../../examples/smart_transform.py): one self-contained file
(needs only `manim` and `numpy`) with `SmartScene.smart_transform(a, b)`; it is generated from the
editor's own code by `scripts/gen_smart_transform.py`.

### Equation steps

To animate algebra one step at a time, choose **Layers > Add > Equation steps...** (or
**Animate > Equation Steps...**) and type the steps, one LaTeX equation per line:

```text
A = L \times L
L = a+b
A = (a+b) \times (a+b)
```

Lines starting with `%` are comments. **Derive the next line** makes a step for you from the last
line (or from the step selected in the preview): pick an operation, type its term and click
**Add line**. The operations work on both sides of the equation's `=`: add, subtract, multiply or
divide by a term, square, square root, reciprocal, natural log, exponential, and **Substitute**
(type `L = a+b`: every `L` becomes `(a+b)`, with parentheses only where they are needed).

The preview lists the steps and, between two steps, the morph they will get: a **matching
morph** (TransformMatchingTex) moves the terms both share to their new places and fades the
rest; a **replacement morph** (Transform) is used when they share nothing. Each line is checked
as you type - a missing brace at once, LaTeX errors a moment later - and **Add steps** stays off
while a line cannot be built. On a computer without LaTeX the dialog says so and the steps are
still added, drawn as placeholders until LaTeX is installed.

The options: **Start** (the playhead), **Step duration** (the first step's entrance and each
morph), **Hold** (how long each step stays still), font size, how the first step enters (Write or
FadeIn), the colour, **Colour new terms** (the terms new in a step get the highlight colour as
coloured [parts](objects.md#parts-of-an-equation); in the next step they are plain again) and
where the steps go. The dialog remembers them.

**Add steps** adds one MathTex per step, named *Step 1*, *Step 2*..., with its clips, as one undo
step, and selects them. They are ordinary objects: move them, change a step's text or a clip's
timing and kind, recolour a part, as with objects you made by hand.

### Moving along a path

**Add clip > Move > MoveAlongPath > *object***: the object travels along another object's
shape (a circle, a graph, a line). In Properties pick another path, and set **Turn** to
**along** to make it turn with the path.

## Presets, themes and templates

- **Presets** are ready-made animations: select one or more objects and choose
  **Animate > Apply Preset > Entrance / Emphasis / Exit / Motion > ...** (32 built in, such as
  Fade in, Pop in, Typewriter, Indicate, Circle it, Focus, Bounce, Spin). The preset plays from the
  playhead, on every selected object, as one undo step. A row's right-click menu has
  **Apply preset** too, at the clicked time.
- **Animate > Browse Presets...** (`Ctrl+Shift+P`, or **Browse presets...** in a row's menu)
  shows every preset as a card that plays on a square while the pointer is over it; filter by
  tab or search, and double-click a card (or press `Enter`) to apply it. The browser stays open
  so you can try others.
- **Animate > Save Animation as Preset...** saves the selected object's clips and keys as your
  own preset (a name and a category).
- Themes and templates: see [Objects](objects.md#themes-and-templates).

## Keyframes

Every object's **Transform** in Properties has position, anchor point, scale, rotation and
opacity. Each keyable property has a **Keys** toggle - the stopwatch:

- **Keys off:** changing the value (in Properties or on the canvas) changes it for the whole
  life of the object.
- **Keys on:** changing it sets a key at the playhead. Turning Keys on sets one key at the
  playhead holding the current value (nothing moves yet); turning it off removes the property's
  keys and keeps the value they gave at the playhead.

Keys show as diamonds on the object's timeline row. Click one to see its values and easing in
Properties; drag it to retime it; `Delete` removes it. Right-click a row for
**Add key at playhead**. Every easing list ends with **Custom curve...**, a curve editor with
two draggable handles and named presets.

### Auto-key

**Edit > Auto-key** (the **Record** button on the Animate page) keys a property the first time
you change it, without turning on its Keys toggle: move the playhead, pose the object, and it
moves there over time - from its value at the object's start to the new value at the playhead.

The rule: auto-key **places** an object instead of animating it when there is nothing to
animate from - when the playhead is at the object's first frame, or when the object has no
entrance yet (no clip, no keys and no Appears at). The status bar then says
"Auto-key: the object was placed...". Give the object an entrance (a clip, a preset or an
Appears at time), move the playhead past its start, and edits become keys.

### Property rows

Click the arrow by an object's name on the timeline (or `Alt+Click` the name) to expand it into
one row per property it can key. Each row shows the value at the playhead, a diamond that keys
or unkeys that property at the playhead, and that property's keys alone: drag them (they snap,
bounded only by their own neighbours), delete them, or right-click one to choose the easing of
the motion that follows it (or **Edit curve...**). Each change is one undo step.

### Motion paths

When the selected object has position keys, its motion path shows on the canvas with a square
per key. Drag a square to move that key; double-click it to make the key smooth (handles appear)
or straight again; drag a handle to bend the path - the other handle of a smooth key turns with
it (hold `Alt` to move one handle only).

## The Animate page

`Shift+2`: the viewer and Properties on top, the **graph editor** in the middle, the timeline at
the bottom. The graph shows the selected object's keys as curves of value over time - x, y,
scale, rotation and opacity, each in its colour. Click property names in the expanded timeline
row to show only those curves (`Shift`/`Ctrl` to add or remove); with none chosen, all are shown.

- Drag a key sideways to retime it, up or down to change its value (`Shift` keeps it on one
  axis, `Escape` cancels).
- Double-click a curve to add a key; `Delete` removes the selected one.
- Right-click between two keys to pick the easing of that stretch, or shape it in the curve
  editor.
- **Frame all** (`A`, or `F` in the graph) shows every key; the wheel zooms time and
  `Ctrl+Wheel` the values.
- **Record** is Edit > Auto-key.

## Markers

Press `M` (**Edit > Add Marker**) to mark the playhead's moment; name it, move it or colour it in
Properties. `[` and `]` jump to the previous / next marker; drag a marker's flag on the ruler.
Right-click the ruler to add a marker there, or a marker to rename or delete it or to add a sound
at it. Drags on the timeline snap to markers.

## Moving many things at once

- **Select several on the timeline:** `Shift+Click` / `Ctrl+Click` adds clips and key diamonds
  (or one property's keys); a drag from empty space draws a selection rectangle; `Ctrl+A` selects
  every clip and key. The status bar counts them.
- **Drag** any selected item to move them all by the same snapped amount (`Alt`: no snapping),
  in one undo step and never before 0 s. A move the file cannot accept (clips overlapping) is
  refused with the reason. `Delete` removes them all; `Escape` keeps only the one Properties shows.
- **Move whole objects:** select objects (in Layers, or `Shift`/`Ctrl` on row names) and drag a
  selected row's lifetime band: their clips, keys and Appears at / Disappears at move together.
- **Edit > Shift Timing...** (`Ctrl+Shift+T`) moves what is selected - objects, a clip, keys, a
  sound, a subtitle or a marker - earlier or later by a number of seconds you type (negative is
  earlier), in one undo step. A first or last clip takes a matching Appears at / Disappears at
  along; a move that would pass 0 s is clamped for the whole selection, an overlap refuses the
  move, and a move that leaves an object's lifetime cutting its own animation is reported.

## Scene length and following the playhead

The scene grows by itself to cover whatever an edit places past its end (with **Grow with
content** on, the default) and never shrinks by itself; **Edit > Fit Length to Content** trims
it. Drag the end line on the ruler to set it by hand; clips, keys and subtitles can be dragged
past the end and the scene grows when you drop them. **View > Follow Playhead** keeps the
playhead in view while you play or scrub; turn it off to keep the timeline where you put it.

## See also

- [Objects](objects.md) - what you can animate
- [The editor](the-editor.md#timeline) - the timeline at a glance
- [Keyboard shortcuts](shortcuts.md)
- [Exporting](exporting.md) - render what you animated
- [User guide index](index.md)
