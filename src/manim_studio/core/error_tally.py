"""A running count of the errors met in this session, by kind (P13.1).

The Code page can say "NameError x3, SyntaxError x1" so a person sees which mistake keeps coming back.
In memory only, thread-safe (the runners report from Qt callbacks and worker threads). Pure: no Qt.
"""

from __future__ import annotations

import threading
from collections import Counter

UNKNOWN = "Error"  # an error that arrived without a type


class ErrorTally:
    """Counts errors by type name."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: Counter[str] = Counter()

    def add(self, error_type: str) -> None:
        """Count one error of ``error_type`` (blank counts as a plain ``Error``)."""
        with self._lock:
            self._counts[(error_type or "").strip() or UNKNOWN] += 1

    def counts(self) -> dict[str, int]:
        """A copy: type -> count, the most frequent first (ties by name)."""
        with self._lock:
            items = list(self._counts.items())
        return dict(sorted(items, key=lambda item: (-item[1], item[0])))

    @property
    def total(self) -> int:
        with self._lock:
            return sum(self._counts.values())

    def summary(self) -> str:
        """``"NameError x3, SyntaxError x1"``; empty when nothing was counted."""
        return ", ".join(f"{name} x{count}" for name, count in self.counts().items())

    def clear(self) -> None:
        with self._lock:
            self._counts.clear()
