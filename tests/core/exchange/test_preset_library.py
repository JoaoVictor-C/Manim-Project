"""The preset library (P12.2): built-in + user + online presets in one file."""

from __future__ import annotations

import json
import os

import pytest

from manim_studio.core.code import python_templates
from manim_studio.core.exchange import preset_library
from manim_studio.core.exchange.preset_library import Preset, PresetLibrary

CODE = "PARAMS = {'a': 1}\n\n\ndef build(p):\n    return Circle()\n"


@pytest.fixture
def path(tmp_path):
    return tmp_path / "presets.json"


@pytest.fixture
def library(path):
    return PresetLibrary(path)


def saved(library):
    return [p for p in library.presets() if not p.builtin]


class TestBuiltins:
    def test_come_from_the_templates_first(self, library):
        builtin = library.presets()
        assert [p.name for p in builtin] == list(python_templates.TEMPLATES)
        for preset, (name, code) in zip(builtin, python_templates.TEMPLATES.items(), strict=True):
            assert (preset.kind, preset.origin, preset.code, preset.builtin) == (
                "object",
                "builtin",
                code,
                True,
            )
            assert preset.id == f"builtin:{name.lower().replace(' ', '-')}"

    def test_have_a_description(self, library):
        assert all(p.description for p in library.presets())

    def test_are_never_saved(self, library, path):
        library.add("Mine", "object", CODE)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert [p["name"] for p in data["presets"]] == ["Mine"]

    def test_cannot_be_removed_or_renamed(self, library):
        builtin = library.presets()[0]
        with pytest.raises(ValueError, match="built-in"):
            library.remove(builtin.id)
        with pytest.raises(ValueError, match="built-in"):
            library.rename(builtin.id, "Other")
        assert library.get(builtin.id) == builtin

    def test_ids_are_unique(self, monkeypatch, path):
        monkeypatch.setattr(python_templates, "TEMPLATES", {"A b": "x", "a-b": "y", "!!!": "z"})
        ids = [p.id for p in PresetLibrary(path).presets()]
        assert ids == ["builtin:a-b", "builtin:a-b-2", "builtin:preset"]

    def test_are_not_taken_from_the_file(self, path):
        entry = {"name": "Fake", "kind": "object", "code": "x", "origin": "builtin"}
        path.write_text(json.dumps({"format": 1, "presets": [entry]}), encoding="utf-8")
        assert [p for p in PresetLibrary(path).presets() if p.name == "Fake"] == []


