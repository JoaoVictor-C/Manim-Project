# 0087. Slides are marker stops: present them full screen or export them as an HTML deck

- **Status:** Accepted
- **Date:** 2026-11-08
- **Deciders:** João Victor
- **Extends:** [ADR 0037](0037-markers-and-snapping.md) (markers), [ADR 0042](0042-deliver-options.md) (render options)
- **Decided in:** [decision session 45](../logs/decision-sessions.md) (Terza, `balanced`, confidence 0.90), evidence B76

## Context

People present their animations live: the animation plays up to a point, waits for the speaker, then goes on, the
way a slide deck builds a slide. Two things were asked for: a **present mode** in the editor (click, arrow keys or
a presenter remote's Page Down / Page Up move on) where a slide may **loop its last moment** while it waits, and an
**HTML deck** that plays the same slides offline in any browser.

What the code already had: markers (ADR 0037) are named, frame-snapped moments with ruler flags, snapping, `M` /
`[` / `]`, undo, and they move with the content under linked ripple (`core/editing/ripple.py`, scope `markers` on by
default) and Shift Timing (`core/editing/shift_timing.py`, which copies a marker with `model_copy`, so any other
field survives). The full-screen player (`ui/playback/presenter.py`) drives the editor's own playback, and every
playing tick goes through one method, `MainWindow._on_play_tick`. `export_video` renders any time window to an MP4
with its sound. `schema_version` 1 is frozen: new fields are optional.

## Decision

**A slide stop is a marker.** `Marker` gains two optional fields, both left out of the file when unset:

- `slide: Literal["stop"] | None` - playback in present mode waits here;
- `loop: float | None` - while it waits, the last `loop` seconds before the stop play again and again, silently.
  Unset: the stop's frame holds still. The range is on the stop itself, never taken from neighbouring markers, so
  a note or a sound-sync marker never changes how a talk plays.

**One pure module says where slides are**, `core/editing/slides.py`, used by the editor and the deck alike:

- `stops(project)` - the stop markers in time order;
- `windows(project)` - each slide as a frame range `(first, last)` on the export's frame grid. A slide ends on its
  stop's frame (included); the next starts on the frame after it; the last slide runs to the scene's end. A stop on
  frame 0 is a title slide of one frame (the talk opens paused on it); a slide with no frames (a stop at the very
  end) is dropped. With no stops there is one slide, the whole scene.
- `loop_window(project, slide)` - the frames that repeat, clamped to at least one frame and at most the slide;
- `next_stop(project, t)` / `previous_stop(project, t)`.

**Present mode is a mode of the full-screen player**, on whenever the project has stops. The editor's playing tick
gains a *play end* and an optional *loop range* (`MainWindow.play_until`, `play_loop`): when a tick would pass the
end it seeks exactly to the stop's frame and pauses (sound stops there too); in a loop range it goes back to the
range's start on the wall clock with no sound. Keys: **Next** (Page Down, Right, Space, click) jumps to the stop
when a slide is playing, otherwise plays the next slide; **Previous** (Page Up, Left) shows the previous stop
paused; Home / End go to the first / last slide; Shift + Left / Right keep stepping frames; Esc leaves. The player
bar shows "Slide 3 of 8".

**The HTML deck is a folder**: `<name>.html` and `<name>_files/` holding, per slide, `slide-NN.mp4` (with its
sound), `slide-NN-end.png` (the stop's frame) and, for a looping stop, `slide-NN-loop.mp4` (silent). One export
process renders them with `export_video` per window (`render/slide_deck.py`), then writes the page, whose text is
built by a pure function (`core/exchange/slide_deck.py`) from a manifest. The page opens on a click-to-start cover
(browsers allow sound only after a click), plays each slide and waits; Next during a slide shows the end still at
once, then the loop. `manim-studio render project.json talk.html --deck` and Deliver's format choice make one.

## Consequences

- Slides inherit every marker behaviour: snapping, navigation, undo, clipboard, ripple, Shift Timing, the beat
  sheet's beats (ADR 0073). A stop is drawn as a different flag on the same ruler.
- A deck costs about 0.3 s more per slide than one video (B76): 1-6 % on real-length scenes. Loop clips add their
  own length.
- The deck is several files; copying it means copying the folder. A single self-contained file (videos inlined) can
  come later as an option.
- Next during a slide cuts its narration mid-word: that is the speaker's choice, the same in the editor and the deck.

## Alternatives considered

- **A separate `Project.slides` lane** - a new list, timeline row, snapping kind, undo kinds, and ripple / Shift
  Timing / clipboard coverage, all of which markers already have; the only gain, a row of its own, a distinct flag
  shape gives too.
- **One video with JavaScript pausing at times** - `timeupdate` fires about four times a second;
  `requestVideoFrameCallback` reports a frame already shown and `pause()` is asynchronous, so a stop overshoots by a
  frame or more, and correcting it (or looping) seeks inside a long GOP and hitches. Forcing key frames at stops
  would tie the encoder to the slide model.
- **One self-contained HTML file with base64 videos** - a third larger, slow to open for long talks. Possible later.
- **Loop from the previous marker** - couples unrelated markers to presenting (a sound-sync marker inside a slide
  would silently shorten its loop).

## Evidence

- Benchmark: [B76](../logs/benchmarks.md) - per-window export overhead; a deck page opened from disk plays its
  sibling-folder videos.
- Source: `ui/main_window.py` `_on_play_tick` (the one playing tick); `core/editing/ripple.py` and
  `core/editing/shift_timing.py` (markers move with the content).
- Tests: `tests/core/editing/test_slides.py`, `tests/ui/playback/test_present_slides.py`,
  `tests/render/test_slide_deck.py` (see the plan, [p18-slides](../plans/p18-slides.md)).
