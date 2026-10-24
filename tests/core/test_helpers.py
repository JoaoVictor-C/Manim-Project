"""Helpers (P13.2, ADR 0058): project modules that code layers, Python objects and other helpers import.

The pure part: names, what code imports, the digest, the import finder (trust enforced where the
import happens), where an error was raised, renaming imports; the schema and the edits.
"""

from __future__ import annotations

import json
import sys

import pytest
from pydantic import ValidationError

from manim_studio.core import edits, helpers
from manim_studio.core.edits import EditError
from manim_studio.core.helpers import check_name, imports_of, install, needed, rename_imports
from manim_studio.core.schema import Helper, Layer, Project, Spec

GRID = "SPACING = 0.5\n\ndef count(width):\n    return int(width / SPACING)\n"


def python_layer(layer_id: str, code: str) -> Layer:
    return Layer(id=layer_id, spec=Spec(type="Python", params={"code": code}))


def code_layer(layer_id: str, code: str) -> Layer:
    return Layer(id=layer_id, spec=Spec(type="Code", params={"code": code}))


def with_helpers(*pairs: tuple[str, str], layers: list[Layer] | None = None) -> Project:
    return Project(layers=layers or [], helpers=[Helper(name=n, code=c) for n, c in pairs])


# -- names ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "reason"),
    [
        ("grid_tools", None),
        ("_private", None),
        ("Palette2", None),
        ("", "needs a name"),
        ("2d", "not a Python name"),
        ("grid-tools", "not a Python name"),
        ("café", "not a Python name"),
        ("class", "keyword"),
        ("match", "keyword"),  # a soft keyword: `import match` reads badly and confuses tools
        ("os", "standard library"),
        ("json", "standard library"),
        ("sys", "standard library"),
        ("manim", "the editor uses"),
        ("numpy", "the editor uses"),
        ("np", "the editor uses"),
        ("math", "the editor uses"),
        ("m", "the editor uses"),
        ("manim_studio", "the editor uses"),
        ("helpers", "the editor uses"),
        ("studio_python_object", "the editor uses"),
    ],
)
def test_check_name(name: str, reason: str | None) -> None:
    problem = check_name(name)
    assert (problem is None) if reason is None else (reason in problem), problem


def test_a_name_is_unique_and_may_be_refused_when_an_installed_module_has_it() -> None:
    assert "already exists" in check_name("grid", ["grid", "other"])
    assert check_name("pydantic") is None  # the file format does not ask what is installed here
    assert "installed on this computer" in check_name("pydantic", installed=True)
    assert check_name("surely_no_module_has_this_name", installed=True) is None


# -- what code imports ---------------------------------------------------------------------------------------


def test_imports_of_reads_every_import_without_running_it() -> None:
    source = (
        "raise SystemExit('never run')\n"
        "import os, grid.sub as g\n"
        "from palette import RED\n"
        "from . import sibling\n"
        "def f():\n    import inner\n"
    )
    assert imports_of(source) == {"os", "grid", "palette", "inner"}
    assert imports_of("def broken(:\n") == set()
    assert imports_of("x = 1\0") == set()


def test_needed_is_transitive_in_dependency_order_and_safe_with_cycles() -> None:
    project = with_helpers(
        ("a", "import b\nimport c\n"),
        ("b", "import c\n"),
        ("c", "X = 1\n"),
        ("loop1", "import loop2\n"),
        ("loop2", "import loop1\n"),
        ("unused", "import a\n"),
    )
    assert needed(project, "import a\nimport os\n") == ["c", "b", "a"]
    assert needed(project, "from b import X") == ["c", "b"]
    assert needed(project, "import loop1") == ["loop2", "loop1"]
    assert needed(project, "import os") == []
    assert needed(project, "import (") == []
    assert needed({"x": "import y", "y": ""}, "import x") == ["y", "x"]  # a mapping works too


def test_importers_name_layers_then_helpers() -> None:
    project = with_helpers(
        ("grid", GRID),
        ("plot", "import grid\n"),
        layers=[python_layer("tri", "import grid\ndef build(p):\n    return 1\n"), code_layer("c", "x = 1")],
    )
    assert helpers.importers(project, "grid") == ["tri", "helper:plot"]
    assert helpers.importers(project, "plot") == []


