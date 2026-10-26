"""The versions of a code layer's text (P13.3): history, last working version, diff - pure, no Qt.

The Code page keeps what the user ran (and, in Live mode, what they typed) so they can go back to the
last version that worked and see what changed. This module only keeps the lists and compares texts;
the UI decides when to call it.

A **chain** is the list of versions of one layer, kept under the layer's id. Ids can be reused by the
project (a layer deleted and another added later may get the same id), so a chain is also tied to its
*content*: ``begin(layer_id, text)`` is called whenever a layer is first seen or comes back, with the
text it has then. If that text is one the chain already holds, it is the same layer (an undo of a
delete, a project reopened, a text typed back) and its history stays; if not, it is a different
layer that has the same id, and the old chain is discarded so its versions never show up for it.

Limits: a chain keeps 50 versions and one million characters of text; the oldest go first, but the
newest working version and the newest version are never dropped, so "back to the last version that
worked" always has something to go back to.
"""

from __future__ import annotations

import difflib
import time
from dataclasses import dataclass, replace

MAX_VERSIONS = 50  # versions of one layer
MAX_CHARS = 1_000_000  # characters of text of all the versions of one layer
LIVE_WINDOW = 30.0  # seconds: live versions closer than this to the one before are merged


@dataclass(frozen=True)
class Version:
    """One text of a layer. ``working`` is True when it was built/rendered without an error, False when
    it failed, None when that is not known (yet). ``source`` is ``"run"``, ``"live"`` or any label."""

    text: str
    time: float
    working: bool | None = None
    source: str = "run"


class CodeHistory:
    """The versions of many layers, one chain per layer id."""

    def __init__(self) -> None:
        self._chains: dict[str, list[Version]] = {}  # oldest first

    # -- recording ---------------------------------------------------------------------------------

    def begin(self, layer_id: str, text: str, *, now: float | None = None) -> bool:
        """A layer is first seen, or comes back, with ``text``. Returns True when a new chain started.

        With no chain for ``layer_id`` one starts (holding ``text``). With a chain that holds ``text``
        nothing changes: it is the same layer. With a chain that does not, the id belongs to another
        layer now: the old chain is discarded and a new one starts.
        """
        chain = self._chains.get(layer_id)
        if chain is not None and any(v.text == text for v in chain):
            return False
        self._chains[layer_id] = [Version(text, _now(now), None, "open")]
        return True

    def record(
        self,
        layer_id: str,
        text: str,
        working: bool | None = None,
        *,
        source: str = "run",
        now: float | None = None,
    ) -> bool:
        """Add ``text`` as the newest version of ``layer_id``; returns whether a version was added.

        A text identical to the newest version is not added (but it learns ``working`` when it was
        unknown, or when it is now known to work). A ``"live"`` version replaces the one before it when
        that is also live, less than ``LIVE_WINDOW`` seconds older and not known to work, so typing
        does not fill the history; the replacing counts as added.
        """
        when = _now(now)
        chain = self._chains.setdefault(layer_id, [])
        if chain and chain[-1].text == text:
            last = chain[-1]
            learns = (working is True and last.working is not True) or (
                last.working is None and working is not None
            )
            if learns:
                chain[-1] = replace(last, working=working)
            return False
        version = Version(text, when, working, source)
        if (
            chain
            and source == "live"
            and chain[-1].source == "live"
            and not chain[-1].working
            and 0 <= when - chain[-1].time < LIVE_WINDOW
        ):
            chain[-1] = version
        else:
            chain.append(version)
        self._trim(chain)
        return True

    def mark_working(self, layer_id: str, text: str, *, now: float | None = None) -> None:
        """``text`` reached ready/built: its newest version is a working one (added when there is none)."""
        chain = self._chains.setdefault(layer_id, [])
        for i in range(len(chain) - 1, -1, -1):
            if chain[i].text == text:
                chain[i] = replace(chain[i], working=True)
                return
        chain.append(Version(text, _now(now), True, "run"))
        self._trim(chain)

    # -- reading -----------------------------------------------------------------------------------

    def versions(self, layer_id: str) -> list[Version]:
        """The versions of ``layer_id``, newest first (empty for an unknown layer)."""
        return list(reversed(self._chains.get(layer_id, [])))

    def last_working(self, layer_id: str, before: str | None = None) -> Version | None:
        """The newest working version whose text is not ``before`` (the text now in the editor), or None."""
        for version in reversed(self._chains.get(layer_id, [])):
            if version.working is True and version.text != before:
                return version
        return None

    def contains(self, layer_id: str, text: str) -> bool:
        return any(v.text == text for v in self._chains.get(layer_id, []))

    def layer_ids(self) -> list[str]:
        return list(self._chains)

    # -- forgetting --------------------------------------------------------------------------------

    def forget(self, layer_id: str) -> None:
        """Drop the whole chain of ``layer_id`` (nothing happens for an unknown one)."""
        self._chains.pop(layer_id, None)

    def drop_unused(self, live_ids: set[str] | frozenset[str] | list[str] | tuple[str, ...]) -> list[str]:
        """Drop the chains of the layers that are not in ``live_ids``; returns the ids dropped."""
        keep = set(live_ids)
        gone = [layer_id for layer_id in self._chains if layer_id not in keep]
        for layer_id in gone:
            del self._chains[layer_id]
        return gone

    # -- limits ------------------------------------------------------------------------------------

    @staticmethod
    def _trim(chain: list[Version]) -> None:
        """Drop the oldest versions beyond the limits; the newest and the newest working one stay."""
        total = sum(len(v.text) for v in chain)
        while len(chain) > MAX_VERSIONS or total > MAX_CHARS:
            keep = _newest_working(chain)
            victim = next((i for i in range(len(chain) - 1) if i != keep), None)
            if victim is None:
                return
            total -= len(chain[victim].text)
            del chain[victim]


def _newest_working(chain: list[Version]) -> int | None:
    for i in range(len(chain) - 1, -1, -1):
        if chain[i].working is True:
            return i
    return None


def _now(now: float | None) -> float:
    return time.time() if now is None else now


# -- comparing -------------------------------------------------------------------------------------


def unified_diff(a: str, b: str, name_a: str = "before", name_b: str = "after") -> str:
    """The changes from ``a`` to ``b`` as a unified diff ('' when equal)."""
    lines_a, lines_b = _lines(a), _lines(b)
    return "".join(difflib.unified_diff(lines_a, lines_b, name_a, name_b))


def diff_stats(a: str, b: str) -> tuple[int, int]:
    """``(added, removed)``: how many lines ``b`` has that ``a`` has not, and the other way round."""
    added = removed = 0
    for line in list(difflib.unified_diff(_lines(a), _lines(b), n=0))[2:]:  # past the two file lines
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
    return added, removed


def _lines(text: str) -> list[str]:
    r"""The lines of ``text``, each ending in ``\n`` (so a missing newline at the end, or ``\r\n``
    against ``\n``, is not a change)."""
    parts = text.split("\n")
    if parts and parts[-1] == "":
        parts.pop()
    return [part.rstrip("\r") + "\n" for part in parts]
