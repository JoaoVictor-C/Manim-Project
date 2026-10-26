# P14 — Narration: voice providers (plugins) and a Narration panel

- **Status:** Proposed (not started)
- **Date:** 2026-10-25
- **Decided in:** not yet (a decision session and ADR 0060 come first, see P14.0)
- **ADR:** 0060 — Voice providers and narration (to be written)
- **Builds on:** [0032 plugins](../adr/0032-plugin-api.md), [0034 audio track](../adr/0034-audio-track.md),
  [0035 subtitle track](../adr/0035-subtitle-track.md)

## Why

The "Momentum, Torque and Angular Momentum" video (`examples/angular_momentum/`) needed a hand-written
pipeline: synthesize one clip per sentence, read each clip's length, lay the sentences out in time, make
the subtitle cues and the audio clips, and make the animation wait for each sentence. Studio could not do
any of it: audio only comes in as a finished file, and plugins can only add objects. The goal is to make
that workflow a feature, with the voice engine replaceable.

## Goal

**Done when** a user can, without leaving the editor: write narration text on cues; pick a voice from any
installed provider; press **Generate voice**; get audio clips placed at each cue; optionally let the cues
**follow the speech** (retime to the real durations); regenerate only what changed; and export a video
whose sound and subtitles match. A provider can be added by dropping a `.py` file in the plugin folder, and
a project never needs the provider again to open, edit or render.

## Non-goals

- Voice cloning, recording or editing audio, music generation.
- Lip-sync or per-word highlighting (a later step could use word timings where a provider gives them).
- Calling a provider at render time: a render only reads files.
- Bundling model files or API keys in the repository or in project files.

## Design

### 1. Provider API — `manim_studio.plugins` (public)

```python
from manim_studio.plugins import VoiceProvider, Voice, register

def voices() -> list[Voice]: ...                       # may be slow: called lazily, cached
def synthesize(text: str, voice: str, rate: float, out: Path) -> None: ...   # writes an audio file

register(VoiceProvider(
    "edge", label="Microsoft Edge (online)", voices=voices, synthesize=synthesize,
    online=True, license_note="Unofficial service; personal use.", settings=(Param("key", "secret", ""),),
))
```

- Same discovery as ADR 0032 (entry points, `~/.manim-studio/plugins`); a failing provider is listed in
  Help > Plugins and skipped.
- `Voice(id, name, language, gender="", sample_rate=None)`; `rate` is a speed multiplier (1.0 = normal);
  providers that cannot change speed ignore it and say so (`supports_rate=False`).
- `synthesize` runs in the **worker process**, never in the UI thread, with a timeout and cancel. It
  raises `VoiceError(message, retryable)`; the host retries retryable errors with back-off (what
  `tts.py` does by hand today).
- Providers are code the user installed (as plugins are): no prompt, but `online=True` providers show a
  badge and a one-time confirmation that text leaves the computer.
- Secrets (`Param` kind `"secret"`) are stored in the OS credential store (keyring), never in a project
  file, the preferences ini or logs.

### 2. Built-in providers (optional extras, so the base install stays small)

| provider | kind | extra | notes |
|---|---|---|---|
| SAPI | offline | none (Windows) | zero install, robotic; the fallback and the test provider |
| Edge neural | online, free, unofficial | `tts-edge` (`edge-tts`) | what the example video used; retries needed |
| Kokoro | offline | `tts-kokoro` (`kokoro-onnx`) | model of about 300 MB downloaded on first use after a prompt |
| Piper | offline | `tts-piper` (`piper-tts`) | voices of 60-100 MB, downloaded on request |
| OpenAI / ElevenLabs / Azure | online, paid, licensed | `tts-cloud` | user-supplied key; the right choice for commercial work |

Model downloads: always ask first with file name, source and size (nothing downloads silently), store
under the user cache folder, verify a checksum where the source publishes one.

### 3. Data model (no schema break)

- Narration stays **subtitle cues + audio clips**: a cue gains an optional `voice: {provider, voice, rate}`
  and `audio_id` (the clip it generated). Both are saved only when set (as other optional fields are), so
  older files open unchanged and `schema_version` stays 1 unless review says otherwise.
- The generated file lives in a **project-adjacent cache** (`<project>_voice/<hash>.mp3|wav`), named by the
  hash of provider + voice + rate + text, so unchanged cues never regenerate and two cues with the same
  text share a file. The audio clip points at it by absolute path like any sound (ADR 0034).
- Editing a cue's text or voice marks its clip **stale** (shown in the UI); it keeps playing the old audio
  until regenerated. Deleting a cue asks whether to delete its clip.

### 4. Editor — a Narration section on the Audio page

- A list of cues with their text, voice chip, duration of the generated audio, and a stale marker.
- **Voice** selector (provider, voice, speed) with a **Preview** button for a short sample; a project
  default voice plus per-cue overrides.
- **Generate voice** (selected cues / all stale cues / all), with progress and cancel, running in the
  worker; each result becomes an audio clip at the cue's start.
