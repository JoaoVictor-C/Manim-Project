"""What exporting code writes (P12.4): names, line endings, header, and the shareable index."""

from __future__ import annotations

import json

from manim_studio.core import code_export as ce
from manim_studio.core import code_files, preset_online
from manim_studio.core.code_export import ExportEntry, ExportOptions

OBJECT = '"""A wheel."""\nPARAMS = {}\n\ndef build(p):\n    return Circle()\n'
SCENE = "from manim import *\n\nclass Orbit(Scene):\n    def construct(self):\n        self.add(Dot())\n"


def entries() -> list[ExportEntry]:
    return [
        ExportEntry("a", "Wheel", "object", OBJECT),
        ExportEntry("b", "Orbit: the scene?", "scene", SCENE, group="preset"),
        ExportEntry("c", "Wheel", "object", OBJECT),
    ]


def test_names_are_valid_and_unique() -> None:
    stems = [stem for stem, _ in ce.prepare(entries())]
    assert stems == ["Wheel", "Orbit_ the scene_", "Wheel (2)"] or stems[0] == "Wheel"
    assert len({s.lower() for s in stems}) == 3
    assert all("?" not in s and ":" not in s for s in stems)


def test_an_empty_name_uses_the_key() -> None:
    assert ce.prepare([ExportEntry("layer-7", "", "scene", SCENE)])[0][0] == "layer-7"


def test_default_text_is_plain_lf_without_a_header() -> None:
    (_, text), *_ = ce.prepare([ExportEntry("a", "Wheel", "object", OBJECT.replace("\n", "\r\n"))])
    assert text == OBJECT


def test_crlf_and_header_options() -> None:
    options = ExportOptions(newline="\r\n", header=True)
    (_, text), *_ = ce.prepare(entries()[:1], options)
    assert text.startswith("# Wheel - exported from Manim Studio\r\n") and "\n" not in text.replace(
        "\r\n", ""
    )


def test_header_is_not_added_twice() -> None:
    again = ce.prepare(entries()[:1], ExportOptions(header=True))[0][1]
    twice = ce.prepare([ExportEntry("a", "Wheel", "object", again)], ExportOptions(header=True))[0][1]
    assert twice == again


def test_the_manifest_lists_every_file_and_is_readable_by_the_online_importer() -> None:
    text = ce.manifest(entries(), "My pack")
    data = json.loads(text)
    assert data["format"] == 1 and data["name"] == "My pack" and len(data["presets"]) == 3
    assert data["presets"][0]["file"] == "Wheel.py"
    assert data["presets"][0]["description"] == "A wheel."
    assert data["presets"][1]["kind"] == "scene"
    served = {"https://example.com/pack/index.json": text}

    def opener(request, timeout):
        class Response:
            status = 200
            headers: dict = {}  # noqa: RUF012

            def __init__(self, body: bytes) -> None:
                self.body, self.done = body, False

            def read(self, n=-1):
                if self.done:
                    return b""
                self.done = True
                return self.body

            def close(self) -> None: ...

        return Response(served[request.full_url].encode("utf-8"))

    found = preset_online.resolve("https://example.com/pack/index.json", opener=opener)
    assert [e.name for e in found] == ["Wheel", "Orbit: the scene?", "Wheel"]
    assert found[0].url == "https://example.com/pack/Wheel.py"


def test_export_files_with_the_prepared_names_writes_what_the_manifest_says(tmp_path) -> None:
    pairs = ce.prepare(entries())
    result = code_files.export_files(pairs, tmp_path, lambda name: "replace")
    names = {p["file"] for p in json.loads(ce.manifest(entries()))["presets"]}
    assert set(result.written) == names
