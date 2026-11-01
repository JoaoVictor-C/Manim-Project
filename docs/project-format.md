# Project file format (schema version 1)

A project is one UTF-8 JSON file validated by `manim_studio.core.model.schema.Project`.
Example: [examples/euler.json](../examples/euler.json). Units are Manim frame
units (the frame is `frame_height` = 8 units tall, origin at the centre, y up);
times are seconds.

## Project

| field | type | default | notes |
|---|---|---|---|
| `schema_version` | int | `1` | bump on breaking changes, with a migration |
| `canvas` | Canvas | | |
| `layers` | Layer[] | `[]` | first = back, last = front |
| `helpers` | Helper[] | `[]` | modules the code imports (ADR 0058); saved only when not empty |
| `code_folders` | `{folder: layer_id[]}` | `{}` | named Code page folders for code layers and Python objects; saved only when not empty |

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
| `visible` | bool | defaults to `true`; `false` hides this layer and its descendants in preview and renders while keeping them editable |
| `spec` | Spec | the Manim object; `null` on a part layer |
| `parent_id` | string | child layers only: the object (or part) it belongs to — a part, a child object such as a graph, or an object in a group (ADR 0050) |
| `part` | `{"tex": s, "occurrence": n}` | part layers only: the `n`-th match (from 0) of `tex` in the parent's text |
| `base` | Transform2D | static transform when a track has no keyframes |
| `lifetime` | `{"in": s, "out": s}` | optional; inferred from clips when absent (below) |
| `tracks` | `{property: Keyframe[]}` | `position`, `scale`, `scale_x`, `scale_y`, `rotation`, `opacity` |
| `clips` | Clip[] | must not overlap in time (validated) |
| `style` | `{"fill": c, ...}` | part layers only, optional (left out when empty): the colours of the part's glyphs, the keys of a Spec's `style` (ADR 0049) |
| `pin` | `{"target": id, "anchor": side, ...}` | Text, MathTex and Tex objects only, optional (left out when not pinned): the label sits by the `anchor` side (`top`, `bottom`, `left`, `right`, `centre`) of the target's drawing at every frame, its position being the offset; `follow_rotation` / `follow_scale` (left out when false) turn and scale it with the target (ADR 0075) |

**Lifetime inference:** visible from the start of the first clip if it is an
introducer (Create, Write, FadeIn, …), else from 0 — or from the end of the
morph that targets this layer. Hidden after the first remover (FadeOut,
Uncreate, …) or morph clip on its lane. The lifetime gates everything: a clip
outside the layer's lifetime does not make it visible. A part's lifetime is
clamped to its parent's.

The separate `visible` setting is a manual layer switch. Hidden layers keep their clips and timing;
turning them visible again restores them without rebuilding their animation.

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
group is stacked. The group's `base` and `tracks` (position, uniform scale,
rotation, anchor, opacity) apply after each object's own transform, opacities
multiplied. Groups do not support independent width and height scale.
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

**Narration** (ADR 0060): a cue can be spoken. `voice` on the project is the voice cues without their own use
(`{ "provider": "edge", "voice": "en-US-AndrewNeural", "rate": 0.91 }`; `rate` is a speed multiplier, 1.0 is
normal), and `pronunciations` maps written text to what is said (`{ "dp/dt": "d p by d t" }`; the subtitle keeps
the written text). A cue may carry `voice` (its own), `audio_id` (the sound made for it: an ordinary entry of
`audio`), `audio_key` (a hash of the voice, speed and spoken text the sound was made from: the sound is stale
when the cue's key now differs) and `pause_before` (seconds of silence before it when the cues follow their
speech). Each is saved only when set. The sounds are plain `audio` clips pointing at files in
`<project name>_voice/`; no provider is needed to open or render the project.

```json
"voice": { "provider": "edge", "voice": "en-US-AndrewNeural", "rate": 0.91 },
"subtitles": [{ "id": "cue-1", "start": 1.6, "end": 3.47, "text": "Watch a figure skater spin.",
                "audio_id": "voice-cue-1", "audio_key": "5b0c1e3f9a2d47e810c6" }]
```

**Markers** (ADR 0037): `markers` lists named moments for editing: `id`, `t`
(seconds, at least 0), `name` and `colour` (default `#f59e0b`), kept in time
order, never two at the same time (the editor keeps one per frame). They draw
nothing and are saved only when there are some. Ids are unique among layers,
sounds, cues and markers.

```json
"markers": [{ "id": "marker-1", "t": 2.0, "name": "Formula", "colour": "#f59e0b" }]
```