- **Follow speech** (off by default; one-click undoable): retimes the cue and the following cues so each
  cue starts after the previous speech ends plus a pause (the gap is a setting), keeping the order. This
  is the `schedule()` step of `build.py`. A second option, **Fit speech to cues**, instead changes the
  speaking rate within limits (for example 0.85-1.25) and reports the cues that cannot fit.
- **Decided:** the first version retimes only cues and their audio; visual clips and code layers stay where
  they are (Shift Timing moves them by hand). Rippling clips attached to a cue or marker is a later step,
  after the code-layer timing question below is answered.
- Import/export `.srt` keeps working; **Export narration script** writes the cues as plain text (the
  `script.md` of the example video).
- Everything is undoable and changes no frame (render-ahead ignores it, as with audio, ADR 0034).

### 5. CLI

- `manim-studio narrate project.json [--voice provider:voice] [--rate 1.0] [--follow-speech] [--only-stale]`
  generates voices headless (for CI and scripts) and writes the project; `render` is unchanged and
  never calls a provider.

### 6. Example

- Port `examples/angular_momentum/` to the feature: its `narration.py` becomes cues in the project and
  `tts.py` goes away; `scenes.py` keeps reading its beats from the cue times (a small helper that exposes
  cue starts to a code layer, or markers the code reads; to be decided in the ADR).

## Risks and open questions (to settle in P14.0)

1. **Animation timing.** Code layers have fixed internal timing. Retiming cues must not silently
   desynchronize them. Options: expose cue/marker times to code layers as `B`-like data; or treat
   narration as the master clock and keep native clips attached to markers. Needs a decision before UI work.
2. **Online providers are unofficial or terms-limited.** Edge's service is not a public API; it can change
   or block. Mitigate with retries, a clear "online/unofficial" badge, the offline providers, and never
   making the app depend on it.
3. **Worker isolation.** Providers may load large models. Run synthesis in a separate process with memory
   and time limits so a bad provider cannot freeze or crash the editor.
4. **Secrets.** keyring availability on all platforms; fall back to an environment variable and to
   "ask each session", never to plain text.
5. **Determinism and caching.** The same text can synthesize differently run to run (some neural voices).
   Because a project stores the generated file, results stay reproducible; regeneration is explicit.
6. **Licensing display.** Per-provider one-line note, plus a link; the app does not interpret licences.
7. **Language and pronunciation.** Math reads badly ("p equals m v"). **Decided:** a per-project
   **pronunciation dictionary** (text -> spoken text), applied before synthesis with the displayed
   subtitle unchanged, is part of the first version (P14.6).
8. **Python export.** Narration is audio plus cues, so ADR 0034/0035 already export it; confirm the
   exact-vs-readable rule for generated clips (they are plain untrimmed clips: should stay readable).

## Steps

| step | content | acceptance |
|---|---|---|
| P14.0 | Decision session and ADR 0060: provider API, data model, retiming rules, secrets, worker isolation; answer the open questions above | ADR accepted; open questions closed or explicitly deferred |
| P14.1 | `VoiceProvider` API, discovery, registries, problems list, **SAPI** provider, worker-process synthesis with timeout/cancel/retry, content-addressed cache | a provider in the plugin folder is found; SAPI synthesizes a file in the worker; failures are listed; cached hit does no work (unit tests with a fake provider) |
| P14.2 | Model changes (`voice`, `audio_id` on cues, saved only when set), stale tracking, generate-and-place edits in `core/editing/edits.py` | round-trips through load/save; old files unchanged; undo restores; no frame changes |
| P14.3 | Narration section UI: voice selector, preview, generate, progress/cancel, stale markers, delete behaviour | generate for selected/all/stale; cancel leaves a valid project; UI tests |
| P14.4 | **Follow speech** and **Fit speech to cues**, pause setting, undo, report of what could not fit | cues retimed without overlap; the example's schedule reproduced exactly by the feature |
| P14.5 | Providers: Edge (extra), then Kokoro and Piper with consented model downloads, then cloud providers with keyring secrets | each provider works from the dialog; missing extra shows an install hint, not a traceback |
| P14.6 | Pronunciation dictionary, narration script export, `narrate` CLI | the example video's math reads correctly; CLI generates headless |
| P14.7 | Port `examples/angular_momentum/` to the feature; user guide page; shortcuts; release notes | the example rebuilds from cues only; docs updated; `scripts/release_check.py` passes |

## Tests

- A **fake provider** (writes a generated tone of length proportional to the text) drives all logic tests
  with no network and no models; real providers only get smoke tests behind opt-in markers.
- Conftest points `MANIM_STUDIO_PLUGINS` at an empty folder and disables network providers.
- Retiming property tests: no overlaps, order preserved, total length equals the sum of speech, pauses and
  tails; idempotent when run twice.

## Effort (rough)

P14.0 half a day; P14.1-P14.2 about one to two days; P14.3-P14.4 about two days; each provider in P14.5
a few hours (model download flows take longest); P14.6-P14.7 about a day.
