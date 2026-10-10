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
| `parent_id` | string | part layers only: the object (or part) it belongs to |
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
*orphaned*: kept, but drawn nowhere. Morph clips are not allowed on objects
with parts yet.

```json
{ "id": "b", "name": "b^2", "parent_id": "eq", "part": { "tex": "b^2", "occurrence": 0 },
  "clips": [{ "id": "i", "kind": "Indicate", "start": 1.0, "duration": 1.0 }] }
```

## Spec

```json
{ "type": "MathTex", "params": { "text": "e^{i\\pi}+1=0", "font_size": 72 }, "style": { "fill": "#facc15" } }
```

- `type`: `Circle`, `Square`, `Rectangle`, `Triangle`, `Line`, `Arrow`, `Dot`,
  `Star`, `Text`, `MathTex`, `Tex`, `ImageMobject`, `Code`.
- `Code` (ADR 0019) holds Python in `params.code`: one `Scene` subclass
  (`from manim import *` and `numpy as np` are implied). It is rendered once
  into a frame cache, plays from the layer's start and holds its last frame;
  it has no clips. It runs only when trusted on this computer.
- `params`: keyword arguments of the Manim constructor. `Text`/`MathTex`/`Tex`
  take their string in `text`; `ImageMobject` takes `path`.
- `style`: `fill`, `fill_opacity`, `stroke`, `stroke_width`, `stroke_opacity`.

The object is built centred on the origin; `base`/`tracks` place it.

## Transform2D

`{"position": [x, y], "scale": 1.0, "rotation": 0.0, "opacity": 1.0}` —
rotation in degrees counter-clockwise; opacity multiplies the object's own opacity.

## Keyframe

```json
{ "t": 2.2, "value": [0, 1.2], "ease": { "name": "smooth" } }
```

`value` is `[x, y]` for `position`, a number otherwise. `ease` describes the
segment **leaving** this keyframe: either `{"name": <Manim rate function>}`
(`linear`, `smooth`, `rush_into`, `there_and_back`, `ease_in_out_sine`, …) or
`{"bezier": [x1, y1, x2, y2]}` (CSS `cubic-bezier`; y may overshoot).

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
| `params` | extra keyword arguments for the Manim animation |
| `to_layer` | morph clips only: the layer this one turns into |

| category | kinds | effect on lifetime |
|---|---|---|
| content (introducer) | Create, Write, DrawBorderThenFill, FadeIn, GrowFromCenter, SpinInFromNothing | starts it |
| content (remover) | Uncreate, Unwrite, FadeOut, ShrinkToCenter | ends it |
| emphasis | Indicate, Wiggle, ApplyWave | none (returns to rest) |
| morph | Transform, FadeTransform, TransformMatchingShapes | ends this layer, starts `to_layer` |

`ImageMobject` layers accept fades, growth/shrink and Indicate only.

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
