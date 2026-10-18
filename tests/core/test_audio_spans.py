"""The mix computed per span, files decoded on demand (ADR 0034 amendment, B70).

Every test compares against the reference: the whole-file decode (``audio._decode``) and a copy of
the whole-scene mix as it was before spans, kept here verbatim so a change to the engine cannot
change the reference with it. Equality is ``np.array_equal`` - not close, the same samples.
"""

from __future__ import annotations

import random

import av
import numpy as np
import pytest

from manim_studio.core import audio, levels
from manim_studio.core.schema import AudioClip, Canvas, Layer, Project, Spec
from manim_studio.render import cairo_export
from manim_studio.render.cairo_export import export_video
from manim_studio.render.options import RenderOptions

RATE = audio.RATE


@pytest.fixture(autouse=True)
def _fresh():
    audio.forget()
    yield
    audio.forget()


# -- the reference: the mix before spans (copied, not imported) -----------------------------------


def reference_clip_samples(clip: AudioClip) -> np.ndarray:
    length = round(clip.duration * RATE)
    out = np.zeros((2, length), np.float32)
    samples = audio._decode(clip.path) if audio.signature(clip.path) != audio.MISSING else None
    if samples is None:
        return out
    first = round(clip.offset * RATE)
    part = samples[:, first : first + length]
    out[:, : part.shape[1]] = part
    envelope = np.full(length, 10 ** (clip.gain / 20), np.float32)
    for seconds, ramp in ((clip.fade_in, 1), (clip.fade_out, -1)):
        n = min(length, round(seconds * RATE))
        if n:
            shape = (np.arange(n, dtype=np.float32) + 0.5) / n
            if ramp > 0:
                envelope[:n] *= shape
            else:
                envelope[length - n :] *= shape[::-1]
    return out * envelope


def reference_mix(project: Project) -> np.ndarray:
    total = round(project.canvas.duration * RATE)
    out = np.zeros((2, total), np.float32)
    for clip in project.audio:
        first = round(clip.start * RATE)
        if first >= total:
            continue
        samples = reference_clip_samples(clip)[:, : total - first]
        out[:, first : first + samples.shape[1]] += samples
    np.clip(out, -1.0, 1.0, out=out)
    return out


# -- sound files ------------------------------------------------------------------------------------


def signal(rate: int, seconds: float, channels: int) -> np.ndarray:
    """A tone with a gated overtone: every region differs from its neighbours."""
    t = np.arange(round(rate * seconds)) / rate
    tone = 0.3 * np.sin(2 * np.pi * 220 * t) + 0.15 * np.sin(2 * np.pi * 1730 * t) * (t % 1 < 0.5)
    rows = [tone, 0.7 * tone + 0.05 * np.sin(2 * np.pi * 97 * t)][:channels]
    return np.stack(rows).astype(np.float32)


def write_pcm(path, rate: int, channels: int, seconds: float) -> None:
    import wave

    data = signal(rate, seconds, channels)
    with wave.open(str(path), "wb") as out:
        out.setnchannels(channels)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes((data.T * 32767).round().astype("<i2").tobytes())


def write_encoded(path, codec: str, rate: int, channels: int, seconds: float, fmt=None) -> None:
    data = signal(rate, seconds, channels)
    layout = "stereo" if channels == 2 else "mono"
    with av.open(str(path), "w", format=fmt) as out:
        stream = out.add_stream(codec, rate=rate, layout=layout)
        resampler = av.AudioResampler(format=stream.codec_context.format.name, layout=layout, rate=rate)
        frame = av.AudioFrame.from_ndarray(np.ascontiguousarray(data), format="fltp", layout=layout)
        frame.sample_rate = rate
        frame.pts = 0
        for f in [*resampler.resample(frame), *resampler.resample(None)]:
            out.mux(stream.encode(f))
        out.mux(stream.encode())


FORMATS = {
    "m44.wav": lambda p, s: write_pcm(p, 44_100, 1, s),
    "s48.wav": lambda p, s: write_pcm(p, 48_000, 2, s),
    "m22.wav": lambda p, s: write_pcm(p, 22_050, 1, s),
    "s96.wav": lambda p, s: write_pcm(p, 96_000, 2, s),
    "m11.wav": lambda p, s: write_pcm(p, 11_025, 1, s),
    "s44.flac": lambda p, s: write_encoded(p, "flac", 44_100, 2, s),
    "s44.mp3": lambda p, s: write_encoded(p, "libmp3lame", 44_100, 2, s),
    "m48.mp3": lambda p, s: write_encoded(p, "libmp3lame", 48_000, 1, s),
    "s44.m4a": lambda p, s: write_encoded(p, "aac", 44_100, 2, s),
    "s48.aac": lambda p, s: write_encoded(p, "aac", 48_000, 2, s, fmt="adts"),
}


