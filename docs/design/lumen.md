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

## The tools added since the first design (0.5)

Everything below was built after the first Lumen mock-ups, using the same tokens and components; this section is
where each one lives so no feature is "somewhere in a menu". Mock-ups: [Camera.dc.html](mockups/project/Camera.dc.html),
[Tools.dc.html](mockups/project/Tools.dc.html) and [Dialogs.dc.html](mockups/project/Dialogs.dc.html). Rule of thumb:
a feature that changes *the picture* lives on the stage or timeline, one that *explains or checks* the project
lives in a dialog or a card of its page, and every one of them is also a palette action (Ctrl K lists the menus).

### Camera (ADR 0072, 0083)

- **Layer row.** The camera is the first row of Layers and cannot be reordered or grouped: a rounded `camera`
  icon tile in the accent-to-cyan gradient, the name, a `camera` chip, the eye. There is one per project; *Add
  object > Camera* is disabled with a tooltip once it exists.
- **Stage header** carries the view as a **segmented control: Scene | Game** (shortcut `G`), next to the Fit /
  75 % / 100 % control. The text that used to float over the picture ("Game view: ...") is a tooltip of the
  control and a one-line hint in the status bar, never a banner over the video. Game is the default.
- **Scene view** draws the world flat. The camera is a **rectangle in the accent** (1.5 px, soft halo) with a
  small camera glyph on its top-left corner, a dashed line to a followed layer, a centre cross, and four corner
  handles that change Size, and a round handle on a stalk above it for Roll; dragging inside moves it. The
  rectangle's own readout chip ("Size 4.0 - 16:9") is accent-filled, like the selection size chip.
- **Properties.** Transform has Position, **Size** (instead of Scale) and Rotation, each with its keyframe
  diamond; the **Camera** section has Background (colour field with swatch and a clear button), Follow (a layer
  picker with an "x" and an Offset X / Y row). A scale key reads "Size" in the key popover.
- **Timeline.** The camera lane is pinned under the ruler with its position / size / rotation keys; the value
  curves ease the *size*, as Unity does.

### Stage, guides and labels (ADR 0074, 0075)

- **Layout guides** (View > Layout Guides, `Ctrl '`): thin accent lines at 30 % over the frame - rule-of-thirds,
  centre cross, title-safe and action-safe boxes - plus draggable guides pulled from the rulers. The guides
  dialog is meant to be a small popover on the stage header's guides button; today it is a restyled dialog (the
  shell cannot import the canvas package), and the header button toggles the guides.
- **Pinned labels:** a rounded label in the layer's own colour with a leader line to the object; they are drawn
  by the same renderer as the video (they can be exported) and are edited in place.
- **Esc** deselects everything; clicking on empty stage does the same and starts a marquee.

### Timeline (ADR 0071, 0079, 0080)

- **Sequences.** Clips and keys made into a sequence are drawn as one bar: the bracket glyph, the name, and the
  member clips inside it as thin segments; the bar has a dashed outline in the clip kind's hue when its parts do
  not all fit one hue. Double-click opens it; *Dissolve Sequence* puts the parts back. Moving the bar moves every
  clip and key; the bar is a **recipe** once saved (Edit > Make Recipe from Sequence), and recipes appear in the
  presets browser with a "recipe" chip and their parameters as a small form.
- **Ripple edit** (Edit > Ripple Edit..., `Ctrl+Alt+R`): a dialog with the mode as a segmented control (*Close the
  gap / Open space / Linked*), a number field with a unit, and a live line "moves 5 clips, 3 keys, 2 markers" in
  a quiet chip; the timeline shows the moved range as a soft accent band while the dialog is open.
- **Draft preview** (View): a chip *Draft* in the stage header while the preview shows a faster, lower-quality
  frame during an edit; it turns to *Exact* when the real frame arrives.

### Dialogs (ADR 0066, 0068, 0073, 0078, 0082)

All use the dialog chrome of Components (icon header, body, footer with the primary last) at 560 x 520, and none
take more than one task.

- **Beat sheet** (Edit, `Ctrl+Alt+B`): one row per beat between markers - a 192 x 108 picture, the beat's name and
  clock range in mono, then *Appears / Says / Sound* as three quiet lines with a coloured dot each. Double-click
  goes there. Footer: *Copy as Markdown*, *Close*.
- **Explain This Moment**: a card list ordered by layer; each row says in a sentence why it is visible now
  ("Write is 62 % through its run"), with the clip chip and a *Go to* ghost button; *Previous / Next moment*
  step through the scene and move the playhead.
- **Snapshots** (File > Snapshots): named versions as rows with a thumbnail, name, age, and *Restore / Compare /
  Delete* on hover; "Save snapshot" is the primary.
- **Plugins**: a table with name, version, a compatibility chip (*ok / needs newer app*), and the permissions the
  plugin asks for as chips (*files*, *network*, *runs code*); *Approve* is a primary button per row; unapproved
  plugins stay off and say "waiting for approval".
- **Extract selection as code**: a preview of the generated code in a code card with a *Same picture* ok chip
  after the check, and the primary *Extract*.
- **Bundles** (File > Export Bundle / Open Bundle): a progress ring and the list of files that went in; opening
  a bundle that fails its check shows the failures as bad chips and never opens it half way.
- **Import script**: the script on the left, the proposed timeline on the right (the structure as lanes), *Create*.

### Code page (ADR 0067, 0076)

- **Errors know where they are.** An error is a card under the editor: a bad chip with the exception, one
  sentence, then two ghost buttons *Go to line* and *Go to layer at 0:04.20* (the playhead goes to the time the
  error belongs to); the "Did you mean...?" card and the Fix button keep their place.
- **Farm chip.** In the toolbar a chip *Farm 3 / 4* (running over total, accent when busy) opens a popover with
  each Python layer's state (waiting, running, ready, failed) and the controls (run again, stop).
- **Controls.** Parameters declared in the code appear in the Parameters tab as sliders, toggles and colour
  swatches that rerun the scene as they move.

### Deliver (ADR 0065, 0066, 0081)

- **Health.** Above the settings a **health card**: a row of chips (*Fonts ok, Media ok, Python layers 2 slow,
  Sound stale*), each warn or bad chip opens the thing it names; the estimate row keeps time, size, sound.
- **Resume.** An export that was interrupted shows in the queue as a card with a segment strip (done segments
  filled in the accent gradient, the next one pulsing), *Resume* as the primary and *Start over* as ghost;
  the progress ring reads "6 of 9".
- **Farm.** The queue row of a parallel export shows one thin bar per worker below the main ring. *Not built yet:*
  the export reports only frame and total, so the bars wait for per-worker progress from the render processes.
- **GPU.** *Encoder* is a segmented control (*Auto / GPU / CPU*) with a chip saying which was used after the run.

### Welcome (ADR 0064)

Templates are 176 x 84 cards with an icon tile, title and one line: *Blank*, *Euler's identity*, *Showcase*,
*Camera tour*, ... The recent list keeps thumbnails.

### Where the shortcuts live

Every new command has a menu entry (so it is in the palette) and a shortcut when it is used often: Beat Sheet
`Ctrl+Alt+B`, Ripple `Ctrl+Alt+R`, Game / Scene view `G`, Layout guides `Ctrl '`, Explain This Moment
`Ctrl+Alt+E`; the rest are palette-only on purpose.
