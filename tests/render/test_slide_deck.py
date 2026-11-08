"""The HTML slide deck (ADR 0087): one video per slide, its end picture, a silent loop where a stop loops."""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import unquote

import av
import numpy as np
import pytest

from manim_studio import cli
from manim_studio.core.editing.slides import loop_window, windows
from manim_studio.core.model.schema import AudioClip, Canvas, Clip, Cue, Layer, Marker, Project, Spec
from manim_studio.core.sound import audio
from manim_studio.render.options import RenderOptions
from manim_studio.render.slide_deck import export_deck, work_folder

pytestmark = pytest.mark.slow  # renders real frames, a few dozen of them per test


def project(markers: list[Marker], sound=None, duration: float = 2.0, cues=()) -> Project:
    return Project(
        subtitles=list(cues),
        canvas=Canvas(width_px=320, height_px=180, fps=10, duration=duration, background="#202020"),
        layers=[
            Layer(
                id="c",
                spec=Spec(type="Circle", style={"stroke": "#f59e0b", "fill": "#3b82f6", "fill_opacity": 1}),
                clips=[Clip(id="k1", kind="GrowFromCenter", start=0, duration=1.0)],
            ),
            Layer(
                id="s",
                spec=Spec(
                    type="Square", params={"side_length": 1}, style={"fill": "#ef4444", "fill_opacity": 1}
                ),
                clips=[Clip(id="k2", kind="FadeIn", start=1.0, duration=1.0)],
            ),
        ],
        markers=markers,
        audio=sound or [],
    )


STOPS = [
    Marker(id="m1", t=0.5, name="circle", slide="stop"),
    Marker(id="m2", t=1.2, name="square", slide="stop", loop=0.3),
]


def decoded(path) -> list[np.ndarray]:
    with av.open(str(path)) as container:
        return [frame.to_ndarray(format="rgb24") for frame in container.decode(video=0)]


def has_sound(path) -> bool:
    with av.open(str(path)) as container:
        return bool(container.streams.audio)


def png(path) -> np.ndarray:
    with av.open(str(path)) as container:
        return next(container.decode(video=0)).to_ndarray(format="rgb24")


def manifest(html: str) -> list[dict]:
    found = re.search(r'<script id="deck" type="application/json">(.*?)</script>', html, re.S)
    return json.loads(found.group(1))["slides"]


@pytest.fixture
def sound(tmp_path) -> list[AudioClip]:
    wav = tmp_path / "tone.wav"
    audio.write_wav(np.full((2, audio.RATE * 2), 0.3, np.float32), wav)
    return [AudioClip(id="a", path=str(wav), start=0.0, duration=2.0)]


def test_a_deck_has_a_video_per_slide_an_end_picture_and_a_silent_loop(tmp_path, sound) -> None:
    proj = project(
        STOPS, sound, cues=[Cue(id="q", start=0.2, end=1.8, text="hello")]
    )  # an .srt per window, removed
    calls: list[tuple[int, int]] = []
    out = tmp_path / "out" / "talk.html"
    result = export_deck(proj, out, progress=lambda done, total: calls.append((done, total)))
    assert result.path == out and out.exists()
    files = out.parent / "talk_files"
    slides = windows(proj)
    assert [(s.first, s.last) for s in slides] == [(0, 6), (6, 13), (13, 20)]
    for slide in slides:
        n = slide.index + 1
        video = files / f"slide-{n:02d}.mp4"
        frames = decoded(video)
        assert len(frames) == slide.frames, video.name
        assert has_sound(video)
        end = png(files / f"slide-{n:02d}-end.png")
        assert end.shape == (180, 320, 3)
        assert np.abs(end.astype(int) - frames[-1].astype(int)).max() <= 2  # the video's own last frame
    loop = files / "slide-02-loop.mp4"
    a, last = loop_window(slides[1])
    assert len(decoded(loop)) == last - a == 3
    assert not has_sound(loop)
    assert sorted(p.name for p in files.glob("*-loop.mp4")) == ["slide-02-loop.mp4"]
    assert not list(files.glob("*.srt")) and not list(files.glob("*.export"))

    html = out.read_text(encoding="utf-8")
    assert "<title>talk</title>" in html  # the page's name unless a title is given
    listed = manifest(html)
    assert [s["video"] for s in listed] == [f"talk_files/slide-0{n}.mp4" for n in (1, 2, 3)]
    for entry in listed:
        for key in ("video", "end", "loop"):
            if entry[key]:
                assert (out.parent / entry[key]).exists(), entry[key]
    assert [s["loop"] for s in listed] == [None, "talk_files/slide-02-loop.mp4", None]

    total = 20 + 3  # every slide's frames and the loop's
    assert calls[-1] == (total, total)
    assert all(t == total for _, t in calls)
    assert [d for d, _ in calls] == sorted(d for d, _ in calls)  # one count across all windows
    assert not work_folder(out).exists()


