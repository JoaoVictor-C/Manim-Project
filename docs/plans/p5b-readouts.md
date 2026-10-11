# P5b — Value readouts and connectors

- **Status:** In progress
- **Date:** 2026-10-11
- **Decided in:** [decision session 29](../logs/decision-sessions.md) (Terza, `fast`, confidence 0.90)
- **Evidence:** B49 in [../logs/benchmarks.md](../logs/benchmarks.md)
- **ADR:** [0036 — Value readouts and connectors](../adr/0036-readouts-and-connectors.md)

## Goal

**Done when** a number on the canvas can count from one value to another with a
clip, a line or arrow stays attached between two moving objects, both render ahead
and export, and both are plain Manim in readable Python exports where possible.

## Number

- Spec type `Number`: params `value` (0), `decimals` (2), `suffix` (LaTeX, ""),
  `font_size` (48), `sign` (no/yes). Built with `DecimalNumber`, centred.
- Clip kind `ChangeDecimalToValue` (category emphasis: it neither introduces nor
  removes; only on Number; param `value`, a float).
- Warm key for Number (worker compiles digits, suffix).
- Readable export: `DecimalNumber(...)`, `ChangeDecimalToValue(n, value)`.

## Connector

- Spec type `Connector` (`CONNECTOR_TYPES`): params `start` and `end` (layer ids),
  `start_offset`, `end_offset` (points), `ends` (edges/centres), `tips`
  (none/end/both), `gap` (0.1). Style: stroke colour and width.
- Evaluator: drawn per frame from ADR 0033 traced points; edges via each target
  drawing's bounding box; cached per (endpoints, spec).
- Schema: targets exist and are traceable (not itself, a trace, a connector or code);
  no clips. `remove_layer` deletes connectors of a deleted target; render-ahead
  closure adds connectors of changed layers.
- Readable export: `always_redraw(...)` for centres ends, no offsets, plain roots;
  otherwise exact.

## UI

- Library: *Text > Number*, *Shapes > Connector* (joins the selected object and the
  one before it in the list; refused without two objects).
- Properties: layer choosers for the targets; the clip's value field.

## Steps

| step | content | acceptance |
|---|---|---|
| P5b.1 | Number, clip kind, Connector, validation, cascade, render-ahead, export | clip harness on Number; manim render of a readable count-up and a connector; box-edge ends; render-ahead after moving a target |
| P5b.2 | library, Properties, timeline | add both from the library, edit them, animate a count |
| P5b.3 | acceptance, docs | the Goal's scenario through the UI, with the export process and an exact/readable Python scene |
