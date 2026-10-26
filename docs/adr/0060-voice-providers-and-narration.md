# 0060. Voice providers and narration: speech made from subtitles, by engines that are plugins

- **Status:** Accepted
- **Date:** 2026-10-26
- **Deciders:** João Victor

## Context

The "Momentum, Torque and Angular Momentum" video needed a hand-written pipeline: synthesize one clip per
sentence, read each clip's length, lay the sentences out in time, make the subtitle cues and the audio clips,
and make the animation wait for each sentence. Studio could take sound only as a finished file
([0034](0034-audio-track.md)) and plugins could only add objects ([0032](0032-plugin-api.md)). The plan
([P14](../plans/p14-narration.md)) turns that workflow into a feature with a replaceable voice engine, and left
eight questions for this decision.

## Decision

**A voice provider is a plugin; narration is subtitles plus sounds.**

- **The API** is in `manim_studio.plugins`: `Voice`, `VoiceError(message, retryable)` and `VoiceProvider(name,
  label, voices, synthesize, online, supports_rate, extension, license_note, check)`, registered with `register`
  and found like any plugin (entry points, the plugin folder). `voices()` lists voices; `synthesize(text, voice,
  rate, out)` writes the file; `check()` returns why the provider cannot run here (an install hint) or None.
  Help > Plugins lists the providers a plugin added and the ones that failed to load.
- **A provider's code never runs in the editor.** `python -m manim_studio.processes.voice` takes one job (list
  the voices, or speak these texts) and answers in JSON lines; the editor's `VoiceClient` starts it, reads each
  answer as it comes, and kills it on cancel or when it goes quiet for 3 minutes (listing: 1 minute). The helper
  retries a `retryable` error with a growing pause (6 tries), writes each file under a temporary name and renames
  it when complete, and reports a bug in a provider as one failed text, not a crash. The command line runs the
  same helper (`run_job`).
- **The data model adds only optional fields**, saved only when set, so older files open and save unchanged and
  `schema_version` stays 1: `Project.voice` (the narration's voice: provider, voice id, speed),
  `Project.pronunciations` (written text -> spoken text), and on a `Cue`: `voice` (its own), `audio_id` (the
  sound made for it), `audio_key` (what that sound says) and `pause_before` (its own silence when following
  speech). The sound is an ordinary `AudioClip` ([0034](0034-audio-track.md)): a render only reads files and no
  provider is needed to open, edit or render a project.
- **Stale is derived, not stored.** The key of a cue is a hash of provider, voice, speed and the *spoken* text;
  the cue keeps the key its sound was made from, and the sound is stale when the key of the cue as it is now
  differs. Editing the text, the voice, the speed, the project's voice or the pronunciation dictionary makes
  it stale; nothing needs to remember to mark it. A stale sound keeps playing until generated again.
- **The files are named by their key**, in `<project name>_voice/` next to the project (so they travel with it)
  or, for a project not saved yet, in the user cache (`MANIM_STUDIO_VOICE_CACHE`). A cue that did not change
  never generates again, two cues with the same words share a file, and what is generated stays reproducible
  (a neural voice may say the same text differently each time: the stored file is the result, regeneration is
  explicit).
- **Generating is one undo step** that places each sound at its cue's start (a cue's own sound is replaced,
  keeping its gain) and changes no frame. Whatever finished is placed even when the rest failed or was
  cancelled; a cue edited while it was being spoken stays stale.
- **Follow speech** (off by default, also a button) retimes the cues and their sounds so each lasts as long as
  its speech and starts `pause` seconds after the previous one (a cue's `pause_before` replaces the pause for
  that cue: a longer silence between sections); the first keeps its start. It moves nothing else. Layers,
  markers and code stay where they are (Shift Timing moves them by hand); the scene grows to cover the result
  as it does for any edit ([P7.1](../plans/p7-studio-workflow.md)). **Fit speech to subtitles** goes the other
  way: it sets each cue's speed (between 0.85x and 1.25x of its own) so its speech fits the cue, says which
  cannot fit, and leaves the sounds stale to be generated again.
- **Pronunciation dictionary** (per project): whole-word replacements, longest first, never inside an earlier
  replacement, applied before synthesis; the subtitle keeps the written text.
- **Deleting a cue deletes the sound made for it** (one undo step brings both back), instead of asking: the
  sound is derived from the words.
- **Online providers** show an "Online" note, ask once before the first text is sent (remembered per provider)
  and are never contacted just because the page is shown: their voices load when the user chooses the provider
  or presses *Load voices*. The command line needs `--allow-online`. A provider that is not installed says
  what to install instead of failing.
