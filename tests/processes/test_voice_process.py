"""The voice helper process (ADR 0060): one job in, JSON lines out, retries, no partial files."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from voice_support import SECONDS_PER_CHAR, seconds_of

pytestmark = pytest.mark.usefixtures("fake_voice")


def run(job: dict) -> list[dict]:
    done = subprocess.run(
        [sys.executable, "-m", "manim_studio.processes.voice"],
        input=json.dumps(job) + "\n",
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return [json.loads(line) for line in done.stdout.splitlines()]  # stdout carries only the protocol


def item(name: str, text: str, folder: Path, **kw) -> dict:
    return {"id": name, "text": text, "voice": "anna", "rate": 1.0, "out": str(folder / f"{name}.wav"), **kw}


def test_it_lists_a_providers_voices() -> None:
    (answer,) = run({"op": "voices", "provider": "fake"})
    assert answer["ok"]
    assert [(v["id"], v["language"], v["gender"]) for v in answer["voices"]] == [
        ("anna", "en-US", "female"),
        ("ben", "en-GB", "male"),
    ]


def test_it_speaks_each_text_to_its_file(tmp_path: Path) -> None:
    items = [item("a", "x" * 20, tmp_path), item("b", "y" * 40, tmp_path, rate=2.0)]
    assert run({"op": "speak", "provider": "fake", "items": items}) == [
        {"id": "a", "ok": True},
        {"id": "b", "ok": True},
        {"done": True},
    ]
    assert seconds_of(tmp_path / "a.wav") == pytest.approx(20 * SECONDS_PER_CHAR, abs=0.01)
    assert seconds_of(tmp_path / "b.wav") == pytest.approx(40 * SECONDS_PER_CHAR / 2.0, abs=0.01)  # the speed
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.wav", "b.wav"]  # no partial file is left


def test_a_refused_text_is_reported_and_the_others_still_go(tmp_path: Path) -> None:
    items = [item("a", "FAIL this", tmp_path), item("b", "fine", tmp_path)]
    answers = run({"op": "speak", "provider": "fake", "items": items})
    assert answers[0] == {"id": "a", "ok": False, "error": "this text is refused"}
    assert answers[1] == {"id": "b", "ok": True}
    assert not (tmp_path / "a.wav").exists()
    assert not list(tmp_path.glob("*.part*"))


def test_a_retryable_error_is_tried_again(tmp_path: Path) -> None:
    answers = run({"op": "speak", "provider": "fake", "items": [item("a", "FLAKY text", tmp_path)]})
    assert answers[0] == {"id": "a", "ok": True}  # it failed twice, then spoke
    assert (tmp_path / "flaky-a.count").read_text() == "3"


def test_it_gives_up_after_the_tries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MANIM_STUDIO_VOICE_TRIES", "2")
    (answer, _) = run({"op": "speak", "provider": "fake", "items": [item("a", "FLAKY text", tmp_path)]})
    assert answer == {"id": "a", "ok": False, "error": "busy, try again"}


def test_a_bug_in_a_provider_is_one_failed_text_not_a_crash(tmp_path: Path) -> None:
    items = [item("a", "BROKEN", tmp_path), item("b", "fine", tmp_path)]
    answers = run({"op": "speak", "provider": "fake", "items": items})
    assert answers[0]["ok"] is False
    assert "ZeroDivisionError: a bug in the provider" in answers[0]["error"]
    assert answers[1] == {"id": "b", "ok": True}


def test_what_a_provider_prints_does_not_break_the_protocol(tmp_path: Path) -> None:
    answers = run({"op": "speak", "provider": "fake", "items": [item("a", "PRINTY", tmp_path)]})
    assert answers == [{"id": "a", "ok": True}, {"done": True}]


def test_a_provider_that_cannot_run_says_what_to_install(tmp_path: Path) -> None:
    (answer, done) = run({"op": "speak", "provider": "needs", "items": [item("a", "x", tmp_path)]})
    assert answer["ok"] is False
    assert answer["unavailable"] is True
    assert "pip install thing" in answer["error"]
    assert done == {"done": True}
    listed, _ = run({"op": "voices", "provider": "needs"})
    assert listed["unavailable"] is True


def test_an_unknown_provider_is_an_error_not_a_traceback(tmp_path: Path) -> None:
    answer, done = run({"op": "voices", "provider": "nope"})
    assert answer == {"ok": False, "error": "no voice provider named 'nope'"}
    assert done == {"done": True}