def test_the_windows_follow_the_export_fps(tmp_path) -> None:
    proj = project(STOPS[:1], duration=1.0)
    out = tmp_path / "fps.html"
    export_deck(proj, out, options=RenderOptions(fps=20))
    files = tmp_path / "fps_files"
    assert (
        [len(decoded(files / f"slide-0{n}.mp4")) for n in (1, 2)]
        == [s.frames for s in windows(proj, 20)]
        == [11, 9]
    )


def test_no_stops_make_one_slide(tmp_path) -> None:
    proj = project([], duration=0.5)
    export_deck(proj, tmp_path / "one.html")
    files = tmp_path / "one_files"
    assert sorted(p.name for p in files.iterdir()) == ["slide-01-end.png", "slide-01.mp4"]
    assert len(decoded(files / "slide-01.mp4")) == 5


def test_a_new_deck_replaces_the_old_one_only_when_complete(tmp_path, monkeypatch) -> None:
    out = tmp_path / "talk.html"
    export_deck(project(STOPS, duration=2.0), out)
    old = out.read_text(encoding="utf-8")
    stale = tmp_path / "talk_files" / "slide-03.mp4"
    assert stale.exists()

    from manim_studio.render import slide_deck

    def broken(*_args, **_kwargs):
        raise RuntimeError("render failed")

    monkeypatch.setattr(slide_deck, "_end_picture", broken)
    with pytest.raises(RuntimeError):
        export_deck(project(STOPS[:1], duration=1.0), out)
    assert out.read_text(encoding="utf-8") == old and stale.exists()  # untouched
    assert not work_folder(out).exists()

    monkeypatch.undo()
    export_deck(project(STOPS[:1], duration=1.0), out)  # two slides now
    assert not stale.exists()  # the old deck's third slide went with it
    assert len(manifest(out.read_text(encoding="utf-8"))) == 2
    assert sorted(p.name for p in tmp_path.iterdir()) == ["talk.html", "talk_files"]


def test_a_deck_in_use_is_saved_beside_it(tmp_path, monkeypatch) -> None:
    """Windows will not move a folder whose video is open in a browser: the new deck takes a new name."""
    from manim_studio.render import slide_deck

    out = tmp_path / "talk.html"
    export_deck(project([], duration=0.5), out)
    old = out.read_text(encoding="utf-8")
    replace = slide_deck.os.replace

    def locked(source, target):
        if Path(source) == tmp_path / "talk_files":
            raise PermissionError("in use")
        return replace(source, target)

    monkeypatch.setattr(slide_deck.os, "replace", locked)
    result = export_deck(project(STOPS[:1], duration=1.0), out)
    assert result.path == tmp_path / "talk (2).html"
    assert result.warning and "talk_files is in use" in result.warning
    assert out.read_text(encoding="utf-8") == old  # the deck in use is as it was
    listed = manifest(result.path.read_text(encoding="utf-8"))
    assert [s["video"] for s in listed] == [
        "talk%20%282%29_files/slide-01.mp4",
        "talk%20%282%29_files/slide-02.mp4",
    ]
    for entry in listed:
        assert (tmp_path / unquote(entry["video"])).exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "talk (2).html",
        "talk (2)_files",
        "talk.html",
        "talk_files",
    ]


def test_a_folder_is_not_a_page(tmp_path) -> None:
    (tmp_path / "x.html").mkdir()
    with pytest.raises(IsADirectoryError):
        export_deck(project([], duration=0.5), tmp_path / "x.html")


def test_cli_renders_a_deck(tmp_path, capsys) -> None:
    path = tmp_path / "p.json"
    path.write_text(project(STOPS, duration=2.0).model_dump_json(by_alias=True), encoding="utf-8")
    out = tmp_path / "talk.html"
    assert cli.main(["render", str(path), str(out), "--deck", "--progress", "json"]) == 0
    messages = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
    frames = [m for m in messages if "frame" in m]
    assert frames[-1] == {"frame": 23, "total": 23}
    assert messages[-1] == {"done": str(out)}
    assert (tmp_path / "talk_files" / "slide-02-loop.mp4").exists()


def test_cli_deck_text_mode(tmp_path, capsys) -> None:
    path = tmp_path / "p.json"
    path.write_text(project([], duration=0.5).model_dump_json(by_alias=True), encoding="utf-8")
    out = tmp_path / "d.html"
    assert cli.main(["render", str(path), str(out), "--deck"]) == 0
    assert "wrote" in capsys.readouterr().out
    assert (tmp_path / "d_files" / "slide-01.mp4").exists()
