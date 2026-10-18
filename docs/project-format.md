# Project file format (schema version 1)

A project is one UTF-8 JSON file validated by `manim_studio.core.schema.Project`.
Example: [examples/euler.json](../examples/euler.json). Units are Manim frame
units (the frame is `frame_height` = 8 units tall, origin at the centre, y up);
times are seconds.

## Project

| field | type | default | notes |
|---|---|---|---|
| `schema_version` | int | `1` | bump on breaking changes, with a migration |
| `canvas` | Canvas | | |
| `layers` | Layer[] | `[]` | first = back, last = front |

## Canvas

| field | default | notes |
|---|---|---|
| `width_px`, `height_px` | 1280, 720 | export resolution; also fixes the aspect ratio |
| `fps` | 30 | |
| `background` | `"#000000"` | |
| `frame_height` | 8.0 | Manim units; `frame_width` follows from the aspect ratio |
| `duration` | 5.0 | seconds |

## Layer

| field | type | notes |
|---|---|---|
| `id` | string | unique; referenced by `to_layer` |
| `name` | string | display name |
| `spec` | Spec | the Manim object; `null` on a part layer |
| `parent_id` | string | child layers only: the object (or part) it belongs to — a part, a child object such as a graph, or an object in a group (ADR 0050) |
| `part` | `{"tex": s, "occurrence": n}` | part layers only: the `n`-th match (from 0) of `tex` in the parent's text |
| `base` | Transform2D | static transform when a track has no keyframes |
| `lifetime` | `{"in": s, "out": s}` | optional; inferred from clips when absent (below) |
| `tracks` | `{property: Keyframe[]}` | `position`, `scale`, `rotation`, `opacity` |
| `clips` | Clip[] | must not overlap in time (validated) |
| `style` | `{"fill": c, ...}` | part layers only, optional (left out when empty): the colours of the part's glyphs, the keys of a Spec's `style` (ADR 0049) |

**Lifetime inference:** visible from the start of the first clip if it is an
introducer (Create, Write, FadeIn, …), else from 0 — or from the end of the
morph that targets this layer. Hidden after the first remover (FadeOut,
Uncreate, …) or morph clip on its lane. The lifetime gates everything: a clip
outside the layer's lifetime does not make it visible. A part's lifetime is
clamped to its parent's.

**Part layers** (ADR 0012) animate a piece of a `MathTex`/`Tex` object — one
term of an equation. A part has no spec; it draws the glyphs of its key's span
and moves with its parent (its own transform pivots on its centre). Its clips
may not overlap clips of its ancestors; sibling parts may animate at the same
time. A key that no longer matches after a text edit leaves the part
*orphaned*: kept, but drawn nowhere. Objects with parts can morph and be
morphed into (the whole tree takes part); a part itself cannot morph, and its
clips may not start after its object begins morphing.

A part's `style` colours its glyphs (an inner part's colour wins on its own glyphs) before any
clip plays, as `eq[0][3:5].set_color(...)` does in a Manim script: a clip that changes colour
(Indicate) goes from the part's colour to its own and back (ADR 0049).

```json
{ "id": "b", "name": "b^2", "parent_id": "eq", "part": { "tex": "b^2", "occurrence": 0 },
  "clips": [{ "id": "i", "kind": "Indicate", "start": 1.0, "duration": 1.0 }] }
```

**Child objects** (ADR 0024, 0030) have a `parent_id` and their own `spec` (no
part key): objects on an `Axes` root. A `Graph` plots `expression`; a `Point`
sits at `x`, `y` (axes units); an `Area` fills under `graph` over `x_range`, down
to `bounded_graph` if set; `RiemannRectangles` take `graph`, `x_range`, `dx` and
`sample` (`left`, `right`, `center`); `AxisLabels` take `x_label`/`y_label` and a
`GraphLabel` `graph`, `label`, `x`, `direction` (TeX). `graph` and
`bounded_graph` name a `Graph` on the same axes; deleting that graph deletes
them. All are locked like graphs (below). A graph is plotted in its axes'
coordinates, drawn right after them, moves with them and lives within their
lifetime. It is **locked** to them: its `base` keeps the default position,
scale, rotation and anchor, and only `opacity` may have a track. Its clips
animate it alone; a clip on the axes animates the axes **with** their graphs, as
one object (ADR 0029), so a graph's clips may not overlap the axes' clips. A
graph may morph into another layer (typically another graph); a morph of the
axes takes their graphs along.

```json
{ "id": "sin", "parent_id": "axes", "spec": { "type": "Graph",
  "params": { "expression": "sin(x)", "x_range": [-5, 5] }, "style": { "stroke": "#38bdf8" } } }
```

