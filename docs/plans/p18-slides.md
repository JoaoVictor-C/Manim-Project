# P18 - Slides: present mode and HTML deck

- **Status:** Done (2026-11-08) - acceptance `tests/acceptance/test_acceptance_p18.py`
- **Date:** 2026-11-08
- **Decided in:** [decision session 45](../logs/decision-sessions.md) (Terza, `balanced`, confidence 0.90)
- **ADR:** [0087 slides are marker stops](../adr/0087-slides.md); evidence [B76](../logs/benchmarks.md)

## Goal

Present an animation like a slide deck: it plays to the next stop and waits for a click, an arrow key or a presenter
remote, and a slide can loop its last moment while it waits. The same slides export as an HTML page that plays
offline in any browser.

**Done when** a user can mark stops on the ruler, set a loop, present full screen with Page Down / Page Up and
clicks, and export a deck from Deliver (or `manim-studio render x.json talk.html --deck`) that opens from disk and
behaves the same; an acceptance test walks it and the suite passes.

## Order

| Slice | What | Main files | Depends on |
|---|---|---|---|
| D1 | **Model and rules**: `Marker.slide`, `Marker.loop`; `stops`, `windows`, `loop_window`, `next_stop`, `previous_stop`; `edits.set_slide_stop` | `core/model/schema.py`, `core/editing/slides.py`, `core/editing/edits.py` | - |
| D2 | **Marking stops**: Properties' Marker section gets *Slide stop* and *Loop (s)*; the ruler draws a stop as a different flag and a loop range as a band; Edit > Add Slide Stop (Shift+M) at the playhead; `[` / `]` unchanged | `ui/panels/properties_panel.py`, `ui/timeline/view.py`, `ui/main_window.py` (menu) | D1 |
| D3 | **Present mode**: `MainWindow.play_until` / `play_loop` in `_on_play_tick`; Presenter slides mode (keys, "Slide n of m", Shift+arrows step frames); View > Present Slides (F5 is taken: Ctrl+F5) | `ui/main_window.py` (tick only), `ui/playback/presenter.py`, `ui/playback/player_bar.py` | D1 |
| D4 | **HTML deck**: pure page builder + manifest; `export_deck` (per-window `export_video`, end png, loop mp4); CLI `--deck`; ExportJob flag; Deliver format "Slide deck (HTML)" | `core/exchange/slide_deck.py`, `render/slide_deck.py`, `cli.py`, `ui/deliver/*` | D1 |
| D5 | **Acceptance and docs**: walk mark -> present -> export; guide page, changelog, shortcuts help | `tests/acceptance/test_acceptance_p18.py`, `docs/guide/` | D2-D4 |

D2, D3 and D4 touch different files and can run in parallel after D1 (D2 and D3 both touch `main_window.py`: D2 only
adds a menu action, D3 only the tick and a menu action; merge D3 first).

## Rules the tests pin (from the decision session)

- With no stops there is one slide, the whole scene. A stop on frame 0 is a one-frame title slide. A slide with no
  frames (a stop on the last frame) is dropped. Two stops one frame apart make a one-frame slide.
- A slide's last frame is its stop's frame; the next slide starts one frame later.
- `loop_window` is clamped to at least one frame and at most the slide; the editor and the deck use it alike.
- Saving a project with no slide fields writes the same bytes as before (fields left out when unset).
- Ripple and Shift Timing keep `slide` / `loop` on the markers they move.
- Present mode: a coarse clock (tick longer than a frame) never shows a frame past the stop; sound stops at the
  stop; Next while playing jumps to the stop; Next while waiting plays the next slide; Previous shows the previous
  stop paused; a loop repeats with no sound.
- Deck: one mp4 per slide whose frame count equals its window (read back with PyAV), an end png per slide, a loop
  mp4 per looping stop; the page lists them in order and opens from disk.

## Not now

- A single-file deck (videos inlined as base64).
- Speaker notes, a presenter view on a second screen, a timer.
- Export to PowerPoint.

## Results

- D1 model and rules: 19 tests, 13/13 mutants killed. D3 present mode: 13 tests, 15/15 killed.
- D2 marking (Shift+M, Properties fields, ruler flag and loop band): 11 tests, 12/13 killed (the survivor is
  equivalent: only stops have slide windows).
- D4 deck (page builder, `export_deck`, CLI `--deck`, Deliver destination): 28 tests, 33/33 killed. Headless Edge
  played a three-slide deck with a loop through Next, the loop and End.
- Still to check by eye in a desktop browser: sound after the click, no black flash between slides, preloading,
  full screen.

