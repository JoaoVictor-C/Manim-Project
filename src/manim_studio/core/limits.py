"""The time limits of runs and a switch that lifts them (ADR 0059).

Code runs under limits so an endless loop cannot hang the editor: a code layer's render is stopped after
``RENDER_LIMIT`` seconds, the build worker after ``BUILD_LIMIT`` seconds on one request, and a Python
object's build after ``python_object.TIME_LIMIT``. A long scene (minutes of simulation, a heavy
LaTeX-filled animation) legitimately needs more, so the Code page has a **No time limit** switch.

The switch is one process-wide flag. The editor sets it from the saved option at startup and when the
button is toggled; processes the editor starts are told about it in the job they receive (the build
worker's request carries ``no_limit``), never through the environment, so a warm process that started
before the toggle still obeys it. The command-line render has no render limit and ignores the switch.
"""

from __future__ import annotations

RENDER_LIMIT = 120.0  # seconds a code layer's render may take in the editor
BUILD_LIMIT = 20.0  # seconds the build worker may spend on one request

_unlimited = False


def unlimited() -> bool:
    """True when the user lifted the time limits."""
    return _unlimited


def set_unlimited(value: bool) -> None:
    global _unlimited
    _unlimited = bool(value)