class TestAdd:
    def test_returns_the_stored_preset(self, library):
        preset = library.add("My object", "object", CODE, description="d", tags=("a", "b"))
        assert preset == Preset(
            id="user:my-object", name="My object", kind="object", code=CODE, origin="user",
            description="d", tags=("a", "b"), source_url="",
        )  # fmt: skip
        assert library.get("user:my-object") == preset

    def test_online(self, library):
        preset = library.add("From web", "scene", "x", origin="online", source_url="https://example.org/a.py")
        assert preset.id == "online:from-web"
        assert (preset.origin, preset.kind, preset.source_url) == (
            "online",
            "scene",
            "https://example.org/a.py",
        )

    def test_a_helper_is_a_kind_of_preset_too(self, library, path):  # ADR 0058
        preset = library.add("Grid tools", "helper", "def grid():\n    return 1\n")
        assert (preset.kind, preset.id) == ("helper", "user:grid-tools")
        assert [p.kind for p in saved(PresetLibrary(path))] == ["helper"]  # read back from the file
        assert [p.name for p in library.search("helper")] == ["Grid tools"]

    def test_tags_may_be_a_list(self, library):
        assert library.add("T", "object", "x", tags=["a"]).tags == ("a",)

    def test_order_is_builtin_then_insertion(self, library):
        library.add("Zed", "object", "1")
        library.add("Alpha", "scene", "2")
        names = [p.name for p in library.presets()]
        assert names[: len(python_templates.TEMPLATES)] == list(python_templates.TEMPLATES)
        assert names[len(python_templates.TEMPLATES) :] == ["Zed", "Alpha"]

    def test_duplicate_names_get_a_suffix(self, library):
        a = library.add("Thing", "object", "1")
        b = library.add("Thing", "object", "2")
        c = library.add("THING", "object", "3")
        assert [a.name, b.name, c.name] == ["Thing", "Thing (2)", "THING (3)"]
        assert len({a.id, b.id, c.id}) == 3

    def test_a_builtin_name_is_taken_too(self, library):
        name = next(iter(python_templates.TEMPLATES))
        assert library.add(name.upper(), "object", "x").name == f"{name.upper()} (2)"

    def test_the_same_name_in_two_origins(self, library):
        a = library.add("X", "object", "1")
        b = library.add("X", "object", "2", origin="online")
        assert (a.name, b.name) == ("X", "X (2)")
        assert (a.id, b.id) == ("user:x", "online:x")

    def test_ids_stay_unique_when_names_slug_alike(self, library):
        ids = [library.add(n, "object", "x").id for n in ("A b", "a-b", "A  B")]
        assert ids == ["user:a-b", "user:a-b-2", "user:a-b-3"]

    def test_name_is_stripped(self, library):
        assert library.add("  Spaced  ", "object", "x").name == "Spaced"

    def test_a_name_with_no_letters_still_gets_an_id(self, library):
        assert library.add("???", "object", "x").id == "user:preset"

    @pytest.mark.parametrize(
        ("name", "kind", "origin"),
        [
            ("", "object", "user"),
            ("  ", "object", "user"),
            ("x", "module", "user"),
            ("x", "object", "builtin"),
        ],
    )
    def test_refuses_nonsense(self, library, name, kind, origin):
        with pytest.raises(ValueError):
            library.add(name, kind, "x", origin=origin)
        assert saved(library) == []

    def test_saves_to_the_file(self, library, path):
        library.add("Ünï", "object", "x = 'é'\r\n")
        assert path.is_file()
        again = PresetLibrary(path)
        assert [(p.name, p.code) for p in saved(again)] == [("Ünï", "x = 'é'\r\n")]
        assert path.read_text(encoding="utf-8").count("é") >= 1  # not escaped

    def test_roundtrip_keeps_everything(self, library, path):
        a = library.add("A", "object", CODE, description="d", tags=("t",))
        b = library.add("B", "scene", "x", origin="online", source_url="https://e.org/b.py")
        assert saved(PresetLibrary(path)) == [a, b]

    def test_a_failed_save_leaves_the_library_as_it_was(self, library, monkeypatch):
        library.add("Kept", "object", "x")

        def broken(src, dst):
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr(preset_library.os, "replace", broken)
        with pytest.raises(OSError):
            library.add("Lost", "object", "y")
        with pytest.raises(OSError):
            library.remove("user:kept")
        assert [p.name for p in saved(library)] == ["Kept"]
        monkeypatch.undo()
        assert [p.name for p in saved(PresetLibrary(library.path))] == ["Kept"]


class TestAtomicSave:
    def test_no_temporary_files(self, library, path):
        library.add("A", "object", "x")
        library.add("B", "object", "y")
        library.remove("user:a")
        assert sorted(os.listdir(path.parent)) == ["presets.json"]

    def test_failure_keeps_the_old_file(self, library, path, monkeypatch):
        library.add("A", "object", "x")
        before = path.read_text(encoding="utf-8")

        def broken(src, dst):
            raise OSError("disk full")

        monkeypatch.setattr(preset_library.os, "replace", broken)
        with pytest.raises(OSError):
            library.add("B", "object", "y")
        assert path.read_text(encoding="utf-8") == before
        assert sorted(os.listdir(path.parent)) == ["presets.json"]

    def test_creates_the_folder(self, tmp_path):
        library = PresetLibrary(tmp_path / "a" / "b" / "presets.json")
        library.add("A", "object", "x")
        assert (tmp_path / "a" / "b" / "presets.json").is_file()

    def test_nothing_is_written_until_something_changes(self, library, path):
        assert not path.exists()
        assert library.import_legacy({}) == 0
        assert not path.exists()