**Groups** (ADR 0050): a root layer with `"spec": { "type": "Group" }` draws
nothing; the layers whose `parent_id` is the group are its objects, each with
its own `spec`, clips, keys and lifetime, drawn in their list order where the
group is stacked. The group's `base` and `tracks` (position, scale, rotation,
anchor, opacity) apply after each object's own transform, opacities multiplied.
Its lifetime is its own `lifetime` when set, else the span of its objects'
lifetimes, and its objects are clamped to it. A group has no clips and no
parent; its objects are whole plain objects (not parts, not objects on axes, not
objects that have parts or objects on axes, not traced paths or connectors). A
morph's two ends are in the same group or in none, and nothing morphs into a
group or moves along one.

```json
{ "id": "group-1", "name": "Triangles", "spec": { "type": "Group" },
  "base": { "position": [1.0, 0.0], "scale": 0.8 } },
{ "id": "tri-a", "parent_id": "group-1", "spec": { "type": "RightTriangle" } }
```

**Subtitles** (ADR 0035): `subtitles` is a list of cues (`id`, `start`, `end`,
`text`) that never overlap; `subtitle_style` sets how all of them look:
`font_size`, `y` (the centre of a one-line subtitle; more lines grow upwards),
`colour`, `band` with `band_colour` and `band_opacity`, `fade` (seconds),
`burn_in` (drawn into the frames) and `max_width` (longer lines wrap, then
shrink). Both are saved only when used. Ids are unique among layers, sounds and
cues.

```json
"subtitles": [{ "id": "cue-1", "start": 0.5, "end": 2.0, "text": "Hello there" }],
"subtitle_style": { "font_size": 30, "colour": "#facc15" }
```

**Markers** (ADR 0037): `markers` lists named moments for editing: `id`, `t`
(seconds, at least 0), `name` and `colour` (default `#f59e0b`), kept in time
order, never two at the same time (the editor keeps one per frame). They draw
nothing and are saved only when there are some. Ids are unique among layers,
sounds, cues and markers.

```json
"markers": [{ "id": "marker-1", "t": 2.0, "name": "Formula", "colour": "#f59e0b" }]
```

**Camera** (ADR 0048): `camera` is the view the scene is drawn from: `phi`
(0-180), `theta` and `gamma` (-180-180), Manim's `ThreeDCamera` angles in
degrees. The default - `phi` 0, `theta` -90, `gamma` 0, the flat 2D view - is
not saved; a file without `camera` has the default. Everything still lies on the
z = 0 plane: another camera shows the flat scene from that angle.

```json
"camera": { "phi": 60.0, "theta": -90.0, "gamma": 0.0 }
```

**Audio** (ADR 0034): a project may have a list of sounds, saved only when it is
not empty. Each plays `duration` seconds of its file from `offset` (the trimmed
start), beginning at `start` on the timeline, with a `gain` in dB and linear
`fade_in` / `fade_out` (together at most the duration). Ids are unique among
layers and sounds. Sounds are mixed together and cut at the canvas end; a file
that is missing or unreadable is silent.

```json
"audio": [{ "id": "audio-1", "name": "narration", "path": "C:/sounds/voice.mp3",
            "start": 0.5, "offset": 0.0, "duration": 12.4, "gain": -3.0, "fade_in": 0.2, "fade_out": 1.0 }]
```

## Spec

```json
{ "type": "MathTex", "params": { "text": "e^{i\\pi}+1=0", "font_size": 72 }, "style": { "fill": "#facc15" } }
```

- `type`: `Circle`, `Square`, `Rectangle`, `Triangle`, `Line`, `Arrow`, `Dot`,
  `Star`, `Text`, `MathTex`, `Tex`, `DecimalNumber`, `ImageMobject`, `SVGMobject`, `Code`, `Python`, `Shape`,
  `Axes`, `TracedPath`, `Connector`; `Graph`, `Point`, `Area`, `RiemannRectangles`, `AxisLabels`,
  `GraphLabel` (only as children of `Axes`); any type an installed plugin
  provides (ADR 0032, 0033) - without the plugin it is drawn as a placeholder.
- `Code` (ADR 0019) holds Python in `params.code`: one `Scene` subclass
  (`from manim import *` and `numpy as np` are implied). It is rendered once
  into a frame cache, plays from the layer's start and holds its last frame;
  it has no clips. It runs only when trusted on this computer.
