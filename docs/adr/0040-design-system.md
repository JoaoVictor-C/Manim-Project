# 0040. The design system

- **Status:** Accepted
- **Date:** 2026-10-11
- **Deciders:** João Victor

## Context

The editor used the native Windows style with no stylesheet, text buttons
("Add", "Delete", "Up", "Down") and 27 colours written into the timeline, canvas,
curve editor and fields. Phase 6 turns it into a studio; P6a gives it one look
before P6b rebuilds the window into pages.

## Decision

- **Tokens** (`ui/theme.py`): one frozen set of colour roles - the chrome (window,
  panel, raised, field, border, divider, text, muted, disabled, accent and the text
  on it, warning, danger, success, tool tips), the timeline's colours (track, ruler,
  lifetime band, playhead, snap guide, clip categories, sound, waveform, subtitles,
  keys), the canvas overlays and the curve editor - plus a 4 px spacing grid, a
  corner radius and fonts. One dark **Studio** set: neutral greys, a blue accent.
- **Contrast is measured** (WCAG 2.1): text at least 4.5:1 on every surface it sits
  on (measured 11.6-14.9), muted text at least 4.5:1 (5.7-7.4), white on the accent
  and on every clip bar at least 4.5:1. The clip categories are darker shades of
  their former hues for that reason.
- **`theme.apply(app)`**: the Fusion style (the native style ignores a dark
  palette), a palette from the tokens, one stylesheet generated from them, a 9 pt UI
  font. The app and the tests' application fixture both call it, so the tests drive
  the widgets users see.
- **Icons** (`ui/icons.py`): semantic names mapped to Phosphor glyphs through
  QtAwesome (MIT), imported on the first icon and tinted from the tokens. Icon
  buttons keep their text as tool tip and accessible name.
- **Fields waiting for an edit** use a `pending` property the stylesheet styles,
  not a stylesheet of their own.
- **Content is not themed**: layer styles, the canvas background, marker and
  subtitle colours, and the dashed placeholder Manim draws in the frame are part of
  the document and the export. No colour literal remains in `ui/` outside
  `theme.py` (a test checks).

## Consequences

- One dark theme; a light set and a preference come with P6d.
- QtAwesome is a new dependency: about 230 ms on the first icon when warm, a few
  seconds the very first time its fonts load.
- Icon buttons are a little narrower or wider than their text was.

## Evidence

- B54 in [../logs/benchmarks.md](../logs/benchmarks.md); the contrast measurements
  and the UI suite run under the theme in decision session 33
  ([../logs/decision-sessions.md](../logs/decision-sessions.md)).
- Plan: [../plans/p6a-design-system.md](../plans/p6a-design-system.md).
