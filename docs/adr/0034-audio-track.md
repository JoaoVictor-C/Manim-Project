# 0034. An audio track: project audio clips, one mix, the sound card as clock

- **Status:** Accepted
- **Date:** 2026-10-11
- **Deciders:** João Victor

## Context

Animations are usually cut to narration or music. The editor had no sound:
playback ran on the wall clock, the export wrote video only, and the Python
export could not place sounds.

## Decision

- **Model.** A project has a list of audio clips beside its layers:
  `audio: [{id, name, path, start, offset, duration, gain, fade_in, fade_out}]`
  (seconds; `offset` trims the file's start; `gain` in dB). The list is saved
  only when it is not empty; layers stay purely visual.
- **One mix.** `core/audio.py` (PyAV and numpy, no Qt) probes a file's
  duration, decodes it to 48 kHz stereo float (a small cache keyed by path and
  file signature), keeps waveform peaks, and mixes a project into audio as long
  as the canvas: each clip trimmed, with gain and linear fades, the sum clipped.
  The editor, the export process and exact Python scenes all use it.
- **Playback.** When the project has audio, a sound device exists and audio is
  on, the mix plays from the playhead through a `QAudioSink` and the time the
  device has played is the playback clock (it advances every ~10 ms, B47); the
  first frame waits for the sound to start. Otherwise the wall clock drives
  playback as before (`MANIM_STUDIO_AUDIO=0` in tests). Scrubbing is silent.
- **Export.** The video gets an AAC 48 kHz stereo track with the mix, aligned to
  the sample (B47).
- **Editing.** One timeline row per audio clip under the layers, with its
  waveform: drag to move, drag an edge to trim, Delete. Properties edit start,
  trim, duration, gain and fades. File > Import Audio... adds a clip at the
  playhead.
- **Python export.** A clip that is not trimmed or faded and ends within the
  scene is written as `self.add_sound(path, time_offset=start, gain=gain)`; any
  other audio makes the export exact: the scene mixes with `core.audio` when it
  is rendered and adds that sound at 0.
- **Caches.** Audio edits change no frame: render-ahead ignores `audio` when
  diffing projects, and the evaluator keeps every cache.
- **Missing files** are silent and reported like missing media (ADR 0027);
  their signatures are checked again on activation and F5.

## Consequences

- Playback with audio starts after the device does (~0.1 s, ~0.5 s for the
  first sound in a session).
- A long sound file costs memory while decoded (384 KB per second); the cache
  keeps a few files.
- Audio is mixed in one place, so what you hear, the video and the exported
  scene agree.

## Evidence

- Probe: B47 in [../logs/benchmarks.md](../logs/benchmarks.md).
- Design: [../logs/decision-sessions.md](../logs/decision-sessions.md), session 26.
- Plan: [../plans/p4d-audio.md](../plans/p4d-audio.md).
