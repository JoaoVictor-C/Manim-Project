# Lumen - the Manim Studio interface

Lumen is the visual language of the editor from version 0.4: a quiet room of soft panels around the picture,
lit by one accent. The mock-ups are in [mockups/](mockups/project/) (a design canvas: `Main.dc.html` is
Compose, then Animate, Code, Audio, Deliver, Welcome, Palette, Paper, Foundations and Components; the
shared stylesheet is [lumen.css](mockups/project/lumen.css)). The decision is
[ADR 0063](../adr/0063-lumen-interface.md), the work plan [P17](../plans/p17-lumen.md).

## What was wrong

The editor works, and it looks like a tool that was built a panel at a time:

- Every panel is a flat grey rectangle edge to edge; nothing says what matters, so the picture and the
  timeline - the two things people look at - are drawn in the same weight as a dock title.
- Navigation is at the bottom of the window (small tabs under the timeline), the menus are a thin text
  strip, and the commands people use all day (undo, export, panels) are in none of the places the eye
  rests.
- Fields are tight and boxy, labels are tiny, there is one font size, and a number can only be typed.
- State is invisible until you look for it: saved or not, rendering or not, a sound that is out of date.
- Everything is dark grey on dark grey with a blue that is used for selection, buttons, hover and links
  alike, so nothing reads as "you are here".
- There is no way to find a command except by knowing its menu.

## Principles

1. **The picture is the hero.** Panels are cards (radius 14, hairline border, 8 px gutters) on a darker
   window; their chrome stays quiet so the colour on the stage is the loudest thing on screen.
2. **One accent, always meaning "here".** Selection, focus, the playhead and the one primary action share
   it. Nothing else is accent-coloured. Clip kinds use a spectrum of six hues of similar lightness.
3. **Touch it, don't type it.** Numbers scrub, curves drag, colours pick in place. Ctrl K reaches every
   command, layer and snippet by name.
4. **Always say what is happening.** Saved, rendering (with progress), stale, cached - on the page you are
   looking at, as a quiet chip or a toast, never only somewhere you left.
5. **Calm motion.** 90-220 ms ease-out, only to explain a change (a panel opening, the page indicator
   moving, a toast arriving). Off with "reduce motion" or when the system asks.

## Foundations

**Colour.** Two themes share one token set: *Ink* (dark, the default) and *Paper* (light). Surfaces
step lighter as they rise: `bg` < `surface` < `surface-2` < `surface-3`; `field` is the recessed colour
inside them; `stage` is the pasteboard around the video frame. Lines are white or ink at 7 % and 12 %
alpha so they sit on any surface. Text is `text`, `muted` and `faint`; `faint` is for hints and units only
(never the only carrier of meaning). The accent is `#7B6CF6` (Paper `#5B4BEA`) with a second end `#4CC9F0`
used only in gradients (the play button, the playhead, progress). Semantic: ok `#3DDC97`, warn `#FFB020`,
bad `#FF5C7A`. Contrast: text on any surface >= 4.5:1, muted >= 4.5:1, accent on `surface` >= 4.5:1,
white on accent >= 4.5:1; enforced by `tests/ui/style/test_theme.py`.

**Type.** Inter for the interface (400, 500, 600, 700), JetBrains Mono for code, times and numbers
(tabular), Newsreader (regular and italic) for titles on the welcome page and empty states, and for
anything that should feel like mathematics. Scale (px at 96 dpi): display 52-76, title 22, heading 14,
body 12.5, caption 11, section label 11 uppercase with 0.1 em tracking. Line height 1.4.

**Shape and space.** 4 px grid. Radii: card 14, row 10, control 9, small control 7, pill 999. Gutter 8 px,
panel padding 14, row height 36, control height 30 (26 small, 38 large). Elevation: cards are flat
(border only); things that float (menus, popovers, the transport pill, toasts, dialogs) have a 1 px line
and a soft shadow `0 10 30 black/50`; keyboard focus is a 3 px accent halo.

**Icons.** One family, Phosphor (regular weight, 1.7 px stroke at 16 px; fill weight for play and the
active tool), tinted by role: `muted` at rest, `text` on hover, `accent` when active.