@pytest.fixture(scope="module")
def files(tmp_path_factory) -> dict[str, str]:
    folder = tmp_path_factory.mktemp("sounds")
    out = {}
    for name, write in FORMATS.items():
        write(folder / name, 9.0)
        out[name] = str(folder / name)
    return out


@pytest.fixture
def short_warm_up(monkeypatch):
    """Seek in 9-second files: decode 0.5 s before a seek target instead of 3 s."""
    monkeypatch.setattr(audio, "WARM_SECONDS", 0.5)


# -- decoding on demand -----------------------------------------------------------------------------


@pytest.mark.parametrize("name", list(FORMATS))
def test_a_region_decoded_on_demand_is_that_region_of_the_whole_decode(files, name, short_warm_up) -> None:
    path = files[name]
    whole = audio._decode(path)
    assert whole.shape[1] > 8 * RATE
    if name.endswith((".mp3", ".m4a", ".aac")):
        audio.scan(path)  # a seek in these formats is trusted only once checked against the scan
    rng = random.Random(name)
    spans = [(0, 10), (audio.CHUNK - 5, 10), (whole.shape[1] - 100, 500), (whole.shape[1] + 7, 3)]
    spans += [(rng.randrange(whole.shape[1]), rng.randrange(1, 3 * audio.CHUNK)) for _ in range(10)]
    for start, count in spans:
        audio.forget_windows()  # every span decoded afresh, not from a window kept by the last
        got = audio.file_span(path, start, count)
        assert np.array_equal(got, whole[:, start : start + count]), (start, count)


def test_trusted_formats_seek_and_others_only_once_checked(files, short_warm_up) -> None:
    deep = 6 * audio.CHUNK  # past the warm-up: a reader starts with a seek
    audio.file_span(files["m44.wav"], deep, 10)
    assert audio.COUNTS["seeks"] == 1 and audio.COUNTS["mismatches"] == 0
    audio.file_span(files["s44.mp3"], deep, 10)
    assert audio.COUNTS["seeks"] == 1  # not checked yet: decoded from the start
    audio.scan(files["s44.mp3"])
    audio.forget_windows()
    audio.file_span(files["s44.mp3"], deep, 10)
    assert audio.COUNTS["seeks"] == 2 and audio.COUNTS["mismatches"] == 0
    aac = files["s48.aac"]  # AAC after a seek is close, not equal: caught, decoded from the start
    audio.scan(aac)
    whole = audio._decode(aac)
    assert np.array_equal(audio.file_span(aac, deep, 10), whole[:, deep : deep + 10])
    assert audio.COUNTS["seeks"] == 3 and audio.COUNTS["mismatches"] == 1
    audio.forget_windows()
    assert np.array_equal(audio.file_span(aac, deep + 3 * audio.CHUNK, 10), whole[:, deep + 3 * audio.CHUNK :][:, :10])
    assert audio.COUNTS["seeks"] == 3 and audio.COUNTS["mismatches"] == 1  # the file is not sought again


def test_reading_on_continues_without_seeking_again(files, short_warm_up) -> None:
    path = files["m44.wav"]
    for k in range(3, 7):
        audio.file_span(path, k * audio.CHUNK, audio.CHUNK)
    assert audio.COUNTS["seeks"] == 1  # one seek, then the same reader went on