class TestRemoveRename:
    def test_remove(self, library, path):
        a = library.add("A", "object", "1")
        b = library.add("B", "object", "2")
        library.remove(a.id)
        assert saved(library) == [b]
        assert saved(PresetLibrary(path)) == [b]
        assert library.get(a.id) is None

    def test_removed_name_and_id_can_be_used_again(self, library):
        library.add("A", "object", "1")
        library.remove("user:a")
        assert library.add("A", "object", "2").id == "user:a"

    def test_unknown_id(self, library):
        with pytest.raises(KeyError):
            library.remove("user:nothing")
        with pytest.raises(KeyError):
            library.rename("user:nothing", "x")

    def test_rename(self, library, path):
        a = library.add("Old", "object", "1")
        renamed = library.rename(a.id, "New")
        assert renamed == Preset(a.id, "New", "object", "1", "user")
        assert library.get(a.id).name == "New"  # the id does not change with the name
        assert [p.name for p in saved(PresetLibrary(path))] == ["New"]

    def test_rename_keeps_the_position(self, library):
        a = library.add("A", "object", "1")
        library.add("B", "object", "2")
        library.rename(a.id, "Z")
        assert [p.name for p in saved(library)] == ["Z", "B"]

    def test_rename_to_a_taken_name(self, library):
        library.add("A", "object", "1")
        b = library.add("B", "object", "2")
        assert library.rename(b.id, "a").name == "a (2)"

    def test_rename_to_its_own_name_in_another_case(self, library):
        a = library.add("name", "object", "1")
        assert library.rename(a.id, "Name").name == "Name"

    def test_rename_to_nothing(self, library):
        a = library.add("A", "object", "1")
        with pytest.raises(ValueError):
            library.rename(a.id, "  ")
        assert library.get(a.id).name == "A"


