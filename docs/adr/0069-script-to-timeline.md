# 0069. Script to timeline: a written script becomes timed subtitle cues, with optional placeholders

- **Status:** Accepted
- **Date:** 2026-10-31
- **Deciders:** João Victor

## Context

Narration ([0060](0060-voice-providers-and-narration.md)) speaks the project's subtitles, and subtitles
([0035](0035-subtitle-track.md)) are typed one cue at a time or imported from an .srt that already has times. Someone who
starts from a written script - the usual way to make an explainer - had to cut it into cues and time each by hand.

## Decision

- `core/editing/script_import.py`: `split_script(text, unit)` cuts a script into sentences or paragraphs (blank lines
  separate paragraphs; a Markdown heading names the paragraph after it and is not spoken; emphasis marks, bullets and
  quotes are dropped; common abbreviations, initials and "e.g." do not end a sentence). `import_script` places the
  pieces one after another, each lasting its words over `words_per_second` (2.6, never under 1 s), `GAP` 0.25 s
  apart and 0.7 s between paragraphs, on frame boundaries, after the subtitles already there or from a given time.
- With `placeholders`, each paragraph also gets a Text layer called "Beat n", shown for as long as the paragraph is read,
  whose text is its heading or its first words: something on the stage to replace with the real visual.
- One edit: the scene grows to hold the cues (`grow_to_fit`), the edit is classified like any other, undo removes it
  all. Sentences over 40 words are reported, not changed.
- **File > Import Script...** pastes or loads a .txt/.md, chooses sentence or paragraph, the reading speed and the
  placeholders, and says what it will make before it does.

## Consequences

- The cues are plain subtitles: they are retimed, burned in, exported as .srt and narrated like any other; narration
  later fixes their timing to the speech.
- Reading speed is one number; a script with slow and quick parts is retimed afterwards.
- Languages without sentence punctuation as in English split only on `. ! ? …`; other scripts are best imported by
  paragraph.

## Alternatives considered

- **Import with real narration at once** - speech needs an engine, may need the internet, and the user may want to
  edit the words first; the Audio page does it from the cues.

## Evidence

- Tests: `tests/core/editing/test_script_import.py`, `tests/ui/exchange/test_script_dialog.py`.
