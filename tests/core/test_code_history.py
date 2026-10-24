"""The versions of a code layer (P13.3): chains, working versions, caps, live coalescing, diffs."""

from __future__ import annotations

from manim_studio.core import code_history
from manim_studio.core.code_history import CodeHistory, Version, diff_stats, unified_diff


def texts(history: CodeHistory, layer: str = "a") -> list[str]:
    return [v.text for v in history.versions(layer)]


class TestRecord:
    def test_adds_and_lists_newest_first(self):
        h = CodeHistory()
        assert h.record("a", "one", now=1.0)
        assert h.record("a", "two", now=2.0)
        assert texts(h) == ["two", "one"]
        assert h.versions("a")[0] == Version("two", 2.0, None, "run")

    def test_the_same_text_as_the_last_is_not_added(self):
        h = CodeHistory()
        h.record("a", "one")
        assert not h.record("a", "one")
        assert len(h.versions("a")) == 1

    def test_an_earlier_text_again_is_a_new_version(self):
        h = CodeHistory()
        for t in ("one", "two", "one"):
            assert h.record("a", t)
        assert texts(h) == ["one", "two", "one"]

    def test_working_is_remembered(self):
        h = CodeHistory()
        h.record("a", "one", True)
        h.record("a", "two", False)
        h.record("a", "three")
        assert [v.working for v in h.versions("a")] == [None, False, True]

    def test_the_same_text_learns_that_it_works(self):
        h = CodeHistory()
        h.record("a", "one")
        assert not h.record("a", "one", True)
        assert h.versions("a")[0].working is True

    def test_a_working_text_is_not_downgraded(self):
        h = CodeHistory()
        h.record("a", "one", True)
        h.record("a", "one", False)
        h.record("a", "one", None)
        assert h.versions("a")[0].working is True

    def test_the_same_text_learns_that_it_failed_only_when_unknown(self):
        h = CodeHistory()
        h.record("a", "one")
        h.record("a", "one", False)
        assert h.versions("a")[0].working is False
        h.record("a", "one", True)  # fixed elsewhere (a helper): it works now
        assert h.versions("a")[0].working is True

    def test_layers_are_separate(self):
        h = CodeHistory()
        h.record("a", "x")
        h.record("b", "y")
        assert texts(h, "a") == ["x"] and texts(h, "b") == ["y"]

    def test_source_and_time_default(self):
        h = CodeHistory()
        h.record("a", "x", source="manual")
        version = h.versions("a")[0]
        assert version.source == "manual" and version.time > 0

    def test_unknown_layer(self):
        h = CodeHistory()
        assert h.versions("zzz") == []
        assert h.last_working("zzz") is None
        assert not h.contains("zzz", "x")


class TestMarkWorking:
    def test_marks_the_newest_version_with_that_text(self):
        h = CodeHistory()
        h.record("a", "one")
        h.record("a", "two")
        h.mark_working("a", "one")
        assert [v.working for v in h.versions("a")] == [None, True]

    def test_marks_the_newest_of_equal_texts(self):
        h = CodeHistory()
        for t in ("one", "two", "one"):
            h.record("a", t)
        h.mark_working("a", "one")
        assert [v.working for v in h.versions("a")] == [True, None, None]

    def test_adds_a_version_when_there_is_none(self):
        h = CodeHistory()
        h.mark_working("a", "one", now=5.0)
        assert h.versions("a") == [Version("one", 5.0, True, "run")]

    def test_keeps_the_other_fields(self):
        h = CodeHistory()
        h.record("a", "one", source="live", now=3.0)
        h.mark_working("a", "one")
        assert h.versions("a")[0] == Version("one", 3.0, True, "live")


class TestLastWorking:
    def make(self):
        h = CodeHistory()
        h.record("a", "v1", True)
        h.record("a", "v2", True)
        h.record("a", "v3", False)
        h.record("a", "v4")
        return h

    def test_newest_working(self):
        assert self.make().last_working("a").text == "v2"

    def test_not_the_text_in_the_editor(self):
        h = self.make()
        assert h.last_working("a", before="v2").text == "v1"
        assert h.last_working("a", before="v1").text == "v2"
        assert h.last_working("a", before="v4").text == "v2"

    def test_none_when_nothing_else_works(self):
        h = CodeHistory()
        h.record("a", "v1", True)
        h.record("a", "v2", False)
        assert h.last_working("a", before="v1") is None
        assert h.last_working("a").text == "v1"

    def test_unknown_is_not_working(self):
        h = CodeHistory()
        h.record("a", "v1")
        assert h.last_working("a") is None