def test_the_digest_is_empty_without_helpers_and_follows_names_and_code_only() -> None:
    assert helpers.digest(Project()) == ""
    one = with_helpers(("grid", GRID))
    assert helpers.digest(one) == helpers.digest({"grid": GRID})
    assert helpers.digest(one) == helpers.digest({"grid": GRID.replace("\n", "\r\n")})  # line endings
    described = Project(helpers=[Helper(name="grid", code=GRID, description="spacing")])
    assert helpers.digest(described) == helpers.digest(one)
    assert helpers.digest(with_helpers(("grid", GRID + "#"))) != helpers.digest(one)
    assert helpers.digest(with_helpers(("grids", GRID))) != helpers.digest(one)
    order = with_helpers(("a", "1"), ("b", "2"))
    assert helpers.digest(order) == helpers.digest(with_helpers(("b", "2"), ("a", "1")))


# -- the import finder ---------------------------------------------------------------------------------------


def test_install_serves_helpers_as_modules_and_removes_them_afterwards() -> None:
    before = list(sys.meta_path)
    with install({"grid_t": GRID}):
        assert isinstance(sys.meta_path[0], importlib_finder())
        import grid_t

        assert grid_t.count(4) == 8
        assert grid_t.__name__ == "grid_t" and grid_t.__package__ == ""
        assert grid_t.__file__ == "<helper grid_t>" == helpers.filename("grid_t")
        assert "grid_t" in sys.modules
    assert "grid_t" not in sys.modules
    assert sys.meta_path == before
    with pytest.raises(ModuleNotFoundError):
        import grid_t


def importlib_finder() -> type:
    return helpers._HelperFinder


def test_an_edit_is_picked_up_and_a_stale_module_is_dropped() -> None:
    namespace: dict = {}
    with install({"palette_t": "RED = 1\n"}):
        exec("import palette_t\nvalue = palette_t.RED", namespace)
    assert namespace["value"] == 1
    with install({"palette_t": "RED = 2\n"}):
        exec("import palette_t\nvalue = palette_t.RED", namespace)
    assert namespace["value"] == 2
    stale = type(sys)("palette_t")  # left behind by a run that never cleaned up
    stale.__file__ = "<helper palette_t>"
    sys.modules["palette_t"] = stale
    try:
        with install({"palette_t": "RED = 3\n"}):
            exec("import palette_t\nvalue = palette_t.RED", namespace)
        assert namespace["value"] == 3
    finally:
        sys.modules.pop("palette_t", None)


def test_a_helper_imports_another_and_from_imports_work() -> None:
    sources = {"base_t": "UNIT = 3\n", "derived_t": "from base_t import UNIT\nDOUBLE = 2 * UNIT\n"}
    namespace: dict = {}
    with install(sources):
        exec("from derived_t import DOUBLE\nimport base_t", namespace)
        assert sys.modules["derived_t"].__file__ == "<helper derived_t>"
    assert namespace["DOUBLE"] == 6
    assert "base_t" not in sys.modules and "derived_t" not in sys.modules


def test_an_untrusted_helper_is_refused_at_its_import() -> None:
    sources = {"ok_t": "import bad_t\n", "bad_t": "X = 1\n"}
    with install(sources, trusted=lambda name: name == "ok_t"), pytest.raises(ImportError) as caught:
        exec("import ok_t", {})
    assert str(caught.value) == "helper 'bad_t' is not trusted yet: select it on the Code page and press Run"
    assert caught.value.name == "bad_t"
    assert "ok_t" not in sys.modules and "bad_t" not in sys.modules


def test_install_without_helpers_changes_nothing() -> None:
    before = list(sys.meta_path)
    with install({}):
        assert sys.meta_path == before


def test_the_finder_serves_only_top_level_helpers() -> None:
    with install({"top_t": "X = 1\n"}), pytest.raises(ModuleNotFoundError):
        exec("import top_t.sub", {})


def test_a_name_check_keeps_helpers_from_hiding_real_modules() -> None:
    """The finder is first on sys.meta_path: names of modules are refused before they get there."""
    assert check_name("json") is not None and check_name("numpy") is not None


# -- where errors come from ----------------------------------------------------------------------------------


def test_helper_for_filename() -> None:
    assert helpers.helper_for_filename("<helper grid>") == "grid"
    assert helpers.helper_for_filename("<python object>") is None
    assert helpers.helper_for_filename("<helper not a name>") is None
    assert helpers.helper_for_filename("C:/x.py") is None


def run_failing(code: str, sources: dict[str, str]) -> BaseException:
    try:
        with install(sources):
            exec(compile(code, "<user>", "exec"), {})
    except BaseException as error:
        return error
    raise AssertionError("did not fail")


