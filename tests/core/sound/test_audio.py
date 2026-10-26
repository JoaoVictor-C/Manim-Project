"""The audio track (P4d.1, ADR 0034): the mix, the file model, edits, the export's sound
track and the Python export's rules."""

from __future__ import annotations

import os

import av
import numpy as np
import pytest
from pydantic import ValidationError

from manim_studio.core.editing import edits
from manim_studio.core.engine.frame_cache import changed_layers
from manim_studio.core.engine.python_export import readable_problems, to_python
from manim_studio.core.model.schema import AudioClip, Canvas, Layer, Project, Spec
from manim_studio.core.sound import audio
from manim_studio.render.cairo_export import export_video

RATE = audio.RATE
CANVAS = Canvas(width_px=160, height_px=90, fps=10, duration=2.0)
STEP = 1 / 32767  # one 16-bit level


@pytest.fixture(autouse=True)
def _fresh():
    audio.forget()
    yield
    audio.forget()


def ramp(seconds: float) -> np.ndarray:
    """Left: a slow ramp from 0 to 0.5, right: its negative - every sample tells where it is."""
    left = np.linspace(0.0, 0.5, round(seconds * RATE), dtype=np.float32)
    return np.stack([left, -left])


@pytest.fixture
def ramp_wav(tmp_path):
    path = tmp_path / "ramp.wav"
    audio.write_wav(ramp(3.0), path)
    return path


def clip(path, **fields) -> AudioClip:
    return AudioClip(id="a", path=str(path), duration=fields.pop("duration", 1.0), **fields)


def project(*clips: AudioClip, canvas: Canvas = CANVAS) -> Project:
    return Project(canvas=canvas, audio=list(clips))