- `Python` (ADR 0051) is an object built by the user's own Manim code:
  `params.code` (at most 64 KB) and optional `params.values` (`{name: value}`). The code
  defines at top level `PARAMS = {name: default}` - a float, an int, `True`/`False`, text,
  or a colour (`"#rgb"`/`"#rrggbb"`); a number may be `(default, minimum, maximum)` - and
  `def build(p)`, returning a Manim VMobject, where `p` is the defaults overridden by
  `values`. `PARAMS` is read without running the code (`ast.literal_eval`). Each value
  must be of its parameter's type and within its limits, and name a declared parameter
  (code whose `PARAMS` cannot be read is accepted: the object shows its error). Like any
  root object it can have clips, keys, a style (applied on top of the code's colours, only
  what is set), be grouped and morph; it cannot have parts or children. Its code runs only
  when trusted on this computer; otherwise, or when the code fails, it is the dashed
  placeholder with the reason.

  ```json
  { "type": "Python", "params": { "code": "PARAMS = {\"side\": (3.0, 0.5, 8.0)}\n\ndef build(p):\n    return Square(side_length=p[\"side\"])\n", "values": { "side": 2.0 } } }
  ```
- `Shape` (ADR 0052) is an object frozen into plain vector data (Edit > Freeze to Shape): what
  another object drew, so it needs no code, no trust and no LaTeX. `params.version` is `1`;
  `params.shapes` is a non-empty list, one entry per drawn piece (Manim's
  `family_members_with_points()` order), each with `points` (its cubic bezier control points,
  `[x, y]`, or `[x, y, z]` when any z is not 0; stored centred on the origin, as built),
  `fill` and `stroke` (Manim's rgbas: one colour `[r, g, b, a]` or a gradient's stops
  `[[r, g, b, a], ...]`, each 0 to 1) and `stroke_width`; optionally, when not Manim's default,
  `background` and `background_width` (the stroke drawn under the fill), `sheen_direction`
  (`[x, y, z]`, default `[-1, 1, 0]`) and `sheen_factor`, `joint` (`AUTO`, `ROUND`, `BEVEL`,
  `MITER`), `cap` (`AUTO`, `ROUND`, `BUTT`, `SQUARE`), `z_index`, `shade_in_3d`. At most
  300 000 points; freezing refuses data over 4 MB. Floats are written exactly. `Spec.style`
  applies on top (only what is set), so themes recolour it; it has no other params, parts or
  children.

  ```json
  { "type": "Shape", "params": { "version": 1, "shapes": [ { "points": [[-1.0, 0.0], [-0.33, 0.0], [0.33, 0.0], [1.0, 0.0]], "fill": [0.0, 0.0, 0.0, 0.0], "stroke": [1.0, 1.0, 1.0, 1.0], "stroke_width": 4.0 } ] } }
  ```
- `TracedPath` (ADR 0033) draws where another layer has been: `target` (a layer
  id: not a trace or a code layer), `offset` (`[x, y]` from the target's centre,
  in its units) and `dissipate` (seconds kept, 0 = all). It samples the target
  on every frame from its own start, has no clips and is deleted with its target.
  A plugin *simulation* is stepped once per frame from the layer's start and has
  no clips either.
- `DecimalNumber` (ADR 0036) takes Manim's own keywords: `number` (0),
  `num_decimal_places` (2), `unit` (LaTeX after the number; blank = none),
  `include_sign` (`"yes"` / `"no"`), `font_size` (48). ChangeDecimalToValue clips
  count it.
