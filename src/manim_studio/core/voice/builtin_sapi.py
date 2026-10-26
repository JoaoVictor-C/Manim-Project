"""Windows' own voices (SAPI, ``System.Speech``): offline, nothing to install, a robotic sound.

They are spoken by Windows PowerShell, one text per call (ADR 0060). The text goes through a file and
the voice, speed and output through the environment, so nothing the user wrote is ever part of a
command line.
"""

from __future__ import annotations

import math
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from ...plugins import Voice, VoiceError, VoiceProvider

TIMEOUT_S = 120

_LIST = r"""
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
foreach ($v in $s.GetInstalledVoices()) {
  $i = $v.VoiceInfo
  "{0}`t{1}`t{2}" -f $i.Name, $i.Culture.Name, $i.Gender
}
"""

_SPEAK = r"""
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
if ($env:MS_VOICE) { $s.SelectVoice($env:MS_VOICE) }
$s.Rate = [int]$env:MS_RATE
$s.SetOutputToWaveFile($env:MS_OUT)
$s.Speak([IO.File]::ReadAllText($env:MS_TEXT, [Text.Encoding]::UTF8))
$s.Dispose()
"""


def _powershell() -> str | None:
    return shutil.which("powershell") or shutil.which("pwsh")


def check() -> str | None:
    if sys.platform != "win32":
        return "Windows voices exist only on Windows"
    if _powershell() is None:
        return "Windows PowerShell was not found"
    return None


def _run(script: str, env: dict[str, str]) -> subprocess.CompletedProcess:
    exe = _powershell()
    if exe is None:
        raise VoiceError("Windows PowerShell was not found")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        return subprocess.run(
            [exe, "-NoProfile", "-NonInteractive", "-Command", script],
            env={**os.environ, **env},
            capture_output=True,
            timeout=TIMEOUT_S,
            creationflags=flags,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise VoiceError(f"Windows took longer than {TIMEOUT_S} s to speak", retryable=True) from None


def voices() -> list[Voice]:
    done = _run(_LIST, {})
    if done.returncode != 0:
        raise VoiceError(done.stderr.decode("utf-8", errors="replace").strip() or "could not list the voices")
    found = []
    for line in done.stdout.decode("utf-8", errors="replace").splitlines():
        name, _, rest = line.strip().partition("\t")
        culture, _, gender = rest.partition("\t")
        if name:
            found.append(Voice(name, name, culture, gender.lower()))
    return found


def sapi_rate(rate: float) -> int:
    """SAPI's -10..10 for a speed multiplier (+10 is about three times as fast)."""
    return max(-10, min(10, round(math.log(rate) / math.log(3) * 10)))


def synthesize(text: str, voice: str, rate: float, out: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="manim-studio-sapi-") as folder:
        text_file = Path(folder) / "text.txt"
        text_file.write_text(text, encoding="utf-8")
        env = {
            "MS_TEXT": str(text_file),
            "MS_OUT": str(out),
            "MS_VOICE": voice,
            "MS_RATE": str(sapi_rate(rate)),
        }
        done = _run(_SPEAK, env)
    if done.returncode != 0 or not out.exists():
        reason = done.stderr.decode("utf-8", errors="replace").strip().splitlines()
        raise VoiceError(reason[0] if reason else "Windows could not speak the text")


PROVIDER = VoiceProvider(
    "sapi",
    "Windows voices (offline)",
    voices,
    synthesize,
    online=False,
    extension=".wav",
    license_note="Part of Windows; check your Windows licence for public use.",
    check=check,
)