**Motion.** 90 ms for hover and press, 160 ms for the page indicator and toggles, 220 ms for panels and
toasts; curve `cubic-bezier(.2,.8,.2,1)`.

## The shell

- **Top bar (52 px).** The mark and the menus at the left (File Edit Animate View Arrange Help, plain
  text; they are the real menus, so every shortcut keeps working), the **page switcher** centred (a
  pill with an icon, a label and the shortcut for Compose, Animate, Code, Audio and Deliver; the active
  page has a raised chip and an indicator that slides), and at the right undo and redo, the **search
  button** (opens the command palette), the three panel toggles, and **Export** (the one primary
  button of the window).
- **Cards** hold every panel: a 38 px header with an uppercase title, its actions on the right, a hairline
  under it.
- **Status bar (28 px).** Saved dot and project name at the left, activity at the right (a rendering
  chip with progress, preview state), then facts about the selection. Messages that used to go to the
  status bar for a few seconds become **toasts** (bottom right, 220 ms in, 4 s, with Undo when the action
  can be undone); the status bar keeps only what is true now.
- **Command palette (Ctrl K).** A centred card, 680 px: one field, results grouped (Actions, Layers,
  Snippets and presets), the matched letters in the accent, shortcuts at the right; `>` narrows to
  actions, `@` to layers, `#` to code symbols. It lists every enabled action of the window's menus, so a
  new menu item appears in it without work.

## The pages

**Compose** (Ctrl 1). Layers card at the left (288), Properties at the right (316), the stage card in
the middle over the timeline card. The stage shows the frame on a dotted pasteboard with the selection
box, a floating tool pill at its left and a floating **transport pill** (to start, play, to end, time,
repeat, speed, volume) at the bottom; the old slider bar is the timeline's job. Properties is a
list of collapsible sections with a keyframe diamond on every animatable one; fields are 30 px, labels
sit inside the field and *drag to scrub*; colours open a popover.

**Animate** (Ctrl 2). A small preview and the **curve editor** on top, the whole timeline below with
every layer expandable into its animated properties (Position, Scale, Rotation, Opacity), each with its
keys and the line between them.

**Code** (Ctrl 3). Explorer, editor with file tabs and a toolbar of state chips (Unapplied, Live, No
limit, Revert, **Run** as the primary button with its shortcut), the preview and the **Chapters** list at
the right, and a bottom panel with Output / Values / Parameters / History. An error is a sentence with
a "Did you mean...?" card and a Fix button beside the traceback.

**Audio** (Ctrl 4). The mix as lanes (Narration, Music, Effects, Subtitles) with real waveforms, a
master meter, and the Narration card: engine cards, voice, speed, Generate, the cue list with a
ready / stale / no sound chip each, the pronunciation chips.

**Deliver** (Ctrl 5). Destinations as large cards (web video, vertical short, GIF, transparent video,
still, Manim Python), the chosen one's settings with an estimate (time, size, sound), and a queue where
the running job has a progress ring and a time left.

**Welcome.** A serif title ("Make mathematics move."), New and Open, templates, the recent projects
with thumbnails, and a drawn curve on the right that is the logo's idea at large size.

## Components

Buttons: primary (accent gradient, one per view), secondary, ghost, danger; icon buttons 30 px.
Fields with an inside label and a unit; select; colour field with swatch; slider with a gradient fill;
toggle; checkbox; segmented control; tabs with an underline; chips (neutral, accent, ok, warn, bad);
list rows with a rounded type icon, name, a kind chip and hover actions; menus (rounded, one section
highlighted, shortcut at the right); tooltips with a shortcut; clips (rounded 8, a vertical gradient per
kind, a white ring when selected), keys (rotated rounded squares); dialogs (a header with an icon, a body, a
footer with the actions right-aligned, the primary last).

## Accessibility

Every control has a name and a tooltip; every colour pair meets the contrast above; focus is always
visible; nothing is conveyed by hue alone (a stale sound also says "stale"); text scales with the system
font size; **Reduce motion** and **High contrast** (Paper with 100 % lines) are in Preferences.