- `Connector` (ADR 0036) is a line or arrow between two layers, drawn again on
  every frame: `source` and `target` (layer ids: two different layers, not a
  trace, connector or code layer), `ends` (`"edges"`: where the line between the
  two points leaves each drawing's bounding box; `"centres"`: at the points),
  `tips` (`"none"`, `"end"`, `"both"`), `gap` (shortens both ends, default 0.1),
  `source_offset` / `target_offset` (`[x, y]` from each drawing's centre, turned
  and scaled with that layer). Style `stroke` colours the line and its tips,
  `stroke_width` sets its width. It draws nothing while either layer is hidden,
  has no clips and is deleted with either layer.
- `params`: keyword arguments of the Manim constructor. `Text`/`MathTex`/`Tex`
  take their string in `text`; `ImageMobject` takes `path`; `SVGMobject` takes
  `path` and `height` (default 2). Paths are absolute. A file that is missing or
  cannot be read is drawn as a dashed placeholder; the project still opens (ADR 0027).
  A `Text` may take `t2c`, Manim's own `{piece: "#rrggbb"}`: every match of a piece is
  coloured; with `t2c`, the Text's `style.fill` colours the rest (ADR 0049).
- `Axes`: `x_range` / `y_range` as `[from, to]`, `x_step` / `y_step`,
  `x_length` / `y_length` (scene units), `numbers` (`"yes"` / `"no"`).
- `Graph`: `expression`, a function of `x` with numbers, `pi`, `e`,
  `+ - * / **`, unary signs and `sin cos tan exp log sqrt abs` — nothing else is
  accepted (it is parsed, never run as Python); `x_range` (default: the axes').
  Where the function is undefined or leaves the axes' y range the curve is
  split, ending exactly at the edge.
- `style`: `fill`, `fill_opacity`, `stroke`, `stroke_width`, `stroke_opacity`.

The object is built centred on the origin; `base`/`tracks` place it.

## Transform2D

`{"position": [x, y], "scale": 1.0, "rotation": 0.0, "opacity": 1.0}` —
rotation in degrees counter-clockwise; opacity multiplies the object's own opacity.

Optional `"anchor": [x, y]` (default `[0, 0]`, not written when default) is
the point the object rotates and scales about, in its own units: its build
centre for objects, its rest centre for parts, moved by the anchor (ADR 0021).
A point `p` of the drawing lands at `A (p - P) + P + position`, `A` being
rotation × scale and `P` the pivot. The anchor only lives in `base`; it has no
track.

## Keyframe

```json
{ "t": 2.2, "value": [0, 1.2], "ease": { "name": "smooth" } }
```

`value` is `[x, y]` for `position`, a number otherwise. `ease` describes the
segment **leaving** this keyframe: either `{"name": <Manim rate function>}`
(`linear`, `smooth`, `rush_into`, `there_and_back`, `ease_in_out_sine`, …) or
`{"bezier": [x1, y1, x2, y2]}` (CSS `cubic-bezier`; y may overshoot).

Position keys may carry `"in_tangent"` / `"out_tangent"` (`[dx, dy]`, relative
to the key's value; written only when set - ADR 0026). A segment whose first
key has an out tangent or whose second key has an in tangent is the cubic
Bezier `p0, p0 + out, p1 + in, p1`; the ease then gives the fraction of its
length travelled. Segments without tangents are straight, as before.

## Clip

```json
{ "id": "e1-morph", "kind": "Transform", "start": 4.4, "duration": 1.2, "to_layer": "eq2" }
```

| field | notes |
|---|---|
| `id` | unique within the layer |
| `kind` | see table below |
| `start`, `duration` | seconds |
| `ease` | optional Easing; omit to keep the animation's own default (e.g. Indicate's there-and-back) |
| `params` | keyword arguments for the Manim animation; the registered ones (below) are validated, others pass through unverified |
| `to_layer` | morph clips only: the layer this one turns into |

| category | kinds | effect on lifetime |
|---|---|---|
| content (introducer) | Create, Write, DrawBorderThenFill, FadeIn, GrowFromCenter, GrowFromEdge, SpinInFromNothing, SpiralIn, AddTextLetterByLetter | starts it |
| content (remover) | Uncreate, Unwrite, FadeOut, ShrinkToCenter, RemoveTextLetterByLetter | ends it |
| emphasis | Indicate, Wiggle, ApplyWave, Circumscribe, Flash, FocusOn; ChangeDecimalToValue (`DecimalNumber` only: it keeps the new value) | none |
| motion | MoveAlongPath (root objects only; `params.path` names the layer to follow) | none |
| morph | Transform, ClockwiseTransform, CounterclockwiseTransform, FadeTransform, FadeTransformPieces, TransformMatchingShapes, TransformMatchingTex | ends this layer, starts `to_layer` |

`ImageMobject` layers accept no kind that draws paths (Create, Write, Wiggle,
SpiralIn, ...). The letter-by-letter kinds need `Text`; TransformMatchingTex
needs MathTex/Tex at both ends. Circumscribe, Flash and FocusOn are *overlays*:
the object stays as it is and the frame, flash lines or spotlight are drawn with
it, turning and scaling with the layer (ADR 0022).

Registered clip params (ADR 0022):

| kind | param | values |
|---|---|---|
| FadeIn, FadeOut | `shift` | `"UP"`, `"DOWN"`, `"LEFT"`, `"RIGHT"` or `[x, y]`; omitted = no movement |
| GrowFromEdge | `edge` | a direction as above; default `"DOWN"` |
| Indicate | `color`, `scale_factor` | `"#rrggbb"` (default `#FFFF00`); 1–3 (default 1.2) |
| Circumscribe | `shape`, `color` | `"rectangle"` or `"circle"`; a colour |
| Flash, FocusOn | `color` | a colour |
| ChangeDecimalToValue | `target_number` | the value it counts to (default 1); linear unless eased |
| MoveAlongPath | `path`, `rotate` | `path`: the id of another layer (not the object itself or its parts, not a part, code layer or image); a group such as an SVG is followed along its longest path. `rotate`: `"no"` (default) or `"along"` - turn with the path, by its change of direction since the clip's start |

**MoveAlongPath** (ADR 0025) moves the object's centre along the path layer's
shape as it is at the clip's start - its built shape under its transform (and
its axes' for a graph), not its animation. The object jumps to the path's start
when the clip begins and stays at its end afterwards. Deleting the path layer
removes the clips that follow it.

## Validation rules

A file that breaks any of these is rejected on load (CLI exit code 2, an error
dialog in the editor):

- `schema_version` must be supported; layer ids are unique.
- Clips: known `kind`; `start ≥ 0`; `duration > 0`; no overlap on a lane.
- Clip ids are unique within a layer; image layers refuse vector-only kinds
  (Create, Write, DrawBorderThenFill, Wiggle, ...).
- Morph clips must have `to_layer`; other clips must not. The target must exist,
  must not be the layer itself, and may be the target of only one morph.
- Nothing may follow a morph on the same lane (the layer has handed off — ADR 0005).
- Groups (ADR 0050): no clips, no parent, only whole plain objects inside; morphs stay inside one group.
- Canvas sizes, fps, `frame_height` and `duration` are positive; `opacity` in `base` is in [0, 1].
- Cubic-bezier `x1`, `x2` are in [0, 1] (y may overshoot).

## Library files (ADR 0039)

Presets, themes and templates are JSON files: the built-ins in
`manim_studio/library/`, your own in `~/.manim-studio/library` (or the folder in
`MANIM_STUDIO_LIBRARY`). Every file has `"format": "manim-studio-library"`,
`"version": 1`, a `"kind"` and a `"name"`; files with another format or a newer
version are skipped with a message, and one of yours replaces a built-in of the
same kind and name.

- `preset`: `category` (`entrance`, `emphasis`, `exit`, `motion`), optional
  `description`, `clips` (each: `kinds` in order of preference, `offset` from the
  playhead, `duration`, optional `ease` and `params`; no morph or path kinds) and
  `keys` (track name -> list of `dt`, `value`, `ease`): position values are `[x, y]`
  offsets from where the layer is, scale a factor, rotation a delta in degrees,
  opacity as it is.
- `theme`: `background`, `text`, `shape`, `accent` colours.
- `template`: `layers` (a valid project fragment: ids and references inside it,
  times from 0).

```json
{ "format": "manim-studio-library", "version": 1, "kind": "preset", "name": "Pulse",
  "category": "emphasis", "keys": { "scale": [ { "dt": 0, "value": 1.0 },
  { "dt": 0.25, "value": 1.15 }, { "dt": 0.5, "value": 1.0 } ] } }
```

## Clipboard (ADR 0038)

Cut, Copy and Duplicate put a small JSON document on the system clipboard, under
the mime type `application/x-manim-studio+json` and as plain text:

```json
{ "format": "manim-studio-clipboard", "version": 1, "kind": "layers",
  "payload": { "layers": [ ...Layer... ], "outside": { "sq": "Square" } } }
```

| kind | payload |
|---|---|
| `layers` | `layers`: each copied object followed by its parts and child objects, in project order; `outside`: the layers they refer to that were not copied, id -> type (`"part"` for a part) |
| `clip` | `clip`: a Clip |
| `audio` | `sound`: an AudioClip |
| `cue` | `cue`: a Cue |

Paste validates it with the schema and refuses another `format` or a newer
`version`. Pasted layers get fresh ids; a reference to an `outside` layer is kept
only when the destination has a layer with that id and type.

## Recovery files (ADR 0038)

While a project has unsaved changes the editor writes a copy every 30 s to
`<AppData>/recovery/` (`%APPDATA%\Manim Studio\recovery` on Windows;
`MANIM_STUDIO_RECOVERY` overrides it): `<stem>.json` is an ordinary project file
and `<stem>.meta.json` is `{"path": original file or null, "pid": owner process,
"saved_at": seconds since the epoch}`. `<stem>` is the first 16 hex digits of the
SHA-1 of the normalised path plus `-<pid>`, or `untitled-<pid>-<n>`. Both files
are written to a temporary name and moved into place, the sidecar last.

## Compatibility

Readers must reject unknown `schema_version` values. Adding optional fields
does not bump the version; renaming or changing meaning does, with a migration
function in `core/schema.py`.
