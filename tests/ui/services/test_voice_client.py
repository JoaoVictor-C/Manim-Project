"""The editor's side of the voice helper (ADR 0060): answers as they come, cancel, timeout, no start."""

from __future__ import annotations

from pathlib import Path

import pytest

from manim_studio.ui.services.voice_client import VoiceClient

pytestmark = pytest.mark.usefixtures("qt_app", "fake_voice")


def item(name: str, text: str, folder: Path) -> dict:
    return {"id": name, "text": text, "voice": "anna", "rate": 1.0, "out": str(folder / f"{name}.wav")}


class Recorder:
    def __init__(self, client: VoiceClient) -> None:
        self.voices: list[tuple[str, dict]] = []
        self.spoken: list[tuple[str, bool, str]] = []
        self.finished: list[tuple[bool, str]] = []
        client.voicesListed.connect(lambda p, a: self.voices.append((p, a)))
        client.spoken.connect(lambda i, ok, why: self.spoken.append((i, ok, why)))
        client.speakFinished.connect(lambda ok, why: self.finished.append((ok, why)))


def test_it_lists_voices() -> None:
    client = VoiceClient()
    got = Recorder(client)
    client.list_voices("fake")
    assert client.wait()
    ((provider, answer),) = got.voices
    assert provider == "fake"
    assert [v["id"] for v in answer["voices"]] == ["anna", "ben"]


def test_it_reports_each_text_as_it_is_spoken(tmp_path: Path) -> None:
    client = VoiceClient()
    got = Recorder(client)
    assert client.speak(
        "fake", [item("a", "one", tmp_path), item("b", "FAIL two", tmp_path), item("c", "three", tmp_path)]
    )
    assert client.speaking
    assert not client.speak("fake", [item("d", "four", tmp_path)])  # one request at a time
    assert client.wait()
    assert got.spoken == [("a", True, ""), ("b", False, "this text is refused"), ("c", True, "")]
    assert got.finished == [(True, "")]
    assert (tmp_path / "a.wav").exists() and (tmp_path / "c.wav").exists()
    assert not client.busy


def test_cancel_stops_the_helper_and_keeps_no_partial_file(tmp_path: Path) -> None:
    client = VoiceClient()
    got = Recorder(client)
    client.speak("fake", [item("a", "SLOW", tmp_path), item("b", "after", tmp_path)])
    client.cancel()
    assert got.finished == [(False, "cancelled")]
    assert not client.busy
    assert not (tmp_path / "b.wav").exists()
    assert client.speak("fake", [item("c", "again", tmp_path)])  # free for the next request
    assert client.wait()
    assert got.finished[-1] == (True, "")


def test_a_helper_that_goes_quiet_is_stopped(tmp_path: Path) -> None:
    client = VoiceClient(speak_timeout_s=1.0)
    got = Recorder(client)
    client.speak("fake", [item("a", "SLOW", tmp_path), item("b", "after", tmp_path)])
    assert client.wait(15000)
    assert [(i, ok) for i, ok, _ in got.spoken] == [("a", False), ("b", False)]
    assert "no answer" in got.spoken[0][2]
    assert got.finished[0][0] is False


def test_a_provider_that_cannot_run_fails_every_text_with_its_hint(tmp_path: Path) -> None:
    client = VoiceClient()
    got = Recorder(client)
    client.speak("needs", [item("a", "x", tmp_path), item("b", "y", tmp_path)])
    assert client.wait()
    assert [(i, ok) for i, ok, _ in got.spoken] == [("a", False), ("b", False)]
    assert "pip install thing" in got.spoken[0][2]
    assert got.finished == [(False, got.spoken[0][2])]


def test_python_that_cannot_start_is_an_error_not_a_hang(tmp_path: Path) -> None:
    client = VoiceClient(program="no-such-program-for-voices")
    got = Recorder(client)
    client.speak("fake", [item("a", "x", tmp_path)])
    client.list_voices("fake")
    assert client.wait()
    assert got.spoken[0][1] is False
    assert "could not start" in got.spoken[0][2]
    assert got.voices[0][1]["ok"] is False