**Sequences** (ADR 0079): `sequences` lists named sets of clips and keys that the editor moves, retimes
and copies together: `id` (unique among every id), `name`, an optional `colour` (`#rgb` or `#rrggbb`, the
timeline's bar; the accent when absent), `clips` (`{ "layer", "clip" }`) and `keys` (`{ "layer", "track", "t" }`,
one property's key on its frame). They draw nothing and are saved only when there are some. Members that do not
exist are dropped when the file is read (a sequence left with none goes); a clip or key in two sequences is
refused.

```json
"sequences": [{ "id": "sequence-1", "name": "Intro", "clips": [{ "layer": "title", "clip": "write-1" }],
                "keys": [{ "layer": "dot", "track": "position", "t": 2.0 }] }]
```

**Morph matching** (ADR 0056): `morph_matching` is `"smart"` or `"classic"`: the matching the
Transform clips added from now on start with (a clip's own `match` param decides how it draws).
`"smart"`, the default, is not saved; a file without it has the default.

**Camera** (ADR 0048): `camera` is the view the scene is drawn from: `phi`
(0-180), `theta` and `gamma` (-180-180), Manim's `ThreeDCamera` angles in
degrees. The default - `phi` 0, `theta` -90, `gamma` 0, the flat 2D view - is
not saved; a file without `camera` has the default. Everything still lies on the
z = 0 plane: another camera shows the flat scene from that angle.

```json
"camera": { "phi": 60.0, "theta": -90.0, "gamma": 0.0 }
```

**Helpers** (ADR 0058): `helpers` is a list of modules of the project - plain Python that code
layers, Python objects and other helpers import by name (`import grid_tools`, `from grid_tools
import make_grid`). Each has a `name`, its `code` and an optional `description` (not saved when
empty); the list is saved only when it is not empty, so older files are unaffected. A name is a
Python identifier, not a keyword, unique among the helpers, and must not shadow a module of the
standard library, `manim`, `numpy`, `np`, `math`, `m`, `manim_studio`, `helpers` or a name starting
with `studio_`. At most 50 helpers, each at most 64 KB of code. A helper's code is a program like a
code layer's (ADR 0019): it runs only once its hash is trusted on this computer, and an untrusted
helper fails the import of the code using it (`render --trust-code` trusts helpers too).

```json
"helpers": [{ "name": "grid_tools", "code": "def spacing(n):\n    return 8 / n\n",
              "description": "Grid spacing" }]
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

- `type`: `Circle`, `Ellipse`, `Square`, `Rectangle`, `RoundedRectangle`, `Triangle`, `RightTriangle`,
  `RegularPolygon`, `RegularPolygram`, `Pentagon`, `Hexagon`, `Octagon`, `Nonagon`, `Decagon`, `Rhombus`,
  `Parallelogram`, `Trapezoid`, `Polygon`, `Polyline`, `Star`, `Cross`, `Dot`, `Line`, `DashedLine`,
  `Arrow`, `DoubleArrow`, `Vector`, `CurvedArrow`, `CurvedDoubleArrow`, `Arc`, `ArcBetweenPoints`, `CubicBezier`, `Sector`,
  `Annulus`, `AnnularSector`, `Angle`, `RightAngle`, `BraceBetweenPoints`, `Text`, `MathTex`, `Tex`,
  `DecimalNumber`, `ImageMobject`, `SVGMobject`, `Code`, `Python`, `Shape`, `Axes`, `NumberLine`,
  `NumberPlane`, `ComplexPlane`, `PolarPlane`, `ThreeDAxes`, `Cube`, `Sphere`, `Cylinder`, `Cone`, `Torus`,
  `Prism`, `Tetrahedron`, `Octahedron`, `Dodecahedron`, `Icosahedron`, `TracedPath`, `Connector`; `Graph`, `Point`,
  `Area`, `RiemannRectangles`, `AxisLabels`, `GraphLabel` (only as children of `Axes`); any type an installed plugin
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

  A parameter can instead use a descriptor to choose its editor and metadata:

  ```python
  PARAMS = {
      "radius": {"type": "float", "default": 2.0, "min": 0.2, "max": 5.0, "step": 0.1, "unit": "m", "label": "Radius"},
      "sides": {"type": "int", "default": 6, "min": 3, "max": 12},
      "style": {"type": "choice", "default": "solid", "choices": ("solid", "dashed")},
      "center": {"type": "point", "default": (0.0, 0.0), "min": -5.0, "max": 5.0, "unit": "m"},
      "offset_x": {"type": "float", "default": 0.0, "unit": "m"},
      "offset_y": {"type": "float", "default": 0.0, "unit": "m"},
      "visible": {"type": "bool", "default": True},
      "caption": {"type": "text", "default": "Orbit"},
      "colour": {"type": "colour", "default": "#38bdf8"},
  }
  HANDLES = {"Center": "center", "Anchor": ("offset_x", "offset_y")}
  ```

  Descriptor types are `float`, `int`, `bool`, `text`, `colour` (also `color`), `choice` and
  `point`. `min`/`max` are inclusive numeric bounds; for a point they apply to both coordinates.
  `step` sets the numeric field's increment. `unit` is shown next to numeric and point fields,
  and `label` replaces the parameter's display name. A `choice` needs a non-empty tuple or list
  of distinct text values, including its default. All descriptor values are plain literals.
  `HANDLES` is optional: each label may target one `point` parameter by name, or a pair of
  `float`/`int` parameter names. Dragging a canvas handle updates the value and respects its
  declared bounds. The older `PARAMS` values and paired `HANDLES` declarations remain supported.

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
  A `Text`, `MathTex` or `Tex` may take `glyph_colours` (ADR 0055): a list with one entry
  per **drawn glyph**, in the order of the built object's `family_members_with_points()` -
  spaces and line breaks draw nothing and have no entry, a ligature is one glyph - each a
  colour (`"#rgb"` or `"#rrggbb"`) or `null` for the object's own colour. At most 5000
  entries; extra ones are ignored and missing ones are `null`. It is left out when nothing
  is coloured. It is applied after `style.fill` and `t2c` (it wins on the glyphs it sets),
  before a part layer's `style` (which wins on its glyphs) and before any clip.
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

`scale_x` and `scale_y` are optional independent width and height multipliers;
each defaults to `1.0` and is omitted when default. `scale` remains the uniform
multiplier shared by both axes.

`{"position": [x, y], "scale": 1.0, "scale_x": 1.0, "scale_y": 1.0, "rotation": 0.0, "opacity": 1.0}` —
rotation in degrees counter-clockwise; opacity multiplies the object's own opacity.

Optional `"anchor": [x, y]` (default `[0, 0]`, not written when default) is
the point the object rotates and scales about, in its own units: its build
centre for objects, its rest centre for parts, moved by the anchor (ADR 0021).
A point `p` of the drawing lands at `A (p - P) + P + position`, `A` being
rotation × `diag(scale * scale_x, scale * scale_y)` and `P` the pivot. The
anchor only lives in `base`; it has no track.

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
| Transform, ClockwiseTransform, CounterclockwiseTransform | `match` | `"classic"` (default when absent: Manim's own Transform) or `"smart"` (pieces, holes and start points paired by the editor, colours blended in OKLab, exact ends; ADR 0056). Read by the editor, never passed to Manim. The editor writes `"smart"` on morphs it creates; scene imports and older files have none |

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
- Helpers (ADR 0058): valid, unique names that shadow no reserved module; at most 50; code at most 64 KB.
- Canvas sizes, fps, `frame_height` and `duration` are positive; `opacity` in `base` is in [0, 1].
- Cubic-bezier `x1`, `x2` are in [0, 1] (y may overshoot).

## Bundles (ADR 0077)

File > Export Bundle... writes a project and the files it uses as one zip file with the extension `.msbundle`:

| entry | what |
|---|---|
| `manifest.json` | `{"format": "manim-studio-bundle", "version": 1, "app_version", "name", "created", "project", "files", "snapshots"}` |
| `project.json` | the project; every carried file's path is `assets/<name>` |
| `assets/<name>` | each file the project uses (a sound's `path`, an `ImageMobject`/`SVGMobject`'s `params.path`), once |
| `snapshots/<id>.json`, `snapshots/<id>.meta.json` | optional: the project's snapshots (ADR 0068), paths rewritten the same way |

`project` is `{"path": "project.json", "sha256", "size"}`. Each entry of `files` is `{"path": "assets/<name>" or
null, "sha256", "size", "original": the path in the project, "used_by": [{"kind": "audio" or the layer type, "id",
"name", "snapshot"?}], "missing": bool}`; a missing file has no `path` and keeps its original path in the project.
`snapshots` entries are `{"path", "sha256", "size"}`. Opening a bundle refuses entries that are absolute or contain
`..`, entries the manifest does not list, a newer `version`, more than 4 GB unpacked, and any sha256 that does not
match; it unpacks into a new folder and rewrites the paths to the unpacked files (absolute, as in any project). A
bundle carries no code trust.

## Library files (ADR 0039)

Presets, themes and templates are JSON files: the built-ins in
`manim_studio/data/library/`, your own in `~/.manim-studio/library` (or the folder in
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
function in `core/model/schema.py`.
