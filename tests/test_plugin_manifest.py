"""Plugin manifests, compatibility and permission approvals (ADR 0078): the pure rules."""

from __future__ import annotations

import json

import pytest

from manim_studio import plugin_manifest as pm
from manim_studio.plugin_manifest import Manifest, ManifestError

VALID = {
    "name": "Pendulum",
    "version": "1.2.0",
    "author": "Ada",
    "description": "A swinging pendulum.",
    "requires": ">=0.3, <0.5",
    "permissions": ["files", "reads_project", "files"],
    "homepage": "ignored",
}


def test_a_valid_manifest_is_read_with_sorted_unique_permissions() -> None:
    manifest = pm.parse_manifest(VALID)
    assert manifest == Manifest(
        "Pendulum", "1.2.0", "Ada", "A swinging pendulum.", ">=0.3, <0.5", ("files", "reads_project")
    )


def test_only_name_and_version_are_required() -> None:
    assert pm.parse_manifest({"name": "X", "version": "1"}) == Manifest("X", "1")


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"name": None}, "'name' is missing"),
        ({"version": None}, "'version' is missing"),
        ({"name": "  "}, "'name' is missing"),
        ({"author": 3}, "'author' must be text"),
        ({"version": "one"}, "'version'"),
        ({"permissions": ["files", "telepathy"]}, "unknown permission telepathy"),
        ({"permissions": "files"}, "must be a list"),
        ({"requires": ">=0.3,"}, "empty clause"),
        ({"requires": "at least 0.3"}, "not a version clause"),
        ({"requires": ">=0.3.*"}, "only goes with"),
        ({"requires": "~=1"}, "two numbers"),
    ],
)
def test_an_unusable_manifest_says_why(change: dict, message: str) -> None:
    data = {k: v for k, v in {**VALID, **change}.items() if v is not None}
    with pytest.raises(ManifestError, match=message):
        pm.parse_manifest(data)


def test_a_manifest_must_be_an_object() -> None:
    with pytest.raises(ManifestError, match="JSON object"):
        pm.parse_manifest(["name"])


def test_reading_a_manifest_file(tmp_path) -> None:
    plugin = tmp_path / "pendulum.py"
    path = pm.manifest_path_for_file(plugin)
    assert path == tmp_path / "pendulum.plugin.json"
    assert pm.read_manifest(path) is None  # no manifest: a legacy plugin
    path.write_text(json.dumps(VALID), encoding="utf-8")
    assert pm.read_manifest(path).name == "Pendulum"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ManifestError, match="not valid JSON"):
        pm.read_manifest(path)


def test_versions_compare_by_their_numbers() -> None:
    assert pm.parse_version("0.3.0rc1") == (0, 3, 0)
    assert pm.parse_version("v1.2") == (1, 2)
    with pytest.raises(ValueError):
        pm.parse_version("unknown")
    assert pm.satisfies("0.3.0", ">=0.3")  # 0.3 == 0.3.0
    assert pm.satisfies("0.3.0", "")
    assert not pm.satisfies("0.3.0", ">0.3")
    assert pm.satisfies("0.10.0", ">0.9")  # numbers, not text
    assert pm.satisfies("0.4.2", ">=0.3, <0.5") and not pm.satisfies("0.5.0", ">=0.3, <0.5")
    assert pm.satisfies("0.3.7", "==0.3.*") and not pm.satisfies("0.4.0", "==0.3.*")
    assert pm.satisfies("0.4.0", "!=0.3.*")
    assert pm.satisfies("0.3.9", "~=0.3.1") and not pm.satisfies("0.4.0", "~=0.3.1")
    assert not pm.satisfies("0.3.0", "~=0.3.1")
    assert pm.satisfies("0.3.0", "0.3")  # a bare version means ==


def test_compatibility_says_what_the_plugin_needs() -> None:
    manifest = Manifest("P", "1", requires=">=0.4")
    assert pm.incompatibility(manifest, "0.3.0") == "incompatible: needs >=0.4 (this is Manim Studio 0.3.0)"
    assert pm.incompatibility(manifest, "0.4.1") is None
    assert pm.incompatibility(Manifest("P", "1"), "0.1") is None  # no range: any version
    assert pm.incompatibility(manifest, "unknown") is None  # an app of unknown version runs it


def test_the_permission_hash_ignores_order_and_repeats() -> None:
    assert pm.permission_hash(["files", "ui"]) == pm.permission_hash(["ui", "files", "ui"])
    assert pm.permission_hash(["files"]) != pm.permission_hash(["files", "network"])


def test_approval_covers_the_same_or_fewer_permissions_and_asks_again_when_they_grow() -> None:
    first = Manifest("P", "1.0", permissions=("files",))
    assert not pm.is_approved(None, first)  # never approved: even no permissions needs a first yes
    assert not pm.is_approved(None, Manifest("P", "1.0"))
    assert pm.new_permissions(None, first) == ("files",)
    record = pm.approval_record(first)
    assert record == {
        "name": "P",
        "version": "1.0",
        "permissions": ["files"],
        "hash": pm.permission_hash(["files"]),
    }
    assert pm.is_approved(record, first)
    assert pm.is_approved(
        record, Manifest("P", "1.1", permissions=("files",))
    )  # an update asking nothing more
    assert pm.is_approved(record, Manifest("P", "1.1"))  # fewer
    grown = Manifest("P", "1.2", permissions=("files", "network"))
    assert not pm.is_approved(record, grown)
    assert pm.new_permissions(record, grown) == ("network",)


def test_a_tampered_record_approves_nothing() -> None:
    record = pm.approval_record(Manifest("P", "1", permissions=("files",)))
    record["permissions"] = ["files", "network"]  # the hash no longer fits
    assert not pm.is_approved(record, Manifest("P", "1", permissions=("files",)))
    assert not pm.is_approved({"permissions": "files"}, Manifest("P", "1"))


def test_approvals_are_stored_and_read_back(tmp_path) -> None:
    path = tmp_path / "deep" / "approvals.json"
    assert pm.load_approvals(path) == {}
    approvals = {"a.py": pm.approval_record(Manifest("A", "1", permissions=("ui",)))}
    pm.save_approvals(approvals, path)
    assert pm.load_approvals(path) == approvals
    path.write_text("[1, 2]", encoding="utf-8")
    assert pm.load_approvals(path) == {}  # an unreadable store approves nothing


def test_the_store_follows_the_environment(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("MANIM_STUDIO_PLUGIN_APPROVALS", str(tmp_path / "x.json"))
    assert pm.default_approvals_path() == tmp_path / "x.json"
    monkeypatch.delenv("MANIM_STUDIO_PLUGIN_APPROVALS")
    assert pm.default_approvals_path().name == "plugin-approvals.json"
