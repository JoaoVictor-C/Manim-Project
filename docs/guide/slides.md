# Slides

Present an animation like a slide deck: it plays up to a **slide stop** and waits there until you click or press
a key, then plays on to the next stop. The same slides export as an HTML page that plays offline in a browser.
The reasons for the design are in [ADR 0087](../adr/0087-slides.md).

## Mark the stops

A slide stop is a marker (see [Animation](animation.md#markers)) that presenting waits at.

- **Edit > Add Slide Stop** (`Shift+M`) puts one at the playhead, or turns the marker already there into one.
- Select a marker and tick **Slide stop** in Properties to turn it into a stop, or untick it to make it a plain
  marker again.
- **Loop** (seconds) makes a stop replay its last moment, silently, while it waits - a pulsing arrow or a turning
  shape keeps moving instead of freezing. Leave it at *Hold still* to rest on the stop's frame.

On the ruler a stop has a bigger flag with a pause sign, and a looping stop shades the part that repeats.
Hover a flag to read what it does. Stops move with everything else when you use Shift Timing or ripple edits.

A slide ends on its stop's frame and the next starts on the frame after it; the last slide runs to the end of the
scene. A stop at 0 s makes a title slide: the talk opens paused on the first frame.

## Present

**View > Full Screen** (`F11`) presents the slides whenever the project has stops. The player bar shows
"Slide 2 of 8".

| Key | Does |
|---|---|
| Click, `Right`, `Page Down`, `Space`, `Enter` | Next: play the next slide, or, while a slide plays, jump to its stop |
| `Left`, `Page Up`, `Backspace` | Previous: the stop before this slide, paused |
| `Home` / `End` | The start / the end of the talk |
| `Shift+Left` / `Shift+Right` | One frame back / forward |
| `Esc` | Leave |

Presenter remotes send `Page Down` / `Page Up`, so they work as they do in a slide program. Sound plays within a
slide and stops at its stop; loops are silent.

## Export an HTML deck

On the **Deliver** page choose **Slide deck (HTML)** and **Render deck**, or from a terminal:

```bash
manim-studio render talk.json out/talk.html --deck
```

The deck is `talk.html` and a folder `talk_files` beside it with one video per slide, a picture of each stop, and
the loop videos. Copy both to share it. Open the page in any browser - no internet needed - and click to start
(browsers only play sound after a click). The keys are the ones above, plus `F` for full screen.
