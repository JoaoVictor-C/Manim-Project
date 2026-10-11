# P4d — Audio track

- **Status:** Done
- **Date:** 2026-10-11
- **Decided in:** [decision session 26](../logs/decision-sessions.md) (Terza, `fast`, confidence 0.91)
- **Evidence:** B47 in [../logs/benchmarks.md](../logs/benchmarks.md)
- **ADR:** [0034 — An audio track](../adr/0034-audio-track.md)

## Goal

**Done when** a sound file imported into a project can be placed, trimmed,
faded and played in sync with the frames, and the exported video and Python
scene carry the same sound.

## Schema

- `AudioClip(id, name="", path, start>=0, offset>=0, duration>0, gain=0 dB,
  fade_in>=0, fade_out>=0)`; fades together at most the duration;
  `Project.audio: list[AudioClip]`, omitted from the file when empty; ids unique
  among layers and audio clips.

## Core

- `core/audio.py`: `RATE = 48000`; `signature(path)` (mtime and size, or
  missing); `probe(path) -> seconds | None`; `decode(path) -> (2, n) float32`
  (LRU of 4, keyed by path and signature; `None` when unreadable); `peaks(path,
  per_second=100)`; `mix(project) -> (2, round(duration × RATE))`; `problems(project)`
  (clip id -> why it is silent); `signature_of(project)` (what the mix depends on).
- Edits: `add_audio`, `update_audio`, `remove_audio` (kind timing, no layers).
- `frame_cache.changed_layers` ignores `audio`.
- Export: `cairo_export` adds AAC when the project has audio.
- Python export: readable `add_sound` for plain clips (no trim, no fades, file
  plays to its end within the scene), otherwise exact; `StudioScene` mixes and
  adds the sound.

## UI

- `ui/audio_player.py`: `AudioPlayer.play(mix, t)`, `stop()`, `position() ->
  seconds | None` (None until the device starts); a fake for tests.
- Main window: playback uses the player's clock when the project has audio and
  the player is available; File > Import Audio...; missing audio in the media
  message; F5/activation re-check.
- Timeline: audio rows under the layers with waveforms; move, trim, delete,
  select (Properties: start, trim, duration, gain, fades).

## Steps

| step | content | acceptance |
|---|---|---|
| P4d.1 | schema, core/audio, edits, frame_cache, export AAC, Python export | mix equals hand-computed samples (trim, gain, fades, clipping); export's audio decodes back to the mix; readable/exact rules; missing files silent and reported |
| P4d.2 | player, playback clock, import, timeline rows, Properties, messages | playback follows a fake audio clock; import, move, trim, edit from the UI |
| P4d.3 | acceptance, docs | import a sound, place and trim it, export a video and an exact Python scene whose audio matches the mix |
