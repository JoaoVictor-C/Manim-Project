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
| `parent_id` | string | child layers only: the object (or part) it belongs to — a part, or a child object such as a graph |
| `part` | `{"tex": s, "occurrence": n}` | part layers only: the `n`-th match (from 0) of `tex` in the parent's text |
| `base` | Transform2D | static transform when a track has no keyframes |
| `lifetime` | `{"in": s, "out": s}` | optional; inferred from clips when absent (below) |
| `tracks` | `{property: Keyframe[]}` | `position`, `scale`, `rotation`, `opacity` |
| `clips` | Clip[] | must not overlap in time (validated) |

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

```json
{ "id": "b", "name": "b^2", "parent_id": "eq", "part": { "tex": "b^2", "occurrence": 0 },
  "clips": [{ "id": "i", "kind": "Indicate", "start": 1.0, "duration": 1.0 }] }
```

**Child objects** (ADR 0024) have a `parent_id` and their own `spec` (no part
key). Today: a `Graph` under an `Axes` root. A graph is plotted in its axes'
coordinates, drawn right after them, moves with them and lives within their
lifetime. It is **locked** to them: its `base` keeps the default position,
scale, rotation and anchor, and only `opacity` may have a track. Its clips are
its own; it may morph into another layer (typically another graph).

```json
{ "id": "sin", "parent_id": "axes", "spec": { "type": "Graph",
  "params": { "expression": "sin(x)", "x_range": [-5, 5] }, "style": { "stroke": "#38bdf8" } } }
```

## Spec

```json
{ "type": "MathTex", "params": { "text": "e^{i\\pi}+1=0", "font_size": 72 }, "style": { "fill": "#facc15" } }
```

- `type`: `Circle`, `Square`, `Rectangle`, `Triangle`, `Line`, `Arrow`, `Dot`,
  `Star`, `Text`, `MathTex`, `Tex`, `ImageMobject`, `Code`, `Axes`; `Graph` (only
  as a child of `Axes`).
- `Code` (ADR 0019) holds Python in `params.code`: one `Scene` subclass
  (`from manim import *` and `numpy as np` are implied). It is rendered once
  into a frame cache, plays from the layer's start and holds its last frame;
  it has no clips. It runs only when trusted on this computer.
- `params`: keyword arguments of the Manim constructor. `Text`/`MathTex`/`Tex`
  take their string in `text`; `ImageMobject` takes `path`.
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
| emphasis | Indicate, Wiggle, ApplyWave, Circumscribe, Flash, FocusOn | none (returns to rest) |
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
| MoveAlongPath | `path` | the id of another layer (not the object itself or its parts, not a part, code layer or image) |

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
- Canvas sizes, fps, `frame_height` and `duration` are positive; `opacity` in `base` is in [0, 1].
- Cubic-bezier `x1`, `x2` are in [0, 1] (y may overshoot).

## Compatibility

Readers must reject unknown `schema_version` values. Adding optional fields
does not bump the version; renaming or changing meaning does, with a migration
function in `core/schema.py`.