- **Secrets**: no provider in this decision needs one. A provider that does reads an environment variable it
  names; storing keys in the system credential store (keyring) is left to the step that adds a paid provider.
- **Built-in providers**: `sapi` (Windows' own voices through PowerShell's `System.Speech`: offline, nothing
  to install, robotic) and `edge` (Microsoft Edge's neural voices through the `edge-tts` package, extra
  `tts-edge`: natural, free, online, unofficial). Kokoro, Piper and the paid cloud voices are not here: each
  needs a model download or a key with its own consent flow, and gets its own step.
- **The command line**: `manim-studio narrate project.json [-o out.json] [--voice provider:voice] [--rate r]
  [--all] [--follow-speech] [--pause s] [--allow-online] [--script file.txt]`; `render` never calls a provider.
- **Layout**: `core/voice/` (rank 3, above `editing`): cache folder, pronunciation, narration (keys, states,
  plan, place, follow, fit, script), retime, the two built-in providers; `processes/voice.py`;
  `ui/services/voice_client.py`; `ui/panels/narration_panel.py` (the Narration section of the Audio page and the
  Voice, Speech and Pause before columns of its subtitles table).

**The open questions of P14, answered**

1. *Animation timing.* Narration moves cues and their sounds only (decided earlier). A code layer written to
   wait for sentences reads the cue times when the project is built: the example's `build.py` runs
   `manim-studio narrate --follow-speech`, then reads each section's beat times from the cues and writes them
   into the code (`B = [...]`). Exposing cue times to a code layer while it runs, or rippling clips attached to
   a cue, is deferred until the example shows what is needed.
2. *Unofficial services.* A badge and a note, retries, the offline provider, and nothing depends on it.
3. *Worker isolation.* The voice helper process, with time limits and cancel.
4. *Secrets.* Deferred, see above.
5. *Determinism.* The stored file is the result; regeneration is explicit.
6. *Licence display.* A one-line note per provider; the app does not interpret licences.
7. *Pronunciation.* Decided, above.
8. *Python export.* Narration is ordinary sounds and subtitles, which the export already writes
   ([0034](0034-audio-track.md), [0035](0035-subtitle-track.md)); a generated clip is a plain untrimmed clip.

## Consequences

- A project can be narrated from its subtitles without leaving the editor, and the example video is rebuilt
  from its script and its cues alone (its schedule, every section's start and length and every beat, is
  identical to the hand-made one).
- `Cue` and `Project` gain fields, so every function that rebuilds a project field by field must carry them
  (`edits._rebuilt` does; a test round-trips them).
- The subtitles of a narrated video are one cue per sentence; a long sentence wraps to two lines. The
  example's hand-cut one-line pieces are gone.
- Neural voices mean a network. Nothing but the Generate and Preview buttons and `narrate` reaches it, each
  after consent.
- The cache folder is the user's to commit or ignore: it holds the real audio of the video.

## Alternatives considered

- **A stored "stale" flag on the cue.** It would have to be set by every edit of text, voice, speed,
  dictionary or default voice, and one forgotten path leaves a silent lie. A derived key cannot be forgotten.
- **Providers loaded and run in the editor.** A provider may load a model of hundreds of megabytes or wait on a
  network: a freeze or a crash would take the user's unsaved work with it.
- **Speak at render time.** A render would then need a network or a model and could differ run to run; it only
  reads files.
- **Ask before deleting a cue's sound.** The sound is made from the cue's words and one undo brings it back; a
  question on every delete would be noise.
- **Auto-extend the video to the speech.** Already how every edit works (the scene grows with its content).

## Evidence

- Plan: [../plans/p14-narration.md](../plans/p14-narration.md).
- Tests: `tests/core/voice/` (keys, states, plan, place, follow, fit, pause, pronunciation, properties of the
  retiming over random inputs), `tests/processes/test_voice_process.py` (the protocol, retries, bugs,
  stdout kept clean), `tests/ui/services/test_voice_client.py` (answers as they come, cancel, timeout, no
  start), `tests/ui/panels/test_narration_panel.py` (the section end to end with a fake provider),
  `tests/test_narrate_cli.py`. A fake provider writes a tone of 0.05 s per character, so no test needs a network
  or a model.
- By hand: both built-in providers spoke through the helper process (`sapi`: the installed Windows voices;
  `edge`: its voice list and a sentence); a 14 s render of the example had its sound and burned-in subtitles.
- The example: `examples/angular_momentum/build.py` is the old pipeline's replacement; every section's start and
  length and every beat equal those of the project built before.
