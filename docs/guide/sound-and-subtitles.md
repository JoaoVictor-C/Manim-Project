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

## The Audio page

`Shift+4` lists the sounds (name, file, start, trim, duration, gain, fades) and the subtitles
(start, end, text) as tables. Double-click a cell to change it; each change is one undo step,
and an invalid one (two subtitles overlapping, fades longer than the sound) is refused with the
reason in the status bar. Clicking a subtitle's row moves the playhead to it. The **level
meter** shows the peak and RMS of the mix around the playhead. The subtitle style is in
Properties (select a subtitle), and the timeline is below, as on every page.

## See also

- [Animation](animation.md#markers) - markers, which sounds and drags snap to
- [Exporting](exporting.md) - video, `.srt` and Python export
- [The editor](the-editor.md#pages) - the pages
- [User guide index](index.md)