def test_decoded_windows_are_bounded_in_bytes_and_no_whole_file_is_kept(files, monkeypatch) -> None:
    monkeypatch.setattr(audio, "WINDOW_BYTES", 3 * audio.CHUNK * 8)
    path = files["s48.wav"]
    whole = audio._decode(path)
    for start in range(0, whole.shape[1], RATE // 2):
        assert np.array_equal(audio.file_span(path, start, RATE // 2), whole[:, start : start + RATE // 2])
        assert audio.window_bytes() <= audio.WINDOW_BYTES
    assert not audio._DECODED  # nothing decoded whole


def test_missing_and_unreadable_files_read_as_nothing(tmp_path) -> None:
    junk = tmp_path / "junk.mp3"
    junk.write_text("not a sound", encoding="utf-8")
    assert audio.file_span(str(junk), 0, 100) is None
    assert audio.file_span(str(tmp_path / "gone.wav"), 0, 100) is None


def test_a_rewritten_file_is_read_again(tmp_path) -> None:
    path = tmp_path / "s.wav"
    audio.write_wav(np.full((2, RATE), 0.25, np.float32), path)
    first = audio.file_span(str(path), 10, 1)
    audio.write_wav(np.full((2, 2 * RATE), 0.5, np.float32), path)
    assert first[0, 0] == pytest.approx(0.25, abs=1e-4)
    assert audio.file_span(str(path), 10, 1)[0, 0] == pytest.approx(0.5, abs=1e-4)


# -- the mix per span -------------------------------------------------------------------------------


def random_project(rng: random.Random, paths: list[str], seconds: float) -> Project:
    clips = []
    for i in range(rng.randrange(1, 5)):
        duration = rng.choice([0.01, 0.3, 1.0, 2.7, 6.0, 12.0])
        fade_in = min(duration / 2, rng.choice([0.0, 0.0, 0.05, duration / 3]))
        fade_out = rng.choice([0.0, 0.0, 0.2 * duration, duration - fade_in])
        clips.append(
            AudioClip(
                id=f"a{i}",
                path=rng.choice(paths),
                start=rng.choice([0.0, rng.uniform(0, seconds), seconds - 0.1, seconds + 1.0]),
                offset=rng.choice([0.0, rng.uniform(0, 4.0), 8.95]),
                duration=duration,
                gain=rng.choice([0.0, -6.0, 12.0, rng.uniform(-30, 20)]),
                fade_in=fade_in,
                fade_out=max(0.0, min(fade_out, duration - fade_in)),
            )
        )
    canvas = Canvas(width_px=160, height_px=90, fps=10, duration=seconds)
    return Project(canvas=canvas, audio=clips)


def test_any_span_of_the_mix_equals_that_slice_of_the_whole_mix(files, tmp_path, short_warm_up) -> None:
    """Random projects (overlaps, trims, offsets past the file's end, gains that clip, fades,
    clips past the scene's end, a missing file) and random spans: the same samples."""
    paths = [files["m44.wav"], files["s48.wav"], files["s44.flac"], files["s44.mp3"], str(tmp_path / "gone")]
    audio.scan(files["s44.mp3"])
    rng = random.Random(70)
    for _ in range(12):
        project = random_project(rng, paths, rng.choice([1.0, 4.5, 10.0]))
        whole = reference_mix(project)
        total = whole.shape[1]
        assert np.array_equal(audio.mix(project), whole)
        edges = [round(c.start * RATE) for c in project.audio] + [round(c.end * RATE) for c in project.audio]
        spans = [(0, 0), (0, total), (total, 10), (total + 50, 10), (max(0, total - 3), 100)]
        spans += [(max(0, e - rng.randrange(1, 2000)), rng.randrange(1, 5000)) for e in edges]
        spans += [(rng.randrange(total), rng.randrange(0, total)) for _ in range(6)]
        for start, count in spans:
            got = audio.mix_span(project, start, count)
            assert got.dtype == np.float32
            assert np.array_equal(got, whole[:, start : start + count]), (project, start, count)


def test_the_envelope_of_a_span_equals_the_whole_clips_far_into_a_long_fade() -> None:
    """Past 2**24 samples a float32 index is no longer exact: the span's ramp must be computed as the
    whole clip's is (an int index, then float32), not from a float32 range starting mid-clip."""
    clip = AudioClip(id="a", path="x.wav", duration=380.0, fade_in=10.0, fade_out=369.0, gain=-3.0)
    length = round(clip.duration * RATE)
    whole = np.full(length, 10 ** (clip.gain / 20), np.float32)
    n_in, n_out = round(clip.fade_in * RATE), round(clip.fade_out * RATE)
    whole[:n_in] *= (np.arange(n_in, dtype=np.float32) + 0.5) / n_in
    whole[length - n_out :] *= ((np.arange(n_out, dtype=np.float32) + 0.5) / n_out)[::-1]
    for lo in (0, n_in - 3, 2**24 - 7, 2**24 + 1001, length - 5000):
        hi = min(length, lo + 4000)
        assert np.array_equal(audio.envelope(clip, lo, hi), whole[lo:hi]), lo


def test_the_level_window_is_a_span_of_the_mix(files) -> None:
    clip = AudioClip(id="a", path=files["m44.wav"], start=0.5, duration=3.0, fade_in=1.0, gain=-2.0)
    project = Project(canvas=Canvas(width_px=160, height_px=90, fps=10, duration=4.0), audio=[clip])
    whole = reference_mix(project)
    for t0, t1 in ((0.0, 0.1), (1.234, 1.334), (3.95, 4.05)):
        first, last = round(t0 * RATE), min(round(t1 * RATE), whole.shape[1])
        assert np.array_equal(levels.window_samples(project, t0, t1), whole[:, first:last])


def test_a_source_reads_spans_and_is_the_whole_mix_as_an_array(files) -> None:
    clip = AudioClip(id="a", path=files["s48.wav"], start=0.2, duration=2.0, fade_out=0.5)
    project = Project(canvas=Canvas(width_px=160, height_px=90, fps=10, duration=3.0), audio=[clip])
    source = audio.source(project)
    whole = reference_mix(project)
    assert source.length == whole.shape[1]
    assert np.array_equal(source.span(1000, 5000), whole[:, 1000:6000])
    assert np.array_equal(np.asarray(source), whole) and np.array_equal(source, whole)


# -- waveform peaks ----------------------------------------------------------------------------------


def reference_peaks(path: str, per_second: int) -> np.ndarray:
    samples = audio._decode(path)
    if samples is None or not samples.shape[1]:
        return np.zeros(0, np.float32)
    loud = np.abs(samples).max(axis=0)
    step = RATE // per_second
    padded = np.pad(loud, (0, -len(loud) % step))
    return padded.reshape(-1, step).max(axis=1)


@pytest.mark.parametrize("per_second", [100, 10, 7, 1])
def test_peaks_are_streamed_and_equal_the_whole_decodes(files, per_second) -> None:
    for name in ("m44.wav", "s44.mp3"):
        assert np.array_equal(audio.peaks(files[name], per_second), reference_peaks(files[name], per_second))
    assert not audio._DECODED


def test_peaks_are_ready_only_once_scanned(files) -> None:
    path = files["m22.wav"]
    assert audio.peaks_ready(path, 100) is None
    audio.scan(path)
    assert np.array_equal(audio.peaks_ready(path, 100), reference_peaks(path, 100))


def test_problems_and_probe_do_not_decode_whole_files(files, tmp_path) -> None:
    clip = AudioClip(id="a", path=files["s44.mp3"], duration=1.0)
    assert audio.problem(clip) is None and audio.probe(files["s44.mp3"]) == pytest.approx(9.0, abs=0.1)
    assert not audio._DECODED


# -- the export --------------------------------------------------------------------------------------


def decoded_track(path) -> np.ndarray:
    with av.open(str(path)) as container:
        return np.concatenate([f.to_ndarray() for f in container.decode(audio=0)], axis=1)


def reference_track(tmp_path, samples: np.ndarray) -> np.ndarray:
    """The sound track as the export wrote it before spans: the whole mix in one frame."""
    out = tmp_path / "reference.mp4"
    with av.open(str(out), mode="w") as container:
        stream = container.add_stream("aac", rate=RATE, layout="stereo")
        resampler = av.AudioResampler(format=stream.codec_context.format.name, layout="stereo", rate=RATE)
        frame = av.AudioFrame.from_ndarray(np.ascontiguousarray(samples), format="fltp", layout="stereo")
        frame.sample_rate = RATE
        frame.pts = 0
        for resampled in [*resampler.resample(frame), *resampler.resample(None)]:
            container.mux(stream.encode(resampled))
        container.mux(stream.encode())
    return decoded_track(out)


def test_the_exported_sound_is_the_one_exported_before_spans(files, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(cairo_export, "AUDIO_SPAN", 7_000)  # many spans, none aligned to AAC's 1024
    clips = [
        AudioClip(id="a", path=files["m44.wav"], start=0.3, offset=0.5, duration=1.6, gain=-3.0, fade_out=0.3),
        AudioClip(id="b", path=files["s48.wav"], start=1.1, duration=0.8, gain=6.0, fade_in=0.2),
    ]
    canvas = Canvas(width_px=160, height_px=90, fps=10, duration=2.0)
    proj = Project(canvas=canvas, layers=[Layer(id="dot", spec=Spec(type="Dot"))], audio=clips)
    whole = reference_mix(proj)
    out = tmp_path / "new.mp4"
    export_video(proj, out)
    assert np.array_equal(decoded_track(out), reference_track(tmp_path, whole))
    ranged = tmp_path / "range.mp4"  # frames 5 to 17: the sound from 0.5 s to 1.7 s
    export_video(proj, ranged, options=RenderOptions(start=0.5, end=1.7))
    cut = whole[:, round(0.5 * RATE) : round(1.7 * RATE)]
    assert np.array_equal(decoded_track(ranged), reference_track(tmp_path, cut))
