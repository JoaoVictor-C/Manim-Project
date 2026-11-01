"""Portable project bundles (ADR 0077): what a project refers to, writing a bundle, opening one safely."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from manim_studio.core.code.trust import TrustStore
from manim_studio.core.exchange import bundle
from manim_studio.core.model import snapshots
from manim_studio.core.model.schema import AudioClip, Layer, Project, Spec

SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><rect width="10" height="10"/></svg>'
SOUND = bytes(range(256)) * 40
CODE = "class Scene1(Scene):\n    def construct(self):\n        self.add(Square())\n"


def media_project(folder: Path) -> Project:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "logo.svg").write_bytes(SVG)
    (folder / "voice.wav").write_bytes(SOUND)
    return Project(
        layers=[
            Layer(
                id="logo",
                name="Logo",
                spec=Spec(type="SVGMobject", params={"path": str(folder / "logo.svg")}),
            ),
            Layer(id="copy", spec=Spec(type="SVGMobject", params={"path": str(folder / "logo.svg")})),
            Layer(id="sq", spec=Spec(type="Square")),
        ],
        audio=[AudioClip(id="audio-1", name="voice", path=str(folder / "voice.wav"), duration=1.0)],
    )


def paths_cleared(project: Project) -> dict:
    data = project.model_dump(by_alias=True)
    for layer in data["layers"]:
        if layer["spec"] and "path" in layer["spec"]["params"]:
            layer["spec"]["params"]["path"] = "*"
    for clip in data.get("audio", []):
        clip["path"] = "*"
    return data


def test_the_references_are_the_media_layers_and_the_sounds(tmp_path) -> None:
    refs = bundle.external_references(media_project(tmp_path))
    assert [(r.kind, r.owner, r.label) for r in refs] == [
        ("SVGMobject", "logo", "Logo"),
        ("SVGMobject", "copy", "copy"),
        ("audio", "audio-1", "voice"),
    ]


def test_a_round_trip_keeps_the_project_and_the_files(tmp_path) -> None:
    project = media_project(tmp_path / "made")
    target = tmp_path / "out" / f"scene{bundle.EXTENSION}"
    report = bundle.build_bundle(project, target, name="scene", app_version="9.9")
    assert report.missing == [] and len(report.files) == 2  # the SVG once for both layers
    with zipfile.ZipFile(target) as zf:
        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["format"] == bundle.FORMAT and manifest["app_version"] == "9.9"
        svg = next(f for f in manifest["files"] if f["path"].endswith(".svg"))
        assert svg["sha256"] == hashlib.sha256(SVG).hexdigest()
        assert [u["id"] for u in svg["used_by"]] == ["logo", "copy"]
        inside = Project.model_validate_json(zf.read("project.json"))
        assert {r.path for r in bundle.external_references(inside)} == {f["path"] for f in manifest["files"]}

    opened = bundle.open_bundle(target, tmp_path / "elsewhere")
    assert opened.folder == tmp_path / "elsewhere" / "scene" and opened.missing == []
    assert paths_cleared(opened.project) == paths_cleared(project)
    assert Project.model_validate_json(opened.project_path.read_text(encoding="utf-8")) == opened.project
    for ref in bundle.external_references(opened.project):
        assert Path(ref.path).is_relative_to(opened.folder)
        assert Path(ref.path).read_bytes() == (SOUND if ref.kind == "audio" else SVG)


def test_opening_twice_never_overwrites_it_picks_a_new_folder(tmp_path) -> None:
    target = tmp_path / "scene.msbundle"
    bundle.build_bundle(media_project(tmp_path / "made"), target, name="scene")
    first = bundle.open_bundle(target)
    (first.folder / "mine.txt").write_text("keep")
    second = bundle.open_bundle(target)
    assert second.folder == tmp_path / "scene (2)"
    assert (first.folder / "mine.txt").read_text() == "keep"


def test_a_missing_file_is_marked_and_the_bundle_still_builds(tmp_path) -> None:
    project = media_project(tmp_path / "made")
    (tmp_path / "made" / "voice.wav").unlink()
    target = tmp_path / "scene.msbundle"
    report = bundle.build_bundle(project, target)
    assert [r.owner for r in report.missing] == ["audio-1"]
    with zipfile.ZipFile(target) as zf:
        entry = next(f for f in json.loads(zf.read("manifest.json"))["files"] if f["missing"])
    assert entry["path"] is None and entry["original"].endswith("voice.wav")
    opened = bundle.open_bundle(target, tmp_path / "open")
    assert opened.missing == [str(tmp_path / "made" / "voice.wav")]
    assert opened.project.audio[0].path == str(tmp_path / "made" / "voice.wav")  # kept: a placeholder


def test_snapshots_travel_when_asked(tmp_path) -> None:
    project = media_project(tmp_path / "made")
    path = tmp_path / "made" / "scene.json"
    path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
    snapshots.save(path, project, "rough cut")
    target = tmp_path / "scene.msbundle"
    assert bundle.build_bundle(project, target, project_path=path).snapshots == 0
    report = bundle.build_bundle(project, target, project_path=path, include_snapshots=True)
    assert report.snapshots == 1
    opened = bundle.open_bundle(target, tmp_path / "open")
    [kept] = snapshots.listing(opened.project_path)
    assert kept.name == "rough cut"
    assert snapshots.load(kept) == opened.project  # its paths point at the unpacked files too


def rewrite(source: Path, target: Path, change) -> None:
    """Copy a bundle, letting ``change(name, data)`` return new data (or None to drop the entry)."""
    with zipfile.ZipFile(source) as read, zipfile.ZipFile(target, "w") as write:
        for info in read.infolist():
            data = change(info.filename, read.read(info))
            if data is not None:
                write.writestr(info.filename, data)


@pytest.mark.parametrize("evil", ["../evil.txt", "/abs.txt", "C:/abs.txt", "assets/../../x", "a\\..\\b"])
def test_zip_slip_is_refused_and_nothing_is_unpacked(tmp_path, evil) -> None:
    good = tmp_path / "good.msbundle"
    bundle.build_bundle(media_project(tmp_path / "made"), good, name="scene")
    bad = tmp_path / "bad.msbundle"
    rewrite(good, bad, lambda name, data: data)
    with zipfile.ZipFile(bad, "a") as zf:
        zf.writestr(evil, b"boom")
    with pytest.raises(bundle.BundleError, match="unsafe"):
        bundle.open_bundle(bad, tmp_path / "open")
    assert not (tmp_path / "open").exists() and not (tmp_path / "evil.txt").exists()


def test_a_manifest_cannot_point_outside_the_assets(tmp_path) -> None:
    good = tmp_path / "good.msbundle"
    bundle.build_bundle(media_project(tmp_path / "made"), good, name="scene")

    def lie(name, data):
        if name != "manifest.json":
            return data
        manifest = json.loads(data)
        manifest["files"][0]["path"] = "../outside.svg"
        return json.dumps(manifest)

    rewrite(good, tmp_path / "bad.msbundle", lie)
    with pytest.raises(bundle.BundleError, match="outside its assets"):
        bundle.open_bundle(tmp_path / "bad.msbundle", tmp_path / "open")


def test_a_tampered_file_is_refused_and_its_folder_removed(tmp_path) -> None:
    good = tmp_path / "good.msbundle"
    bundle.build_bundle(media_project(tmp_path / "made"), good, name="scene")
    bad = tmp_path / "bad.msbundle"
    rewrite(good, bad, lambda name, data: data.replace(b"rect", b"RECT") if name.endswith(".svg") else data)
    with pytest.raises(bundle.BundleError, match="sha256"):
        bundle.open_bundle(bad, tmp_path / "open")
    assert list((tmp_path / "open").iterdir()) == []


def test_a_tampered_project_is_refused(tmp_path) -> None:
    good = tmp_path / "good.msbundle"
    bundle.build_bundle(media_project(tmp_path / "made"), good, name="scene")
    bad = tmp_path / "bad.msbundle"
    rewrite(good, bad, lambda name, data: data.replace(b'"sq"', b'"sx"') if name == "project.json" else data)
    with pytest.raises(bundle.BundleError, match="sha256"):
        bundle.open_bundle(bad, tmp_path / "open")


def test_unlisted_files_and_oversized_bundles_are_refused(tmp_path) -> None:
    good = tmp_path / "good.msbundle"
    bundle.build_bundle(media_project(tmp_path / "made"), good, name="scene")
    bad = tmp_path / "bad.msbundle"
    rewrite(good, bad, lambda name, data: data)
    with zipfile.ZipFile(bad, "a") as zf:
        zf.writestr("trusted-code.json", json.dumps({"trusted": ["x"]}))
    with pytest.raises(bundle.BundleError, match="does not list"):
        bundle.open_bundle(bad, tmp_path / "open")
    with pytest.raises(bundle.BundleError, match="more than"):
        bundle.open_bundle(good, tmp_path / "open", max_bytes=100)


def test_a_newer_format_or_a_plain_zip_is_refused(tmp_path) -> None:
    plain = tmp_path / "plain.zip"
    with zipfile.ZipFile(plain, "w") as zf:
        zf.writestr("hello.txt", "hi")
    with pytest.raises(bundle.BundleError, match="not a Manim Studio bundle"):
        bundle.open_bundle(plain, tmp_path / "open")
    good = tmp_path / "good.msbundle"
    bundle.build_bundle(Project(), good)

    def newer(name, data):
        return json.dumps({**json.loads(data), "version": 99}) if name == "manifest.json" else data

    rewrite(good, tmp_path / "new.msbundle", newer)
    with pytest.raises(bundle.BundleError, match="newer"):
        bundle.open_bundle(tmp_path / "new.msbundle", tmp_path / "open")


def test_trust_does_not_travel_with_a_bundle(tmp_path) -> None:
    project = Project(layers=[Layer(id="code", spec=Spec(type="Code", params={"code": CODE}))])
    here = TrustStore(tmp_path / "here.json")
    here.trust([CODE])
    assert here.untrusted(project) == []
    target = tmp_path / "scene.msbundle"
    bundle.build_bundle(project, target, name="scene")
    with zipfile.ZipFile(target) as zf:
        assert sorted(zf.namelist()) == ["manifest.json", "project.json"]
        assert "trust" not in zf.read("manifest.json").decode()
    there = TrustStore(tmp_path / "there.json")  # another computer
    opened = bundle.open_bundle(target, tmp_path / "open")
    assert there.untrusted(opened.project) == ["code"]
    assert not (tmp_path / "there.json").exists()  # opening wrote no trust


def test_a_manifest_claiming_trust_changes_nothing(tmp_path) -> None:
    project = Project(layers=[Layer(id="code", spec=Spec(type="Code", params={"code": CODE}))])
    good = tmp_path / "good.msbundle"
    bundle.build_bundle(project, good, name="scene")

    def claim(name, data):
        if name != "manifest.json":
            return data
        return json.dumps({**json.loads(data), "trusted": [hashlib.sha256(CODE.encode()).hexdigest()]})

    rewrite(good, tmp_path / "claim.msbundle", claim)
    opened = bundle.open_bundle(tmp_path / "claim.msbundle", tmp_path / "open")
    assert TrustStore(tmp_path / "there.json").untrusted(opened.project) == ["code"]
