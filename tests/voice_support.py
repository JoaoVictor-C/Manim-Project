"""A fake voice provider for the narration tests (ADR 0060): no network, no engine, no model.

``install_fake`` writes it as a plugin file, so the voice helper process (which loads plugins from
``MANIM_STUDIO_PLUGINS`` like any process) finds it too, and registers it in this process.

It "speaks" a tone of ``0.05 s`` per character of the text (so a longer text lasts longer, as speech does)
at 8000 Hz. Special texts: containing ``FAIL`` it raises a plain error; ``FLAKY`` fails twice with a
retryable error (counted in a file next to the output) and then works; ``BROKEN`` raises a bug of its own.
"""

from __future__ import annotations

import sys
import wave
from pathlib import Path

import pytest

from manim_studio import plugins

SECONDS_PER_CHAR = 0.05

PLUGIN = """
import math
import struct
import wave
from pathlib import Path

from manim_studio.plugins import Voice, VoiceError, VoiceProvider, register

RATE = 8000


def voices():
    return [Voice("anna", "Anna", "en-US", "female"), Voice("ben", "Ben", "en-GB", "male")]


def synthesize(text, voice, rate, out):
    if "FAIL" in text:
        raise VoiceError("this text is refused")
    if "SLOW" in text:
        import time

        time.sleep(30)
    if "PRINTY" in text:
        print("a provider that talks on stdout")
    if "BROKEN" in text:
        raise ZeroDivisionError("a bug in the provider")
    if "FLAKY" in text:
        counter = out.parent / ("flaky-" + out.stem.split(".")[0] + ".count")
        n = int(counter.read_text()) if counter.exists() else 0
        counter.write_text(str(n + 1))
        if n < 2:
            raise VoiceError("busy, try again", retryable=True)
    seconds = len(text) * PER_CHAR / rate
    frames = int(seconds * RATE)
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(i / 8))) for i in range(frames)))


def missing():
    return "the thing is not installed. Install it with: pip install thing"


register(VoiceProvider("needs", "Needs an install (tests)", voices, synthesize, check=missing))
register(VoiceProvider("fake", "Fake voices (tests)", voices, synthesize, extension=".wav",
                       license_note="Tones."))
""".replace("PER_CHAR", repr(SECONDS_PER_CHAR))


def install_fake(folder: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Write the fake provider into ``folder`` (a plugin folder every process of the test sees)."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "fake_voice.py"
    path.write_text(PLUGIN, encoding="utf-8")
    monkeypatch.setenv("MANIM_STUDIO_PLUGINS", str(folder))
    monkeypatch.setenv("MANIM_STUDIO_VOICE_BACKOFF", "0")
    plugins.load_file(path)


def forget_fake() -> None:
    plugins.unregister("voice:fake")
    plugins.unregister("voice:needs")
    sys.modules.pop("manim_studio_plugin_fake_voice", None)


def seconds_of(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / w.getframerate()
