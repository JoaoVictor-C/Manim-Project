# Sound and subtitles

## Sounds

**File > Import Audio...** adds a sound file (WAV, MP3, OGG, FLAC, M4A, AAC) at the playhead.
It appears as a row with its waveform under the object rows (a sound longer than a minute
shows a flat row for a moment while its waveform is scanned in the background). The file is
referenced by path, not copied into the project.

- **On the timeline:** drag a sound to move it, drag its edges to trim it; right-click its row
  for **Delete sound**. Right-click a clip for **Add sound at start** / **Add sound at end**,
  or a marker for **Add sound here** - handy for sound effects; each lists the project's sounds
  and **Other file...**.
- **In Properties** (select the sound): Name, Start, Trim start (seconds of the file skipped),
  Duration, Gain (-60 to +24 dB), Fade in and Fade out.
- **Playback:** playing the timeline plays the mix in sync, from the sound card's clock. The
  mix is computed in short pieces, so long sounds (15 minutes and more) use little memory.
- **Export:** the video carries the mix as AAC audio. The readable Python export uses Manim's
  `add_sound`, which plays whole files at their gain; a trimmed or faded sound, or one longer than
  the scene, makes the Python export exact ([why](exporting.md#readable-or-exact)).

## Subtitles

**Edit > Add Subtitle** (`Ctrl+T`) adds a subtitle at the playhead; type its text in
Properties. Subtitles have their own **Subtitles** row on the timeline: drag one to move it,
drag its edges to change its times, right-click it to delete it, or right-click empty space on
the row for **Add subtitle here**. Two subtitles cannot overlap.

Properties of a subtitle: **Start**, **End** and **Text**, and the **Subtitle style (all
subtitles)**: Size, Height (where the line sits), Colour, Band (a box behind the text), Band
colour, Band opacity, Fade, Width (where lines wrap) and **Burn in** (draw them into the
video).

- **File > Import Subtitles...** reads an `.srt` file; **File > Export Subtitles...** writes
  one.
- **Export:** with Burn in on, the video shows the subtitles; in every case an `.srt` is
  written beside the video unless you choose otherwise on the Deliver page (burned in and an
  `.srt`, only the `.srt`, or none) or with `--subtitles` on the command line.

## Narration (a voice reads the subtitles)

The **Narration** section of the Audio page (`Ctrl+4`) speaks the subtitles with a computer voice and puts
each result on the timeline as a sound at its subtitle's start. Type or import the subtitles first; then:

1. **Provider, Language, Voice, Speed.** *Windows voices (offline)* need nothing and sound robotic. *Microsoft
   Edge neural (online)* sounds natural but needs the `tts-edge` extra (`pip install "manim-studio[tts-edge]"`,
   the section says so when it is missing) and sends the subtitle text to Microsoft's service: the editor asks
   once before it does, and does not contact it until you choose it (*Load voices* loads its list). The voice
   is the project's; tick **Selected subtitle only** to give one subtitle its own. **Preview** says the selected
   subtitle (or a sample) without touching the project.
2. **Generate voice** speaks the new and changed subtitles (the arrow also offers *Selected subtitle* and *All
   subtitles (again)*), with progress and **Cancel**. Everything that finished is placed as one undo step, even
   if the rest failed or was cancelled. The sound of a subtitle that did not change is never made again, and
   two subtitles with the same words share one file; the files are in `<project name>_voice/` next to the
   project.
3. The subtitles table has **Voice**, **Speech** and **Pause before** columns. A subtitle whose text, voice,
   speed, the project's voice or the pronunciation changed since its sound was made shows **stale**: its old
   sound keeps playing until you generate again. Deleting a subtitle deletes its sound (undo brings both back).
4. **Follow speech** (the box, to do it after generating, or the button, to do it now) moves the subtitles and
   their sounds so each lasts as long as its speech and starts after the previous one plus the pause; the
   first stays where it is. **Pause before** gives one subtitle its own silence (a longer one between sections).
   Nothing else moves: Shift Timing moves layers and markers by hand. The video grows to hold the result.
   **Fit speech to subtitles** does it the other way round: it sets each subtitle's speed (0.85x to 1.25x) so
   its speech fits it and says which cannot fit; generate again to hear it.
5. **Pronunciation...** says how words are spoken ("F" -> "force"): the subtitle keeps what is written, the voice
   says the right column. **Export script...** writes the narration as plain text.

From the command line, `manim-studio narrate project.json --voice edge:en-US-AndrewNeural --follow-speech
--allow-online` does the same without the editor (`--all` speaks everything again, `--script` writes the text);
`render` never calls a voice.

**Another voice engine** is a plugin: a `.py` file in the plugin folder (see [Plugins](objects.md#plugins))
that registers a voice provider:

```python
from pathlib import Path
from manim_studio.plugins import Voice, VoiceError, VoiceProvider, register

def voices():  # runs in a helper process, never in the editor
    return [Voice("anna", "Anna", language="en-US", gender="female")]

def synthesize(text: str, voice: str, rate: float, out: Path) -> None:
    ...  # write the speech to `out`; raise VoiceError("busy", retryable=True) to be tried again

register(VoiceProvider("anna", "Anna (offline)", voices, synthesize, extension=".wav"))
```

Help > Plugins lists the providers each plugin added.

## The Audio page

`Ctrl+4` lists the sounds (name, file, start, trim, duration, gain, fades) and the subtitles
(start, end, text, voice, speech, pause before) as tables. Double-click a cell to change it; each change is one undo step,
and an invalid one (two subtitles overlapping, fades longer than the sound) is refused with the
reason in the status bar. Clicking a subtitle's row moves the playhead to it. The **level
meter** shows the peak and RMS of the mix around the playhead. The subtitle style is in
Properties (select a subtitle), and the timeline is below, as on every page.

## See also

- [Animation](animation.md#markers) - markers, which sounds and drags snap to
- [Exporting](exporting.md) - video, `.srt` and Python export
- [The editor](the-editor.md#pages) - the pages
- [User guide index](index.md)