def test_an_error_in_a_helper_names_the_helper_and_its_line() -> None:
    error = run_failing("x = 1\nimport boom_t\nboom_t.go()\n", {"boom_t": "def go():\n    1 / 0\n"})
    assert helpers.locate(error, "<user>") == helpers.Place(3, "helper:boom_t", 2)
    assert helpers.locate(error, "<user>").helper == "boom_t"
    at_import = run_failing("import top_err_t\n", {"top_err_t": "X = 1\nraise ValueError('top')\n"})
    assert helpers.locate(at_import, "<user>") == helpers.Place(1, "helper:top_err_t", 2)


def test_a_syntax_error_in_a_helper_points_at_its_line() -> None:
    error = run_failing("\nimport syn_t\n", {"syn_t": "x = 1\ndef f(:\n"})
    place = helpers.locate(error, "<user>")
    assert place.where == "helper:syn_t" and place.helper_line == 2 and place.line == 2


def test_an_error_in_the_code_itself_is_where_it_was() -> None:
    error = run_failing("import fine_t\nfine_t.X / 0\n", {"fine_t": "X = 1\n"})
    assert helpers.locate(error, "<user>") == helpers.Place(2)
    syntax = SyntaxError("bad", ("<user>", 4, 1, "x"))
    assert helpers.locate(syntax, "<user>") == helpers.Place(4)


# -- renaming imports ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("from grid import count\n", "from new_grid import count\n"),
        ("import grid as g\nx = g.count(1)\n", "import new_grid as g\nx = g.count(1)\n"),
        ("import grid\nx = grid.count(1)\n", "import new_grid\nx = new_grid.count(1)\n"),
        ("import os, grid\n", "import os, new_grid\n"),
        # `grid` is bound by something else too: the uses keep their name through an alias
        ("import grid\ngrid = grid.count\n", "import new_grid as grid\ngrid = grid.count\n"),
        (
            "import grid\ndef f(new_grid):\n    return grid\n",
            "import new_grid as grid\ndef f(new_grid):\n    return grid\n",
        ),
        (
            "def f():\n    from grid import count\n    return count\n",
            "def f():\n    from new_grid import count\n    return count\n",
        ),
        ("x = 'é'; from grid import count\n", "x = 'é'; from new_grid import count\n"),  # columns in bytes
        ("s = 'import grid'\n", None),  # text is never touched
        ("import grid.sub\n", None),  # a helper has no submodules
        ("from gridx import y\nimport gridx\n", None),
        ("from . import grid\n", None),
        ("def broken(:\n", None),
    ],
)
def test_rename_imports(source: str, expected: str | None) -> None:
    assert rename_imports(source, "grid", "new_grid") == expected


def test_attributes_named_like_the_helper_are_left_alone() -> None:
    source = "import grid\nx = obj.grid + grid.count\n"
    assert rename_imports(source, "grid", "g2") == "import g2\nx = obj.grid + g2.count\n"


# -- the file format -----------------------------------------------------------------------------------------


def test_helpers_round_trip_and_are_omitted_when_empty() -> None:
    assert "helpers" not in json.loads(Project().model_dump_json())
    project = Project(helpers=[Helper(name="grid", code=GRID), Helper(name="p", code="", description="d")])
    data = json.loads(project.model_dump_json(by_alias=True))
    assert data["helpers"] == [{"name": "grid", "code": GRID}, {"name": "p", "code": "", "description": "d"}]
    again = Project.model_validate_json(project.model_dump_json(by_alias=True))
    assert again == project and again.helper("p").description == "d"