def test_a_clip_is_trimmed_gained_and_faded(ramp_wav) -> None:
    sound = clip(ramp_wav, start=0.5, offset=1.0, duration=1.2, gain=-6.0, fade_in=0.2, fade_out=0.4)
    mixed = audio.mix(project(sound))
    assert mixed.shape == (2, 2 * RATE)
    assert not mixed[:, : RATE // 2].any()  # silent before its start
    source = ramp(3.0)[:, RATE : RATE + round(1.2 * RATE)]
    envelope = np.full(source.shape[1], 10 ** (-6 / 20))
    n_in, n_out = round(0.2 * RATE), round(0.4 * RATE)
    envelope[:n_in] *= (np.arange(n_in) + 0.5) / n_in
    envelope[-n_out:] *= ((np.arange(n_out) + 0.5) / n_out)[::-1]
    expected = source * envelope
    got = mixed[:, RATE // 2 : RATE // 2 + expected.shape[1]]
    assert np.abs(got - expected).max() <= 2 * STEP
    assert not mixed[:, RATE // 2 + expected.shape[1] :].any()  # silent after its end


def test_clips_add_up_are_clipped_and_end_with_the_canvas(tmp_path, ramp_wav) -> None:
    loud = tmp_path / "loud.wav"
    audio.write_wav(np.full((2, 3 * RATE), 0.8, np.float32), loud)
    a = clip(loud, duration=3.0)
    b = AudioClip(id="b", path=str(loud), start=1.5, duration=3.0)
    late = AudioClip(id="c", path=str(ramp_wav), start=5.0, duration=1.0)  # after the end: ignored
    mixed = audio.mix(project(a, b, late))
    assert mixed.shape == (2, 2 * RATE)  # cut at the canvas end
    assert mixed[0, RATE] == pytest.approx(0.8, abs=2 * STEP)
    assert mixed[0, round(1.6 * RATE)] == 1.0  # 1.6 clipped


def test_a_file_shorter_than_the_clip_is_silent_past_its_end(ramp_wav) -> None:
    mixed = audio.mix(project(clip(ramp_wav, offset=2.5, duration=1.5)))
    assert mixed[0, RATE // 4] > 0 and not mixed[:, RATE // 2 + 10 :].any()


def test_other_formats_and_rates_are_resampled(tmp_path) -> None:
    path = tmp_path / "tone.mp3"
    t = np.arange(44_100) / 44_100
    tone = np.stack([0.5 * np.sin(2 * np.pi * 440 * t)] * 2).astype(np.float32)
    with av.open(str(path), "w") as out:
        stream = out.add_stream("libmp3lame", rate=44_100, layout="stereo")
        resampler = av.AudioResampler(format=stream.codec_context.format.name, layout="stereo", rate=44_100)
        frame = av.AudioFrame.from_ndarray(tone, format="fltp", layout="stereo")
        frame.sample_rate = 44_100
        for packet in [p for f in resampler.resample(frame) for p in stream.encode(f)] + list(
            stream.encode()
        ):
            out.mux(packet)
    assert audio.probe(str(path)) == pytest.approx(1.0, abs=0.06)
    decoded = audio.decode(str(path))
    assert decoded.shape[0] == 2 and decoded.shape[1] == pytest.approx(RATE, abs=0.06 * RATE)
    assert np.abs(decoded).max() == pytest.approx(0.5, abs=0.05)


def test_missing_and_unreadable_files_are_silent_and_say_why(tmp_path, ramp_wav) -> None:
    junk = tmp_path / "junk.mp3"
    junk.write_text("not a sound", encoding="utf-8")
    clips = [
        clip(tmp_path / "gone.wav"),
        AudioClip(id="b", path=str(junk), duration=1.0),
        AudioClip(id="c", path=str(ramp_wav), duration=1.0),
    ]
    assert audio.problems(project(*clips)) == {"a": "file not found", "b": "cannot read the file"}
    assert audio.probe(str(tmp_path / "gone.wav")) is None and audio.probe(str(junk)) is None
    mixed = audio.mix(project(*clips[:2]))
    assert mixed.shape == (2, 2 * RATE) and not mixed.any()


def test_a_rewritten_file_is_read_again(tmp_path) -> None:
    path = tmp_path / "sound.wav"
    audio.write_wav(np.full((2, RATE), 0.25, np.float32), path)
    first = audio.mix(project(clip(path))).copy()
    audio.write_wav(np.full((2, 2 * RATE), 0.5, np.float32), path)  # another size: another signature
    second = audio.mix(project(clip(path)))
    assert first[0, 100] == pytest.approx(0.25, abs=STEP) and second[0, 100] == pytest.approx(0.5, abs=STEP)


def test_waveform_peaks(ramp_wav) -> None:
    peaks = audio.peaks(str(ramp_wav), per_second=10)
    assert len(peaks) == 30
    assert peaks[0] == pytest.approx(0.5 / 30, abs=1e-3) and peaks[-1] == pytest.approx(0.5, abs=1e-3)


def test_the_decoded_files_kept_are_bounded(tmp_path) -> None:
    for i in range(6):
        path = tmp_path / f"s{i}.wav"
        audio.write_wav(np.zeros((2, 10), np.float32), path)
        audio.decode(str(path))
    assert len(audio._DECODED) == audio._DECODED_KEEP


# -- the model and edits ---------------------------------------------------------------


def test_the_file_format() -> None:
    silent = Project(canvas=CANVAS, layers=[Layer(id="dot", spec=Spec(type="Dot"))])
    assert "audio" not in silent.model_dump(by_alias=True)  # files without sound save as before
    sound = silent.model_copy(update={"audio": [AudioClip(id="a", path="x.wav", duration=2.0, gain=-3)]})
    again = Project.model_validate_json(sound.model_dump_json(by_alias=True))
    assert again == sound and again.audio[0].gain == -3
    with pytest.raises(ValidationError, match="fades are longer"):
        AudioClip(id="a", path="x.wav", duration=1.0, fade_in=0.6, fade_out=0.5)
    with pytest.raises(ValidationError, match="duplicate"):
        Project(
            layers=[Layer(id="a", spec=Spec(type="Dot"))], audio=[AudioClip(id="a", path="x", duration=1)]
        )


def test_sound_edits_keep_every_frame_and_layer_edits_keep_the_sound() -> None:
    base = Project(canvas=CANVAS, layers=[Layer(id="dot", spec=Spec(type="Dot"))])
    added = edits.add_audio(base, "music.wav", start=0.5, duration=3.0, name="Music")
    sound = added.project.audio[0]
    assert (sound.id, sound.name, sound.start, sound.duration) == ("audio-1", "Music", 0.5, 3.0)
    assert added.kind == "timing" and added.layer_ids == frozenset()
    assert changed_layers(base, added.project) == set()  # render-ahead keeps every frame
    louder = edits.update_audio(added.project, "audio-1", gain=6.0, fade_in=0.5)
    assert louder.project.audio[0].gain == 6.0 and louder.kind == "timing"
    moved = edits.update_layer(louder.project, "dot", name="Moved")
    assert moved.project.audio == louder.project.audio  # rebuilt projects keep their sound
    second = edits.add_audio(moved.project, "hit.wav", start=1.0, duration=0.2)
    assert [c.id for c in second.project.audio] == ["audio-1", "audio-2"]
    assert edits.remove_audio(second.project, "audio-1").project.audio == [second.project.audio[1]]
    with pytest.raises(edits.EditError):
        edits.remove_audio(base, "audio-1")


def test_trimming_the_left_edge_keeps_the_sound_in_place() -> None:
    sound = edits.add_audio(Project(canvas=CANVAS), "music.wav", start=1.0, duration=3.0).project
    trimmed = edits.trim_audio(sound, "audio-1", start=1.5).project.audio[0]
    assert (trimmed.start, trimmed.offset, trimmed.duration) == (1.5, 0.5, 2.5)
    back = edits.trim_audio(sound, "audio-1", start=0.2).project.audio[0]  # cannot start before the file
    assert (back.start, back.offset, back.duration) == (1.0, 0.0, 3.0)
    shorter = edits.trim_audio(sound, "audio-1", end=2.0).project.audio[0]
    assert (shorter.start, shorter.offset, shorter.duration) == (1.0, 0.0, 1.0)


# -- export ---------------------------------------------------------------------------


def decoded_track(path) -> np.ndarray:
    with av.open(str(path)) as container:
        assert container.streams.audio, "no sound track"
        return np.concatenate([f.to_ndarray() for f in container.decode(audio=0)], axis=1)


MANIM_DELAY = 1024  # Manim's own mp4s start the sound 1024 samples late (AAC priming, B47)


def sound_lag(track: np.ndarray, mix: np.ndarray, most: int = 2 * MANIM_DELAY) -> int:
    """How many samples later ``track`` plays ``mix`` (cross-correlation of the left channels)."""
    n = min(track.shape[1], mix.shape[1])
    a, b = mix[0, :n].astype(np.float64), track[0, :n].astype(np.float64)
    spectrum = np.fft.irfft(np.fft.rfft(b, 2 * n) * np.conj(np.fft.rfft(a, 2 * n)))
    lags = np.r_[spectrum[: most + 1], spectrum[-most:]]
    best = int(np.argmax(lags))
    return best if best <= most else best - len(lags)


def assert_plays(track: np.ndarray, mix: np.ndarray, lag: int = 0) -> None:
    """``track`` is ``mix`` played ``lag`` samples late (within AAC's error)."""
    assert sound_lag(track, mix) == lag
    n = min(track.shape[1] - lag, mix.shape[1])
    assert np.abs(track[:, lag : lag + n] - mix[:, :n]).mean() < 0.01


def beeps(path, seconds: float = 3.0) -> None:
    """A 440 Hz beep in each second (0.25-0.6 s): sharp edges show any misalignment."""
    t = np.arange(round(seconds * RATE)) / RATE
    gate = ((t % 1.0) >= 0.25) & ((t % 1.0) < 0.6)
    audio.write_wav(np.stack([0.5 * gate * np.sin(2 * np.pi * 440 * t)] * 2).astype(np.float32), path)


def test_the_exported_video_carries_the_mix(tmp_path) -> None:
    beeps(tmp_path / "beeps.wav")
    sound = clip(tmp_path / "beeps.wav", start=0.3, offset=0.5, duration=1.2, gain=-3.0, fade_out=0.3)
    proj = Project(canvas=CANVAS, layers=[Layer(id="dot", spec=Spec(type="Dot"))], audio=[sound])
    out = tmp_path / "with sound.mp4"
    export_video(proj, out)
    track = decoded_track(out)
    expected = audio.mix(proj)
    assert track.shape == expected.shape
    assert_plays(track, expected)  # aligned to the sample (B47)
    silent = tmp_path / "silent.mp4"
    export_video(proj.model_copy(update={"audio": []}), silent)
    with av.open(str(silent)) as container:
        assert not container.streams.audio


def test_plain_sounds_export_as_add_sound_and_others_make_the_scene_exact(tmp_path, ramp_wav) -> None:
    whole = clip(ramp_wav, start=0.5, duration=3.0, gain=-2.0)
    long_canvas = Canvas(width_px=160, height_px=90, fps=10, duration=4.0)
    plain = project(whole, canvas=long_canvas)
    assert readable_problems(plain) == []
    code = to_python(plain, "Sound").code
    assert f"self.add_sound({str(ramp_wav)!r}, time_offset=0.5, gain=-2.0)" in code

    def problems(**changes) -> list[str]:
        return readable_problems(project(whole.model_copy(update=changes), canvas=long_canvas))

    assert problems(offset=0.5, duration=2.5) == ["a: a trimmed sound"]
    assert problems(duration=2.0) == ["a: a trimmed sound"]
    assert problems(fade_in=0.5) == ["a: a faded sound"]
    assert problems(start=2.0) == ["a: a sound longer than the scene"]
    assert problems(path=str(tmp_path / "gone.wav")) == ["a: file not found"]
    exact = to_python(project(whole.model_copy(update={"fade_in": 0.5}), canvas=long_canvas), "Sound")
    assert not exact.readable and "#   - a: a faded sound" in exact.code


@pytest.mark.slow
def test_exported_scenes_render_with_the_editors_sound(tmp_path) -> None:
    """Both forms rendered by `manim render`: the readable add_sound and the exact scene's mix,
    1024 samples late as all of Manim's sound (deviations.md)."""
    import subprocess
    import sys

    canvas = Canvas(width_px=160, height_px=90, fps=10, duration=4.0)
    beeps(tmp_path / "beeps.wav")
    for name, sound in (
        ("Plain", clip(tmp_path / "beeps.wav", start=0.5, duration=3.0)),
        ("Exact", clip(tmp_path / "beeps.wav", start=0.5, offset=1.0, duration=2.0, fade_in=0.5)),
    ):
        proj = Project(canvas=canvas, layers=[Layer(id="dot", spec=Spec(type="Dot"))], audio=[sound])
        export = to_python(proj, name)
        assert export.readable == (name == "Plain")
        scene = tmp_path / f"{name.lower()}.py"
        scene.write_text(export.code, encoding="utf-8")
        media = tmp_path / f"media-{name}"
        done = subprocess.run(
            [sys.executable, "-m", "manim", "render", str(scene), name, "--media_dir", str(media)],
            capture_output=True,
            text=True,
            cwd=tmp_path,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        assert done.returncode == 0, done.stderr[-2000:]
        assert_plays(decoded_track(next(media.rglob(f"{name}.mp4"))), audio.mix(proj), MANIM_DELAY)