class TestBegin:
    def test_starts_a_chain(self):
        h = CodeHistory()
        assert h.begin("a", "code", now=1.0)
        assert h.versions("a") == [Version("code", 1.0, None, "open")]

    def test_the_same_text_keeps_the_history(self):
        h = CodeHistory()
        h.begin("a", "one")
        h.record("a", "two", True)
        h.record("a", "three")
        assert not h.begin("a", "three")  # the layer is seen again as it was
        assert texts(h) == ["three", "two", "one"]

    def test_an_older_text_of_the_chain_keeps_the_history(self):
        h = CodeHistory()
        h.begin("a", "one")
        h.record("a", "two")
        assert not h.begin("a", "one")  # reverted or undone: still this layer
        assert texts(h) == ["two", "one"]

    def test_a_reused_id_with_other_text_starts_over(self):
        h = CodeHistory()
        h.begin("a", "old layer")
        h.record("a", "old layer, edited", True)
        assert h.begin("a", "a different layer")
        assert texts(h) == ["a different layer"]
        assert h.last_working("a") is None

    def test_undo_of_a_delete_gets_its_history_back(self):
        h = CodeHistory()
        h.begin("a", "x = 1")
        h.record("a", "x = 2", True)
        # the layer is deleted (nothing is forgotten yet) and the delete is undone
        assert not h.begin("a", "x = 2")
        assert h.last_working("a").text == "x = 2"
        assert len(h.versions("a")) == 2

    def test_after_the_chain_is_dropped_the_returning_layer_starts_over(self):
        h = CodeHistory()
        h.begin("a", "x")
        h.drop_unused(set())
        assert h.begin("a", "x")
        assert texts(h) == ["x"]


class TestLimits:
    def test_at_most_fifty_versions(self):
        h = CodeHistory()
        for i in range(80):
            h.record("a", f"v{i}")
        found = texts(h)
        assert len(found) == code_history.MAX_VERSIONS == 50
        assert found[0] == "v79" and found[-1] == "v30"

    def test_the_total_text_is_capped(self):
        h = CodeHistory()
        chunk = "x" * 300_000
        for i in range(6):
            h.record("a", f"{i}{chunk}")
        found = texts(h)
        assert sum(len(t) for t in found) <= code_history.MAX_CHARS
        assert found[0].startswith("5") and len(found) == 3

    def test_the_newest_working_version_is_never_dropped(self):
        h = CodeHistory()
        h.record("a", "the one that worked", True)
        for i in range(120):
            h.record("a", f"broken {i}", False)
        found = texts(h)
        assert len(found) == 50
        assert "the one that worked" in found
        assert h.last_working("a").text == "the one that worked"
        assert found[0] == "broken 119"

    def test_only_the_newest_working_version_is_protected(self):
        h = CodeHistory()
        h.record("a", "old working", True)
        h.record("a", "newer working", True)
        for i in range(60):
            h.record("a", f"v{i}")
        found = texts(h)
        assert "newer working" in found and "old working" not in found

    def test_the_newest_version_stays_even_when_it_alone_is_too_big(self):
        h = CodeHistory()
        h.record("a", "small")
        h.record("a", "y" * (code_history.MAX_CHARS + 10))
        assert len(texts(h)) == 1

    def test_a_big_working_version_is_kept_and_the_rest_make_room(self):
        h = CodeHistory()
        h.record("a", "w" * 600_000, True)
        for i in range(4):
            h.record("a", f"{i}" + "z" * 200_000)
        found = texts(h)
        assert any(t.startswith("w") for t in found)
        assert sum(len(t) for t in found) <= code_history.MAX_CHARS

    def test_mark_working_also_trims(self):
        h = CodeHistory()
        for i in range(50):
            h.record("a", f"v{i}")
        h.mark_working("a", "a text never recorded")
        assert len(texts(h)) == 50


