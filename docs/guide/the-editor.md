# The editor

The window has a menu bar (**File, Edit, Animate, View, Arrange, Help**), five workspace
**pages**, and a page bar at the bottom to switch between them. The main views exist once and
move between pages, so the selection, playback and undo history are the same everywhere.

## Pages

Switch with the page bar, **View > Pages**, or `Ctrl+1` ... `Ctrl+5` (`Shift+1` ... `Shift+5` work too). Each page remembers
its panel sizes (also between runs), and the editor reopens on the page you left.

| page | key | what it is for | layout |
|---|---|---|---|
| **Compose** | `Ctrl+1` | building the scene | Layers - the viewer over the timeline - Properties |
| **Animate** | `Ctrl+2` | shaping motion | the viewer and Properties, the graph editor of the selected object's keys, the timeline |
| **Code** | `Ctrl+3` | code layers and Python objects | their list - a code editor over the render/build output - the viewer |
| **Audio** | `Ctrl+4` | sounds and subtitles | tables of sounds and of subtitles, a level meter, the viewer, the timeline |
| **Deliver** | `Ctrl+5` | exporting | the viewer - render settings, the render queue and the Python scene |

The buttons at the left of the page bar - **Layers**, **Properties** and **Timeline** - hide and show
those panels, like **View > Layers**, **View > Properties** and **View > Timeline**; a page shows the
buttons for the panels it has, a hidden panel stays hidden on every page, and the choice is remembered.
The button at the right of the bar, or **View > Full Screen** (`F11`), shows the animation alone, filling the
screen: no panels, no selection outline, the frame fitted and black around it, with a video player's control bar
over the bottom: the seek bar with the elapsed and total time (click or drag to jump), the title, start / back 5 s /
play-pause / forward 5 s / end, **repeat**, the **speed** (0.25x to 2x; a scene with sound plays at 1x), the volume
and mute (a scene with sound), and a button to leave. While it plays, the bar and the pointer fade when the mouse
rests (a paused animation keeps the bar). Keys: `Space` or a click plays and pauses, `Left`/`Right` step a frame
(`Shift`: ten), `Home`/`End` jump to the start and end, `L` repeat, `M` mute, `Up`/`Down` volume, and `Esc`, `F11` or
a double-click leave.
The Code page also has its own buttons for its explorer (`Ctrl+B`) and output (`Ctrl+J`).

## The viewer: canvas and transport

The canvas shows the frame at the playhead, rendered by Manim. Around the video frame, dimmed,
you see what lies outside it. Under it are the transport (play/pause, a time slider) and a
readout: the time, the frame number, how the frame was drawn (cached, or its render time),
the zoom, and - while frames are rendered ahead - how many are ready (`ahead 120/150`).

- `Space` plays and pauses; `Left` / `Right` step one frame.
- **Zoom and pan:** `Ctrl+Wheel` zooms about the cursor, the wheel pans (`Shift+Wheel`
  sideways), and so does dragging with the middle button. **View > Fit** (`Ctrl+0`),
  **Actual Size (100 %)** (`Ctrl+1`), **Zoom In** / **Zoom Out** (`Ctrl+=` / `Ctrl+-`).
  `F` on the canvas frames the selected objects (the whole frame when nothing is selected),
  also **View > Frame Selection**.
- **View > Half-resolution playback** draws the canvas at half resolution for heavy scenes.
- **View > Render Ahead** (on by default) renders frames ahead of the playhead in a second
  process and keeps them, so playing and scrubbing are smooth once they are ready. An edit only
  drops the frames it changes.

### Canvas gestures

- **Select:** click an object; `Alt+Click` picks the one behind it. `Shift+Click` adds or
  removes an object; a drag from empty canvas selects everything the rectangle touches.
- **Move:** drag (`Shift`: one axis only; `Alt`: no snapping; `Escape` cancels). Arrow keys
  nudge by 1 px (`Shift`: 10 px).
