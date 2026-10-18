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

## Amendment (2026-10-18): the same mix, computed per span

A 15-minute sound cost about 1 GB while editing (B64): the decoded file at 48 kHz stereo float32
(332 MB), the whole-scene mix (331 MB) and a second mix kept by the cache during an edit, with
a 614 ms rebuild after each audio edit and a 2.1 s decode on the GUI thread at the first
timeline sync. The user chose to mix in short spans, decoding on demand, with no change to any
output sample (B70).

- **One mix, per span.** `audio.mix_span(project, start, count)` is the mix's samples
  `start..start+count`: each clip under the span adds its slice, in the clips' order, with
  the whole clip's arithmetic (the envelope's ramp index is an integer cast to float32, as
  `np.arange(n, dtype=float32)` gives it; a float32 range started mid-clip rounds differently
  past 2**24 samples), then the sum is clipped. It is **bit-identical** to the slice of the
  whole mix (`np.array_equal`, random projects and spans in `tests/core/test_audio_spans.py`
  against a verbatim copy of the old mix). `audio.mix` stays, made of spans, for the exact
  Python scene's wav; playback (a `QIODevice` pulling 0.25 s spans), the export (the mix
  encoded in 10 s pieces with consecutive timestamps, the same AAC track as before), the level
  meter and the timeline read spans or streamed peaks.
- **Decoding on demand.** Files are decoded in windows of 61 440 samples (1.28 s), kept in an
  LRU bounded at 64 MB for all files; a few readers stay open where they stopped, so playing
  on does not seek again. No decode of a whole file is kept (`decode` remains as the tests'
  reference and keeps only small files).
- **Seeks are exact or not used.** A window deep in a file is reached by seeking: the decoder
  starts early (3 s, or 0.1 s for PCM and FLAC) and the resampler restarts on a sample where its
  phase repeats (48000/gcd(rate, 48000) output samples), 4096 output samples before the window,
  so the window's samples are the whole decode's (the restart's first samples differ without
  that warm-up - measured). Frames must carry timestamps that are consecutive sample counts,
  else the file is decoded from its start. This is trusted for PCM and FLAC in their own
  containers (tested at 8-96 kHz, mono and stereo); any other format seeks only after `scan` - one
  streaming pass that also yields the waveform peaks and the length - has recorded a hash of each
  window, and every sought window is compared with it. AAC does not decode identically after a
  seek (differences of 1e-6 to 1e-3, measured, ADTS and MP4): it is caught and the file is then
  always decoded from its start (bounded memory, but a deep random read costs a decode up to that
  point). MP3 seeks matched.
- **Waveforms.** Peaks are computed by a streaming pass (equal to the old ones); a sound longer
  than 60 s is scanned on a background thread and its timeline row is flat until then.
- A file that fails part way through now plays up to the failure until the failure is seen
  (it is then silent, as before); the whole-file decode made it silent from the start.

## Evidence

- Probe: B47 in [../logs/benchmarks.md](../logs/benchmarks.md).
- Design: [../logs/decision-sessions.md](../logs/decision-sessions.md), session 26.
- Plan: [../plans/p4d-audio.md](../plans/p4d-audio.md).
- The mix per span: B70 in [../logs/benchmarks.md](../logs/benchmarks.md).