@pytest.mark.parametrize(
    ("helper_list", "message"),
    [
        ([{"name": "os", "code": ""}], "standard library"),
        ([{"name": "a b", "code": ""}], "not a Python name"),
        ([{"name": "np", "code": ""}], "the editor uses"),
        ([{"name": "g", "code": "x" * (64 * 1024 + 1)}], "longer than 64 KB"),
        ([{"name": "g", "code": ""}, {"name": "g", "code": "1"}], "duplicate helper names"),
        ([{"name": f"h{i}", "code": ""} for i in range(51)], "at most 50 helpers"),
    ],
)
def test_invalid_helpers_are_refused_on_load(helper_list: list[dict], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        Project.model_validate({"helpers": helper_list})


def test_fifty_helpers_and_64_kb_are_allowed() -> None:
    Project.model_validate({"helpers": [{"name": f"h{i}", "code": "x" * 10} for i in range(50)]})
    Helper(name="big", code="x" * (64 * 1024))


# -- edits ---------------------------------------------------------------------------------------------------


TRI = "import grid\nPARAMS = {}\ndef build(p):\n    return grid.count(4)\n"


def project_with_users() -> Project:
    return with_helpers(
        ("grid", GRID),
        ("plot", "from grid import count\nN = count(2)\n"),
        layers=[python_layer("tri", TRI), code_layer("scene", "import grid\nclass A(Scene): pass\n")],
    )


def test_add_helper_checks_the_name_and_rebuilds_the_code_that_may_import_it() -> None:
    project = Project(layers=[python_layer("tri", TRI)])
    edit = edits.add_helper(project, "grid", GRID, "spacing")
    assert edit.project.helper("grid") == Helper(name="grid", code=GRID, description="spacing")
    assert edit.kind == "spec" and edit.layer_ids == {"tri"}
    with pytest.raises(EditError, match="already exists"):
        edits.add_helper(edit.project, "grid", "")
    with pytest.raises(EditError, match="standard library"):
        edits.add_helper(project, "os", "")
    with pytest.raises(EditError, match="installed on this computer"):
        edits.add_helper(project, "pydantic", "")
    with pytest.raises(EditError, match="longer than 64 KB"):
        edits.add_helper(project, "big", "x" * (64 * 1024 + 1))
    alone = edits.add_helper(Project(), "grid", GRID)  # nothing runs code: nothing to rebuild
    assert alone.kind == "timing" and alone.layer_ids == frozenset()


def test_add_helper_refuses_the_51st() -> None:
    project = Project(helpers=[Helper(name=f"h{i}") for i in range(50)])
    with pytest.raises(EditError, match="at most 50"):
        edits.add_helper(project, "one_more", "")


def test_update_helper_code_rebuilds_its_users_but_a_description_does_not() -> None:
    project = project_with_users()
    edit = edits.update_helper(project, "grid", code=GRID + "\nEXTRA = 1\n")
    assert edit.project.helper("grid").code.endswith("EXTRA = 1\n")
    assert edit.kind == "spec" and edit.layer_ids == {"tri", "scene"}
    described = edits.update_helper(project, "grid", description="the grid")
    assert described.kind == "timing" and described.layer_ids == frozenset()
    assert described.project.helper("grid").code == GRID
    with pytest.raises(EditError, match="no helper 'nope'"):
        edits.update_helper(project, "nope", code="")


def test_rename_helper_rewrites_the_imports_of_its_users() -> None:
    project = project_with_users()
    edit = edits.rename_helper(project, "grid", "grid2")
    assert [h.name for h in edit.project.helpers] == ["grid2", "plot"]
    assert edit.project.helper("plot").code == "from grid2 import count\nN = count(2)\n"
    tri = edit.project.layer("tri").spec.params["code"]
    assert tri == "import grid2\nPARAMS = {}\ndef build(p):\n    return grid2.count(4)\n"
    assert edit.project.layer("scene").spec.params["code"].startswith("import grid2\n")
    assert dict(edit.rewritten)[TRI] == tri and len(edit.rewritten) == 3
    assert edit.kind == "spec"


def test_rename_helper_without_fixing_imports_and_refusals() -> None:
    project = project_with_users()
    edit = edits.rename_helper(project, "grid", "grid2", fix_imports=False)
    assert edit.project.layer("tri").spec.params["code"] == TRI and edit.rewritten == ()
    assert edits.rename_helper(project, "grid", "grid").project is project
    with pytest.raises(EditError, match="already exists"):
        edits.rename_helper(project, "grid", "plot")
    with pytest.raises(EditError, match="keyword"):
        edits.rename_helper(project, "grid", "class")
    with pytest.raises(EditError, match="no helper"):
        edits.rename_helper(project, "nope", "x")


def test_remove_helper_is_refused_while_code_imports_it() -> None:
    project = project_with_users()
    with pytest.raises(EditError) as caught:
        edits.remove_helper(project, "grid")
    assert str(caught.value) == "helper 'grid' is imported by tri, scene, helper plot"
    edit = edits.remove_helper(project, "grid", force=True)
    assert [h.name for h in edit.project.helpers] == ["plot"] and edit.kind == "spec"
    unused = edits.remove_helper(edit.project, "plot")
    assert unused.project.helpers == []
    assert "helpers" not in json.loads(unused.project.model_dump_json())


def test_classify_agrees_and_other_edits_keep_the_helpers() -> None:
    project = project_with_users()
    changed = edits.update_helper(project, "grid", code="X = 2\n").project
    assert edits.classify(project, changed) == ("spec", frozenset({"tri", "scene"}))
    renamed = edits.update_layer(project, "tri", name="Triangle").project
    assert renamed.helpers == project.helpers