class TestLoading:
    def test_missing_file_is_an_empty_library(self, library):
        assert saved(library) == []

    def test_default_path_from_the_environment(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MANIM_STUDIO_PRESETS", str(tmp_path / "x.json"))
        assert PresetLibrary().path == tmp_path / "x.json"
        assert preset_library.default_path() == tmp_path / "x.json"

    def test_default_path_without_the_environment(self, monkeypatch):
        monkeypatch.delenv("MANIM_STUDIO_PRESETS")
        assert preset_library.default_path().name == "presets.json"

    @pytest.mark.parametrize(
        "text",
        [
            "{not json",
            "",
            "[]",
            "null",
            '"text"',
            '{"format": 1, "presets": 3}',
            '{"format": 1}',
            '{"format": 2, "presets": []}',
            '{"presets": []}',
        ],
    )
    def test_corrupt_file_is_set_aside(self, path, text):
        path.write_text(text, encoding="utf-8")
        library = PresetLibrary(path)
        assert saved(library) == []
        assert not path.exists()
        assert (path.parent / "presets.json.bad").read_text(encoding="utf-8") == text
        library.add("New", "object", "x")  # and it works afterwards
        assert [p.name for p in saved(PresetLibrary(path))] == ["New"]

    def test_binary_file_is_set_aside(self, path):
        path.write_bytes(b"\xff\xfe\x00garbage")
        assert saved(PresetLibrary(path)) == []
        assert (path.parent / "presets.json.bad").exists()

    def test_earlier_bad_files_are_not_overwritten(self, path):
        for n, expected in enumerate(["presets.json.bad", "presets.json.bad2", "presets.json.bad3"]):
            path.write_text(f"broken {n}", encoding="utf-8")
            PresetLibrary(path)
            assert (path.parent / expected).read_text(encoding="utf-8") == f"broken {n}"

    def test_a_folder_in_place_of_the_file_does_not_raise(self, path):
        path.mkdir()
        assert saved(PresetLibrary(path)) == []

    def test_entries_with_wrong_types_are_dropped(self, path):
        good = {"name": "Good", "kind": "object", "code": "x", "origin": "user"}
        bad = [
            "text",
            None,
            {},
            {**good, "name": 3},
            {**good, "name": "  "},
            {**good, "code": None},
            {**good, "kind": "module"},
            {**good, "origin": "mars"},
            {**good, "description": 4},
            {**good, "tags": "abc"},
            {**good, "tags": [1]},
            {**good, "source_url": []},
        ]
        path.write_text(json.dumps({"format": 1, "presets": [bad[0], good, *bad[1:]]}), encoding="utf-8")
        library = PresetLibrary(path)
        assert [p.name for p in saved(library)] == ["Good"]
        assert path.exists()  # a few bad entries do not set the file aside

    def test_missing_optional_fields_get_defaults_and_ids(self, path):
        entries = [
            {"name": "A", "kind": "scene", "code": "1", "origin": "online"},
            {"name": "A", "kind": "scene", "code": "2", "origin": "online", "id": "online:a"},
            {"name": "B", "kind": "object", "code": "3", "origin": "user", "id": "online:b"},
        ]
        path.write_text(json.dumps({"format": 1, "presets": entries}), encoding="utf-8")
        a, a2, b = saved(PresetLibrary(path))
        assert (a.id, a2.id, b.id) == ("online:a", "online:a-2", "user:b")
        assert (a.description, a.tags, a.source_url) == ("", (), "")

    def test_loading_does_not_rewrite_the_file(self, path):
        text = json.dumps(
            {"format": 1, "presets": [{"name": "A", "kind": "object", "code": "x", "origin": "user"}]}
        )
        path.write_text(text, encoding="utf-8")
        PresetLibrary(path)
        assert path.read_text(encoding="utf-8") == text


class TestLegacy:
    def test_adds_as_user_objects(self, library):
        assert library.import_legacy({"One": "a", "Two": "b"}) == 2
        assert [(p.name, p.kind, p.origin, p.code) for p in saved(library)] == [
            ("One", "object", "user", "a"),
            ("Two", "object", "user", "b"),
        ]

    def test_is_saved(self, library, path):
        library.import_legacy({"One": "a"})
        assert [p.name for p in saved(PresetLibrary(path))] == ["One"]

    def test_twice_adds_nothing(self, library):
        templates = {"One": "a", "Two": "b"}
        assert library.import_legacy(templates) == 2
        assert library.import_legacy(templates) == 0
        assert len(saved(library)) == 2

    def test_same_name_other_code_is_added_once_with_a_suffix(self, library):
        library.add("One", "object", "different")
        templates = {"One": "a"}
        assert library.import_legacy(templates) == 1
        assert [p.name for p in saved(library)] == ["One", "One (2)"]
        assert library.import_legacy(templates) == 0  # not again as "One (3)"

    def test_the_same_name_and_code_as_a_builtin_is_not_added(self, library):
        name, code = next(iter(python_templates.TEMPLATES.items()))
        assert library.import_legacy({name: code}) == 0
        assert saved(library) == []

    def test_an_identical_user_preset_is_not_added(self, library):
        library.add("One", "scene", "a")
        assert library.import_legacy({"One": "a"}) == 0

    def test_junk_is_skipped(self, library):
        assert library.import_legacy({"": "a", "  ": "b", "Ok": "c", "Bad": 3}) == 1  # type: ignore[dict-item]
        assert [p.name for p in saved(library)] == ["Ok"]

    def test_empty(self, library):
        assert library.import_legacy({}) == 0


class TestSetTags:
    def test_sets_and_saves(self, library, path):
        library.add("A", "object", "x")
        updated = library.set_tags("user:a", ["geometry", "triangle"])
        assert updated.tags == ("geometry", "triangle")
        assert library.get("user:a") == updated
        assert PresetLibrary(path).get("user:a").tags == ("geometry", "triangle")

    def test_replaces_the_old_tags(self, library):
        library.add("A", "object", "x", tags=("old",))
        assert library.set_tags("user:a", ("new",)).tags == ("new",)
        assert library.set_tags("user:a", ()).tags == ()

    def test_normalises(self, library):
        library.add("A", "object", "x")
        raw = ["  Algebra ", "ALGEBRA", "a,b", "", " ", "two   words", "x,,y"]
        assert library.set_tags("user:a", raw).tags == ("algebra", "a", "b", "two words", "x", "y")

    def test_at_most_twelve_tags_of_twenty_four_characters(self, library):
        library.add("A", "object", "x")
        tags = library.set_tags("user:a", [f"tag{i}" for i in range(20)]).tags
        assert tags == tuple(f"tag{i}" for i in range(12))
        assert library.set_tags("user:a", ["x" * 40]).tags == ("x" * 24,)

    def test_a_cut_tag_that_repeats_is_dropped(self, library):
        library.add("A", "object", "x")
        assert library.set_tags("user:a", ["a" * 30, "a" * 25]).tags == ("a" * 24,)

    def test_builtin_refuses(self, library):
        builtin = library.presets()[0]
        with pytest.raises(ValueError, match="built-in"):
            library.set_tags(builtin.id, ["x"])
        assert library.get(builtin.id).tags == ()

    def test_unknown_id(self, library):
        with pytest.raises(KeyError):
            library.set_tags("user:nothing", ["x"])

    def test_the_file_format_is_unchanged(self, library, path):
        library.add("A", "object", "x")
        library.set_tags("user:a", ["t"])
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["format"] == 1
        assert set(data["presets"][0]) == {
            "id", "name", "kind", "code", "origin", "description", "tags", "source_url",
        }  # fmt: skip
        assert data["presets"][0]["tags"] == ["t"]

    def test_failure_keeps_the_old_tags(self, library, path, monkeypatch):
        library.add("A", "object", "x", tags=("keep",))
        before = path.read_text(encoding="utf-8")

        def broken(src, dst):
            raise OSError("disk full")

        monkeypatch.setattr(preset_library.os, "replace", broken)
        with pytest.raises(OSError):
            library.set_tags("user:a", ["lost"])
        assert library.get("user:a").tags == ("keep",)
        assert path.read_text(encoding="utf-8") == before

    def test_other_fields_stay(self, library):
        before = library.add("A", "scene", "code", description="d", source_url="u", origin="online")
        after = library.set_tags(before.id, ["t"])
        assert after == Preset(
            before.id, before.name, before.kind, before.code, before.origin, "d", ("t",), "u"
        )

    def test_normalise_tags_directly(self):
        assert preset_library.normalise_tags(("B", "a", "b")) == ("b", "a")
        assert preset_library.normalise_tags([]) == ()


class TestTags:
    def test_counts_most_used_first_then_by_name(self, library):
        library.add("A", "object", "1", tags=("zeta", "alpha"))
        library.add("B", "object", "2", tags=("alpha", "beta"))
        library.add("C", "scene", "3", tags=("beta", "alpha", "gamma"))
        assert library.tags() == [("alpha", 3), ("beta", 2), ("gamma", 1), ("zeta", 1)]

    def test_empty(self, library):
        assert library.tags() == []

    def test_a_tag_repeated_on_one_preset_counts_once(self, library):
        library.add("A", "object", "1", tags=("x", "x"))
        assert library.tags() == [("x", 1)]

    def test_follows_set_tags_and_remove(self, library):
        a = library.add("A", "object", "1")
        library.set_tags(a.id, ["one"])
        assert library.tags() == [("one", 1)]
        library.remove(a.id)
        assert library.tags() == []


class TestSearch:
    @pytest.fixture
    def stocked(self, library):
        library.add("Pythagoras proof", "scene", "1", description="Squares on the sides", tags=("geometry",))
        library.add("Matrix grid", "object", "2", description="A grid of numbers", tags=("algebra", "grid"))
        library.add(
            "Web triangle", "object", "3", origin="online", description="Seen on the web", tags=("geometry",)
        )
        return library

    @staticmethod
    def names(found):
        return [p.name for p in found]

    def test_empty_query_gives_everything_in_order(self, stocked):
        assert stocked.search("") == stocked.presets()
        assert stocked.search("   ") == stocked.presets()

    def test_by_name_case_insensitively(self, stocked):
        assert self.names(stocked.search("PYTHAGORAS")) == ["Pythagoras proof"]

    def test_by_description(self, stocked):
        assert self.names(stocked.search("squares")) == ["Pythagoras proof"]

    def test_by_tag(self, stocked):
        assert self.names(stocked.search("algebra")) == ["Matrix grid"]
        assert set(self.names(stocked.search("geometry"))) == {"Pythagoras proof", "Web triangle"}

    def test_all_words_must_match(self, stocked):
        assert self.names(stocked.search("geometry triangle")) == ["Web triangle"]
        assert stocked.search("geometry matrix") == []

    def test_origin_words(self, stocked):
        assert set(self.names(stocked.search("mine"))) == {"Pythagoras proof", "Matrix grid"}
        assert self.names(stocked.search("downloaded")) == ["Web triangle"]
        builtin = stocked.search("builtin")
        assert builtin and all(p.builtin for p in builtin)
        assert len(builtin) == len(python_templates.TEMPLATES)

    def test_origin_word_with_another_word(self, stocked):
        assert self.names(stocked.search("mine grid")) == ["Matrix grid"]

    def test_kind_words(self, stocked):
        assert self.names(stocked.search("mine scene")) == ["Pythagoras proof"]

    def test_name_matches_come_before_description_matches(self, library):
        library.add("Plain", "object", "1", description="mentions grid")
        library.add("Grid maker", "object", "2")
        assert [p.name for p in library.search("grid")][:2] == ["Grid maker", "Plain"]

    def test_ties_keep_the_library_order(self, library):
        library.add("Alpha one", "object", "1")
        library.add("Alpha two", "object", "2")
        assert [p.name for p in library.search("alpha")] == ["Alpha one", "Alpha two"]

    def test_builtins_are_found_by_name(self, library):
        first = library.presets()[0]
        assert library.search(first.name.lower())[0] == first

    def test_uppercase_tags_still_match(self, library):
        library.add("A", "object", "x", tags=("Geometry",))
        assert [p.name for p in library.search("geometry")] == ["A"]

    def test_no_match(self, stocked):
        assert stocked.search("nothing-like-this") == []
