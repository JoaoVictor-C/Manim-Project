"""core/assist/error_tally.py: counts of errors by type (P13.1)."""

from __future__ import annotations

import threading

from manim_studio.core.assist.error_tally import ErrorTally


def test_empty_tally() -> None:
    tally = ErrorTally()
    assert tally.counts() == {} and tally.summary() == "" and tally.total == 0


def test_summary_orders_by_count_then_name() -> None:
    tally = ErrorTally()
    for name in ["SyntaxError", "NameError", "NameError", "TypeError", "NameError", "KeyError"]:
        tally.add(name)
    assert tally.summary() == "NameError x3, KeyError x1, SyntaxError x1, TypeError x1"
    assert tally.counts() == {"NameError": 3, "KeyError": 1, "SyntaxError": 1, "TypeError": 1}
    assert tally.total == 6


def test_a_blank_type_counts_as_a_plain_error() -> None:
    tally = ErrorTally()
    tally.add("")
    tally.add("  ")
    tally.add(None)  # type: ignore[arg-type]
    assert tally.counts() == {"Error": 3}


def test_counts_is_a_copy_and_clear_resets() -> None:
    tally = ErrorTally()
    tally.add("A")
    tally.counts()["A"] = 99
    assert tally.counts() == {"A": 1}
    tally.clear()
    assert tally.summary() == ""


def test_adding_from_several_threads() -> None:
    tally = ErrorTally()

    def work() -> None:
        for _ in range(500):
            tally.add("NameError")

    threads = [threading.Thread(target=work) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert tally.counts() == {"NameError": 4000}
    assert tally.summary() == "NameError x4000"
