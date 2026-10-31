"""Named project snapshots (ADR 0068): kept beside the file, compared in the editor's words."""

from __future__ import annotations

import pytest

from manim_studio.core.editing import edits
from manim_studio.core.model import snapshots
from manim_studio.core.model.schema import Canvas, Clip, Layer, Marker, Project, Spec, Transform2D

CANVAS = Canvas(width_px=320, height_px=180, fps=10, duration=4.0)


def square(layer_id: str = "sq", **fields) -> Layer:
    return Layer(id=layer_id, name=fields.pop("name", ""), spec=Spec(type="Square"), **fields)


def project(*layers: Layer, **fields) -> Project:
    return Project(canvas=fields.pop("canvas", CANVAS), layers=list(layers), **fields)


def test_snapshots_live_beside_the_file_and_are_listed_newest_first(tmp_path) -> None:
    path = tmp_path / "scene.json"
    assert snapshots.folder_for(path) == tmp_path / "scene.snapshots"
    first = snapshots.save(path, project(square()), "rough cut", now=1000.0)
    second = snapshots.save(path, project(square(), square("b")), "  final   narration ", now=2000.0)
    names = [(s.name, s.layers) for s in snapshots.listing(path)]
    assert names == [("final narration", 2), ("rough cut", 1)]
    assert first.id != second.id
    assert snapshots.load(second).layers[1].id == "b"


def test_equal_names_are_allowed_and_empty_names_are_not(tmp_path) -> None:
    path = tmp_path / "scene.json"
    snapshots.save(path, project(), "same", now=1.0)
    snapshots.save(path, project(), "same", now=2.0)
    assert len(snapshots.listing(path)) == 2
    with pytest.raises(snapshots.SnapshotError):
        snapshots.save(path, project(), "   ")


def test_a_snapshot_missing_a_file_or_unreadable_is_not_listed(tmp_path) -> None:
    path = tmp_path / "scene.json"
    kept = snapshots.save(path, project(square()), "kept", now=1.0)
    lost = snapshots.save(path, project(), "lost", now=2.0)
    broken = snapshots.save(path, project(), "broken", now=3.0)
    lost.path.unlink()  # its project is gone: the sidecar alone is nothing
    broken.path.with_name(f"{broken.id}{snapshots.META}").write_text("{not json")
    assert [s.name for s in snapshots.listing(path)] == ["kept"]
    assert snapshots.listing(tmp_path / "nothing.json") == []
    assert not [p for p in snapshots.folder_for(path).iterdir() if p.name.endswith(".tmp")]
    assert kept.path.is_file()


def test_rename_and_delete(tmp_path) -> None:
    path = tmp_path / "scene.json"
    snapshot = snapshots.save(path, project(square()), "draft", now=1.0)
    renamed = snapshots.rename(snapshot, "first draft")
    assert [s.name for s in snapshots.listing(path)] == ["first draft"] and renamed.id == snapshot.id
    snapshots.delete(renamed)
    assert snapshots.listing(path) == [] and not renamed.path.exists()


def test_a_snapshot_that_no_longer_reads_says_so(tmp_path) -> None:
    snapshot = snapshots.save(tmp_path / "scene.json", project(), "x", now=1.0)
    snapshot.path.write_text("not a project")
    with pytest.raises(snapshots.SnapshotError, match="cannot read the snapshot 'x'"):
        snapshots.load(snapshot)


def test_compare_names_what_changed_in_the_editors_words() -> None:
    old = project(square("a", name="Title"), square("b"), square("c"), square("d"))
    moved = square("a", name="Title", base=Transform2D(position=(1.0, 0.0)))
    retimed = square("b", clips=[Clip(id="k", kind="FadeIn", start=0.0, duration=1.0)])
    restyled = Layer(id="c", spec=Spec(type="Circle"))
    new = project(
        moved,
        retimed,
        restyled,
        square("e", name="Extra"),
        canvas=CANVAS.model_copy(update={"duration": 6.0}),
        markers=[Marker(id="m", t=1.0, name="beat")],
    )
    diff = snapshots.compare(old, new)
    assert diff.added == ["Extra (Square)"] and diff.removed == ["d (Square)"]
    assert diff.changed == {
        "Title (Square)": ["position and keys"],
        "b (Square)": ["timing"],
        "c (Circle)": ["what it is"],
    }
    assert diff.scene == ["canvas changed (duration 4.0 -> 6.0)", "markers: 0 -> 1"]
    assert not diff.empty and "~ b (Square): timing" in diff.lines()


def test_identical_projects_have_no_differences() -> None:
    same = project(square())
    diff = snapshots.compare(same, same.model_copy(deep=True))
    assert diff.empty and diff.lines() == ["No differences."]


def test_restoring_is_one_edit_that_replaces_the_project_and_undo_returns_it() -> None:
    now = project(square("a"), square("b"))
    then = project(square("a", base=Transform2D(position=(2.0, 0.0))))
    edit = edits.restore_project(now, then)
    assert edit.project == then
    assert edit.layer_ids >= {
        "a",
        "b",
    }  # the layer that changed and the one that went: both lose their caches
