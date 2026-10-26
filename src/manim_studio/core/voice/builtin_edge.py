"""Microsoft Edge's neural voices through the ``edge-tts`` package: natural, free, online.

An unofficial service (ADR 0060): it can change or refuse without notice, so a request that gets no
audio is retried by the voice helper, and nothing else depends on it. The text is sent to Microsoft.
Install the extra: ``pip install "manim-studio[tts-edge]"``.
"""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

from ...plugins import Voice, VoiceError, VoiceProvider

INSTALL = 'Install it with: pip install "manim-studio[tts-edge]"'


def check() -> str | None:
    return (
        None if importlib.util.find_spec("edge_tts") else f"the edge-tts package is not installed. {INSTALL}"
    )


def voices() -> list[Voice]:
    import edge_tts

    try:
        listed = asyncio.run(edge_tts.list_voices())
    except Exception as exc:
        raise VoiceError(f"could not reach the voice service: {exc}", retryable=True) from exc
    found = [
        Voice(v["ShortName"], v["ShortName"], v.get("Locale", ""), v.get("Gender", "").lower())
        for v in listed
    ]
    return sorted(found, key=lambda v: (v.language, v.id))


def percent(rate: float) -> str:
    """edge-tts wants the speed as a signed percentage ("-9%")."""
    return f"{round((rate - 1.0) * 100):+d}%"


def synthesize(text: str, voice: str, rate: float, out: Path) -> None:
    import edge_tts

    try:
        asyncio.run(edge_tts.Communicate(text, voice, rate=percent(rate)).save(str(out)))
    except edge_tts.exceptions.NoAudioReceived as exc:
        raise VoiceError("the voice service sent no audio", retryable=True) from exc
    except edge_tts.exceptions.EdgeTTSException as exc:
        raise VoiceError(str(exc) or type(exc).__name__, retryable=False) from exc
    except OSError as exc:  # no connection, a dropped one
        raise VoiceError(f"could not reach the voice service: {exc}", retryable=True) from exc


PROVIDER = VoiceProvider(
    "edge",
    "Microsoft Edge neural (online)",
    voices,
    synthesize,
    online=True,
    extension=".mp3",
    license_note="An unofficial service meant for Edge's own read-aloud: personal use.",
    check=check,
)
