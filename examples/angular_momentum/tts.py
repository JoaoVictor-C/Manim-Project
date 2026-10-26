"""Narration with a neural voice (Microsoft Edge TTS, en-US-AndrewNeural): one MP3 per sentence + durations.

Needs ``edge-tts`` (pip) and an internet connection the first time; finished files are reused.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import av
import edge_tts

VOICE = "en-US-AndrewNeural"
RATE = "-9%"


async def _speak(items: list[tuple[str, Path]]) -> None:
    for text, path in items:
        for attempt in range(6):
            try:
                await edge_tts.Communicate(text, VOICE, rate=RATE).save(str(path))
                break
            except edge_tts.exceptions.NoAudioReceived:
                await asyncio.sleep(1.5 * (attempt + 1))
        else:
            raise RuntimeError(f"the voice service gave no audio for: {text!r}")


def _seconds(path: Path) -> float:
    with av.open(str(path)) as c:
        return c.duration / 1_000_000


def synthesize(sentences: dict[str, str], folder: Path) -> dict[str, tuple[Path, float]]:
    """sentences: key -> text. Returns key -> (mp3 path, seconds). Skips files that exist."""
    folder.mkdir(parents=True, exist_ok=True)
    todo = [(t, folder / f"{k}.mp3") for k, t in sentences.items() if not (folder / f"{k}.mp3").exists()]
    if todo:
        asyncio.run(_speak(todo))
    return {k: (folder / f"{k}.mp3", _seconds(folder / f"{k}.mp3")) for k in sentences}