class TestLive:
    def test_live_versions_close_together_merge(self):
        h = CodeHistory()
        h.record("a", "run", True, now=0.0)
        assert h.record("a", "l1", source="live", now=10.0)
        assert h.record("a", "l2", source="live", now=20.0)
        assert h.record("a", "l3", source="live", now=29.0)
        assert texts(h) == ["l3", "run"]
        assert h.versions("a")[0].time == 29.0

    def test_the_window_is_counted_from_the_version_before(self):
        h = CodeHistory()
        h.record("a", "l1", source="live", now=0.0)
        h.record("a", "l2", source="live", now=29.0)  # merges: replaces l1, at 29
        h.record("a", "l3", source="live", now=58.0)  # 29 s after the last: merges again
        assert texts(h) == ["l3"]

    def test_live_versions_30_seconds_apart_do_not_merge(self):
        h = CodeHistory()
        h.record("a", "l1", source="live", now=0.0)
        h.record("a", "l2", source="live", now=30.0)
        assert texts(h) == ["l2", "l1"]

    def test_a_live_version_does_not_replace_a_run(self):
        h = CodeHistory()
        h.record("a", "run", source="run", now=0.0)
        h.record("a", "live", source="live", now=1.0)
        assert texts(h) == ["live", "run"]

    def test_a_run_does_not_replace_a_live_version(self):
        h = CodeHistory()
        h.record("a", "live", source="live", now=0.0)
        h.record("a", "run", source="run", now=1.0)
        assert texts(h) == ["run", "live"]

    def test_a_working_live_version_is_not_replaced(self):
        h = CodeHistory()
        h.record("a", "l1", True, source="live", now=0.0)
        h.record("a", "l2", source="live", now=1.0)
        assert texts(h) == ["l2", "l1"]

    def test_a_live_version_that_failed_is_replaced(self):
        h = CodeHistory()
        h.record("a", "l1", False, source="live", now=0.0)
        h.record("a", "l2", source="live", now=1.0)
        assert texts(h) == ["l2"]

    def test_live_only_replaces_within_its_own_layer(self):
        h = CodeHistory()
        h.record("a", "la", source="live", now=0.0)
        h.record("b", "lb", source="live", now=1.0)
        assert texts(h, "a") == ["la"]

    def test_identical_live_text_is_not_added(self):
        h = CodeHistory()
        h.record("a", "same", source="live", now=0.0)
        assert not h.record("a", "same", source="live", now=1.0)

    def test_merged_live_versions_still_respect_the_caps(self):
        h = CodeHistory()
        for i in range(100):
            h.record("a", f"v{i}", True, now=float(i))
            h.record("a", f"l{i}", source="live", now=float(i) + 0.5)
        assert len(texts(h)) <= 50


class TestForget:
    def test_forget_one(self):
        h = CodeHistory()
        h.record("a", "x")
        h.record("b", "y")
        h.forget("a")
        h.forget("never seen")
        assert h.versions("a") == [] and texts(h, "b") == ["y"]

    def test_drop_unused(self):
        h = CodeHistory()
        for layer in ("a", "b", "c"):
            h.record(layer, layer)
        assert sorted(h.drop_unused({"b"})) == ["a", "c"]
        assert h.layer_ids() == ["b"]
        assert h.drop_unused(["b", "z"]) == []

    def test_drop_unused_with_nothing_live(self):
        h = CodeHistory()
        h.record("a", "x")
        h.drop_unused(frozenset())
        assert h.layer_ids() == []


class TestDiff:
    def test_unified_diff(self):
        diff = unified_diff("a\nb\nc\n", "a\nB\nc\n")
        lines = diff.splitlines()
        assert lines[:2] == ["--- before", "+++ after"]
        assert "-b" in lines and "+B" in lines
        assert " a" in lines and " c" in lines

    def test_names(self):
        diff = unified_diff("x\n", "y\n", "run 1", "run 2")
        assert diff.startswith("--- run 1\n+++ run 2\n")

    def test_equal_texts_have_no_diff(self):
        assert unified_diff("a\nb", "a\nb") == ""
        assert diff_stats("a\nb", "a\nb") == (0, 0)

    def test_a_missing_final_newline_is_not_a_change(self):
        assert unified_diff("a\nb\n", "a\nb") == ""

    def test_line_endings_are_not_changes(self):
        assert unified_diff("a\r\nb\r\n", "a\nb\n") == ""

    def test_every_line_of_the_diff_ends_with_a_newline(self):
        assert unified_diff("a", "b").endswith("\n")

    def test_stats(self):
        assert diff_stats("a\nb\nc\n", "a\nB\nc\nd\n") == (2, 1)
        assert diff_stats("", "a\nb\n") == (2, 0)
        assert diff_stats("a\nb\n", "") == (0, 2)

    def test_stats_count_lines_that_look_like_headers(self):
        assert diff_stats("-- a\n", "++ a\n") == (1, 1)
        assert diff_stats("x\n", "++ b\n--- c\n") == (2, 1)

    def test_blank_line_changes_count(self):
        assert diff_stats("a\nb\n", "a\n\nb\n") == (1, 0)