- **Scale / rotate:** drag a corner handle / the round knob (`Shift` snaps to 10 % / 15°). Both
  turn about the object's **anchor**, the small cross: `Ctrl+Drag` the cross to move it
  (`Shift` snaps to the box's corners, edge midpoints and centre), `Ctrl+Double-click` centres it.
- **Size handles:** the round handles on an object's edges change its own size - a
  rectangle's width or height, a circle's radius, a text's size (`Shift`: steps of 4 points) -
  and those on a line's ends move that end only. Sizes are not keyable: a handle changes the
  object for its whole life.
- **Snapping:** moved objects and dragged handles snap to the edges and centres of other
  objects and of the frame, and a guide shows where. Hold `Alt` to place freely, or turn it off
  with **View > Snap to Objects** (`Ctrl+;`).
- **Parts and groups:** a click selects the whole equation or group; double-click selects the
  term or object inside, `Escape` goes back up.
- **Motion paths:** when the selected object has position keys, its path shows with a square
  per key - see [Animation](animation.md#motion-paths).

**Arrange** lines up the selection: Align Left / Centre / Right / Top / Middle / Bottom
(`Ctrl+Alt+Left`, `H`, `Right`, `Up`, `V`, `Down`; a single object aligns to the video frame), and
Distribute Horizontally / Vertically spaces three or more objects evenly.

When the [camera](objects.md#the-scene-and-the-camera) is turned away from the flat view, the
canvas shows the picture but no outlines or handles and ignores clicks: select in Layers, or
reset the camera.

## Layers panel

One row per object, front first; parts of an equation and objects on axes sit under their
parent. Buttons: **Add** (the object library and templates), **Parts** (parts of an equation,
graphs and objects on axes), **Delete** (`Delete`), **Up** / **Down** (bring forward `Ctrl+]`,
send backward `Ctrl+[`; dragging rows also reorders). Double-click a row to rename it;
`Ctrl+Click` and `Shift+Click` select several. Right-click for the same actions.
Text layers are named by their words until you rename them.

## Properties panel

Properties edits whatever is selected; each finished field is one undo step.

- **Nothing selected:** the **Scene** (length, Grow with content, size, frame rate,
  background, **Fit Length to Content**) and the **Camera** (also **Edit > Scene Settings...**).
- **An object:** its own parameters (text, LaTeX, radius, colours...), **Style**,
  **Transform** (position, anchor point, scale, rotation, opacity, each with a **Keys** toggle)
  and **Lifetime** (Appears at / Disappears at; Auto when empty).
- **A clip, a key, a sound, a subtitle or a marker:** its timing and options.

Multi-line fields (LaTeX, code) apply with `Ctrl+Enter` or when you leave them.

## Timeline

Under the viewer on every page: a ruler with markers and the scene's end, one row per object
with its lifetime band, clips and key diamonds, then the **Subtitles** row and one row per
sound with its waveform.

- Click or drag on the ruler to scrub. `Ctrl+Wheel` zooms; **View > Fit Timeline** (`Shift+F`)
  fits the whole scene. **View > Follow Playhead** (on by default) keeps the playhead in view
  while you play, scrub or step.
- Drag a clip to move it, its edge to trim it; drags snap to frames, clip edges, keys, markers,
  sounds, subtitles and the playhead (`Alt`: no snapping; `Escape` cancels).
- Click the arrow by an object's name (or `Alt+Click` the name) to expand its **property
  rows**.
- Right-click a row for **Add clip**, **Apply preset**, **Browse presets...** and
  **Add key at playhead**; right-click a clip, a key, the ruler, a sound or the Subtitles row for
  what applies there.
- Clicking a row's name, or empty space on a row, selects that object (`Shift`/`Ctrl` adds).

Everything about animating on the timeline is in [Animation](animation.md).

## The other pages

- **Animate:** the graph editor and property rows - [Animation](animation.md#the-animate-page).
- **Code:** code layers and Python objects - [Objects](objects.md#python-objects) and
  [code layers](objects.md#code-layers).
- **Audio:** [Sound and subtitles](sound-and-subtitles.md#the-audio-page).
- **Deliver:** [Exporting](exporting.md#the-deliver-page).

## Preferences

Manim Studio remembers the recent files (**File > Open Recent**, ten at most, with
**Clear Recent**), the window, the panel sizes of every page, the view toggles (snap to
objects, half-resolution playback, render ahead, follow playhead) and the last page. They are
kept in one file, `manim-studio.ini` - see [where files live](troubleshooting.md#where-files-live).
Delete it to start fresh.

## See also

- [Keyboard shortcuts](shortcuts.md) - the complete table
- [Objects](objects.md) - what the Add menu creates
- [Animation](animation.md) - clips, keys and the graph
- [User guide index](index.md)
