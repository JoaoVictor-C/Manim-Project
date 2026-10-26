"""``manim-studio narrate`` (ADR 0060): speak the subtitles headless, place the sounds, write the project."""

from __future__ import annotations

from pathlib import Path

import pytest

from manim_studio import cli
from manim_studio.core.model.schema import Canvas, Cue, Project, VoiceChoice
from manim_studio.core.voice import narration
from voice_support import SECONDS_PER_CHAR

pytestmark = pytest.mark.usefixtures("fake_voice")


def write(tmp_path: Path, *texts: str, voice: VoiceChoice | None = None) -> Path:
    cues = [Cue(id=f"cue-{i}", start=i * 4.0, end=i * 4.0 + 2.0, text=t) for i, t in enumerate(texts)]
    path = tmp_path / "talk.json"
    project = Project(canvas=Canvas(duration=20.0), subtitles=cues, voice=voice)
    path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
    return path


def read(path: Path) -> Project:
    return Project.model_validate_json(path.read_text(encoding="utf-8"))


def test_it_speaks_every_subtitle_and_writes_the_project(tmp_path: Path, capsys) -> None:
    path = write(tmp_path, "first", "the second one")
    assert cli.main(["narrate", str(path), "--voice", "fake:anna"]) == 0
    out = capsys.readouterr().out
    assert "speaking 2 texts with fake" in out
    assert "2 sound(s) placed, 0 failed" in out
    project = read(path)
    assert project.voice == VoiceChoice(provider="fake", voice="anna")
    assert [(c.start, round(c.duration, 3)) for c in project.audio] == [
        (0.0, round(5 * SECONDS_PER_CHAR, 3)),
        (4.0, round(14 * SECONDS_PER_CHAR, 3)),
    ]
    assert all(narration.state(project, c) == narration.READY for c in project.subtitles)
    assert (tmp_path / "talk_voice").is_dir()  # beside the project


def test_a_second_run_speaks_nothing_new_and_all_speaks_again(tmp_path: Path, capsys) -> None:
    path = write(tmp_path, "first", "second")
    cli.main(["narrate", str(path), "--voice", "fake:anna"])
    capsys.readouterr()
    assert cli.main(["narrate", str(path)]) == 0
    assert "speaking" not in capsys.readouterr().out
    assert cli.main(["narrate", str(path), "--all"]) == 0  # the files exist: placed again, not spoken again
    assert "0 failed" in capsys.readouterr().out
    assert len(read(path).audio) == 2


def test_a_changed_subtitle_is_spoken_again_and_only_it(tmp_path: Path, capsys) -> None:
    path = write(tmp_path, "first", "second")
    cli.main(["narrate", str(path), "--voice", "fake:anna"])
    project = read(path)
    cues = [project.subtitles[0].model_copy(update={"text": "first, changed"}), project.subtitles[1]]
    path.write_text(
        project.model_copy(update={"subtitles": cues}).model_dump_json(by_alias=True), encoding="utf-8"
    )
    capsys.readouterr()
    assert cli.main(["narrate", str(path)]) == 0
    assert "speaking 1 text with fake" in capsys.readouterr().out
    assert len(read(path).audio) == 2


def test_follow_speech_script_and_an_output_file(tmp_path: Path) -> None:
    path = write(tmp_path, "first", "the second one")
    out, script = tmp_path / "narrated.json", tmp_path / "talk.txt"
    args = ["narrate", str(path), "-o", str(out), "--voice", "fake:ben", "--follow-speech", "--pause", "0.5"]
    assert cli.main([*args, "--script", str(script)]) == 0
    assert read(path).audio == []  # the input is untouched
    narrated = read(out)
    assert (narrated.subtitles[0].start, round(narrated.subtitles[1].start, 3)) == (
        0.0,
        round(5 * SECONDS_PER_CHAR + 0.5, 3),
    )
    assert script.read_text(encoding="utf-8").startswith("[0:00.0] first\n\n[0:")


def test_a_refused_subtitle_gives_exit_code_1_and_the_rest_is_kept(tmp_path: Path, capsys) -> None:
    path = write(tmp_path, "fine", "FAIL here")
    assert cli.main(["narrate", str(path), "--voice", "fake:anna"]) == 1
    assert "1 sound(s) placed, 1 failed" in capsys.readouterr().out
    assert [c.audio_id for c in read(path).subtitles] == ["voice-cue-0", None]


def test_it_needs_a_voice_and_says_so(tmp_path: Path, capsys) -> None:
    assert cli.main(["narrate", str(write(tmp_path, "hello"))]) == 2
    assert "pass --voice PROVIDER:VOICE" in capsys.readouterr().err
    assert cli.main(["narrate", str(write(tmp_path, "hello")), "--voice", "nonsense"]) == 2
    assert "--voice wants PROVIDER:VOICE" in capsys.readouterr().err


def test_an_online_voice_needs_allow_online(tmp_path: Path, capsys) -> None:
    path = write(tmp_path, "hello")
    assert cli.main(["narrate", str(path), "--voice", "edge:en-US-AndrewNeural"]) == 2
    assert "pass --allow-online" in capsys.readouterr().err
    assert read(path).audio == []  # nothing was sent or written


def test_a_missing_or_invalid_project_is_a_message_not_a_traceback(tmp_path: Path, capsys) -> None:
    assert cli.main(["narrate", str(tmp_path / "nope.json")]) == 2
    assert "cannot read" in capsys.readouterr().err
    bad = tmp_path / "bad.json"
    bad.write_text("{}x", encoding="utf-8")
    assert cli.main(["narrate", str(bad)]) == 2
    assert "not a valid project" in capsys.readouterr().err
