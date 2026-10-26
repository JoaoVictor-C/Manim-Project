"""Online presets (P12.3): link parsing, manifests, safe fetching.

Nothing here reaches the internet: the network is a real ``http.server`` thread on 127.0.0.1
(ephemeral port), and the GitHub API shapes go through injected openers.
"""

from __future__ import annotations

import http.server
import io
import json
import socket
import ssl
import threading
import urllib.error
import urllib.request
from typing import ClassVar

import pytest

from manim_studio.core.exchange import preset_online as po
from manim_studio.core.exchange.preset_online import (
    OnlineEntry,
    OnlineError,
    fetch_entry,
    fetch_text,
    resolve,
)

PY = "from manim import *\n\n\nclass A(Scene):\n    def construct(self):\n        pass\n"


# --- a real local server --------------------------------------------------------------------


class _Handler(http.server.BaseHTTPRequestHandler):
    routes: ClassVar[dict] = {}
    seen: ClassVar[list] = []

    def do_GET(self):
        type(self).seen.append((self.path, self.headers.get("User-Agent")))
        status, headers, body = type(self).routes.get(self.path.split("?")[0], (404, {}, b"nope"))
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # silence
        pass


@pytest.fixture
def server():
    handler = type("H", (_Handler,), {"routes": {}, "seen": []})
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    handler.base = base
    yield handler
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=5)


def ok(body, **headers):
    data = body.encode("utf-8") if isinstance(body, str) else body
    return (200, headers, data)


def redirect(to, code=302):
    return (code, {"Location": to}, b"")


# --- fakes for injected openers -------------------------------------------------------------


class FakeResponse:
    def __init__(self, body=b"", status=200, headers=None):
        self._io = io.BytesIO(body if isinstance(body, bytes) else body.encode("utf-8"))
        self.status = status
        self.headers = headers or {}
        self.closed = False

    def read(self, n=-1):
        return self._io.read(n)

    def close(self):
        self.closed = True


class Script:
    """An opener answering from a ``{url: response-or-exception}`` table, recording requests."""

    def __init__(self, table):
        self.table = table
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append(request)
        result = self.table[request.full_url]
        if isinstance(result, Exception):
            raise result
        return result


def json_response(data, **kw):
    return FakeResponse(json.dumps(data), **kw)


# --- direct file, size cap, encoding --------------------------------------------------------


def test_fetch_text_direct_file_sends_user_agent(server):
    server.routes["/a.py"] = ok(PY)
    assert fetch_text(server.base + "/a.py") == PY
    assert server.seen[0][1] == "Manim-Studio"


def test_resolve_direct_py_url_makes_one_entry_without_network():
    entries = resolve("https://example.com/presets/My%20Circle.py?raw=1", opener=Script({}))
    assert entries == [
        OnlineEntry(
            name="My Circle",
            url="https://example.com/presets/My%20Circle.py?raw=1",
            source="https://example.com/presets/My%20Circle.py?raw=1",
        )
    ]


def test_resolve_direct_py_from_local_server_and_fetch_entry(server):
    server.routes["/dir/circle.py"] = ok(PY)
    (entry,) = resolve(server.base + "/dir/circle.py")
    assert entry.name == "circle" and entry.kind_hint == "" and entry.size is None
    assert fetch_entry(entry) == PY


def test_bom_is_tolerated(server):
    server.routes["/b.py"] = ok(b"\xef\xbb\xbf" + PY.encode())
    assert fetch_text(server.base + "/b.py") == PY


def test_size_cap_with_content_length(server):
    server.routes["/big.py"] = ok("x" * 200)
    with pytest.raises(OnlineError, match="too large"):
        fetch_text(server.base + "/big.py", max_bytes=100)


def test_size_cap_stops_reading_without_content_length():
    class Endless:
        status = 200
        headers: ClassVar[dict] = {}

        def __init__(self):
            self.served = 0

        def read(self, n=-1):
            self.served += n
            return b"a" * n

    stream = Endless()
    with pytest.raises(OnlineError, match="too large"):
        fetch_text("https://example.com/x.py", max_bytes=1000, opener=lambda r, t: stream)
    assert stream.served == 1001  # one byte past the cap, then it stopped


def test_exactly_at_the_cap_is_fine(server):
    server.routes["/x.py"] = ok("a" * 100)
    assert len(fetch_text(server.base + "/x.py", max_bytes=100)) == 100


def test_binary_body_is_refused(server):
    server.routes["/bin.py"] = ok(b"MZ\x90\x00\x03\x00")
    with pytest.raises(OnlineError, match="binary"):
        fetch_text(server.base + "/bin.py")


def test_non_utf8_body_is_refused(server):
    server.routes["/l1.py"] = ok("caf\xe9".encode("latin-1"))
    with pytest.raises(OnlineError, match="UTF-8"):
        fetch_text(server.base + "/l1.py")


# --- http errors ----------------------------------------------------------------------------


def test_404_is_friendly(server):
    with pytest.raises(OnlineError, match="404"):
        fetch_text(server.base + "/missing.py")


def test_5xx_is_friendly(server):
    server.routes["/boom.py"] = (503, {}, b"")
    with pytest.raises(OnlineError, match="503"):
        fetch_text(server.base + "/boom.py")


def test_github_403_mentions_the_rate_limit():
    err = urllib.error.HTTPError(
        "https://api.github.com/x", 403, "Forbidden", {"X-RateLimit-Remaining": "0"}, io.BytesIO(b"{}")
    )

    def opener(request, timeout):
        raise err

    with pytest.raises(OnlineError, match="limit"):
        fetch_text("https://api.github.com/x", opener=opener)


def test_other_403_has_no_github_hint():
    err = urllib.error.HTTPError("https://example.com/x.py", 403, "Forbidden", {}, io.BytesIO(b""))

    def opener(request, timeout):
        raise err

    with pytest.raises(OnlineError) as info:
        fetch_text("https://example.com/x.py", opener=opener)
    assert "403" in str(info.value) and "GitHub" not in str(info.value)


def test_returned_error_status_is_handled_too():
    with pytest.raises(OnlineError, match="404"):
        fetch_text("https://example.com/x.py", opener=lambda r, t: FakeResponse(status=404))


@pytest.mark.parametrize(
    ("exc", "text"),
    [
        (urllib.error.URLError(TimeoutError("t")), "too long"),
        (TimeoutError(), "too long"),
        (urllib.error.URLError(socket.gaierror(11001, "no host")), "could not be found"),
        (urllib.error.URLError(ssl.SSLCertVerificationError("bad cert")), "certificate"),
        (urllib.error.URLError(ssl.SSLError("tls")), "TLS"),
        (ConnectionResetError(), "connection failed"),
        (urllib.error.URLError(ConnectionRefusedError()), "refused the connection"),
    ],
)
def test_network_failures_become_friendly_errors(exc, text):
    def opener(request, timeout):
        raise exc

    with pytest.raises(OnlineError, match=text):
        fetch_text("https://example.com/x.py", opener=opener)


def test_connection_refused_on_real_socket():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    with pytest.raises(OnlineError):
        fetch_text(f"http://127.0.0.1:{port}/a.py", timeout=2)


def test_response_is_closed():
    response = FakeResponse(PY)
    fetch_text("https://example.com/x.py", opener=lambda r, t: response)
    assert response.closed


# --- scheme rules and redirects -------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/a.py",
        "ftp://example.com/a.py",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "example.com/a.py",
        "",
    ],
)
def test_only_https_or_local_http(url):
    opener = Script({})
    with pytest.raises(OnlineError):
        fetch_text(url, opener=opener)
    assert opener.requests == []


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "[::1]"])
def test_plain_http_allowed_for_local_hosts(host):
    opener = Script({f"http://{host}:8000/a.py": FakeResponse(PY)})
    assert fetch_text(f"http://{host}:8000/a.py", opener=opener) == PY


def test_redirects_are_followed(server):
    server.routes["/a.py"] = redirect("/b.py")
    server.routes["/b.py"] = redirect(server.base + "/c.py", 301)
    server.routes["/c.py"] = ok(PY)
    assert fetch_text(server.base + "/a.py") == PY


def test_three_redirects_are_allowed_a_fourth_is_not(server):
    for i in range(4):
        server.routes[f"/r{i}"] = redirect(f"/r{i + 1}")
    server.routes["/r4"] = ok(PY)
    with pytest.raises(OnlineError, match="redirects too many"):
        fetch_text(server.base + "/r0")
    assert fetch_text(server.base + "/r1") == PY  # three hops


def test_redirect_loop_ends(server):
    server.routes["/loop"] = redirect("/loop")
    with pytest.raises(OnlineError, match="too many"):
        fetch_text(server.base + "/loop")


def test_redirect_without_location(server):
    server.routes["/a"] = (302, {}, b"")
    with pytest.raises(OnlineError, match="without saying where"):
        fetch_text(server.base + "/a")


def test_redirect_from_https_to_http_is_refused():
    opener = Script(
        {
            "https://example.com/a.py": FakeResponse(
                status=302, headers={"Location": "http://example.com/b.py"}
            ),
        }
    )
    with pytest.raises(OnlineError, match="not allowed"):
        fetch_text("https://example.com/a.py", opener=opener)
    assert len(opener.requests) == 1


def test_redirect_from_https_to_local_http_is_refused():
    opener = Script(
        {
            "https://example.com/a.py": FakeResponse(
                status=302, headers={"Location": "http://127.0.0.1/b.py"}
            ),
        }
    )
    with pytest.raises(OnlineError, match="plain http"):
        fetch_text("https://example.com/a.py", opener=opener)


def test_redirect_to_another_scheme_is_refused():
    opener = Script(
        {"https://example.com/a.py": FakeResponse(status=302, headers={"Location": "file:///etc/passwd"})}
    )
    with pytest.raises(OnlineError):
        fetch_text("https://example.com/a.py", opener=opener)


def test_relative_redirect_and_http_error_redirect():
    err = urllib.error.HTTPError(
        "https://example.com/dir/a.py", 302, "Found", {"Location": "../b.py"}, io.BytesIO(b"")
    )
    table = {"https://example.com/dir/a.py": err, "https://example.com/b.py": FakeResponse(PY)}
    assert fetch_text("https://example.com/dir/a.py", opener=Script(table)) == PY


def test_default_opener_does_not_follow_redirects_itself(server):
    server.routes["/a.py"] = redirect("/b.py")
    server.routes["/b.py"] = ok(PY)
    with pytest.raises(urllib.error.HTTPError) as info:
        po._default_opener(urllib.request.Request(server.base + "/a.py"), 5)
    assert info.value.code == 302


# --- manifests ------------------------------------------------------------------------------


def manifest(**over):
    data = {
        "format": 1,
        "name": "Example",
        "presets": [
            {"name": "Circle", "file": "circle.py", "description": "A circle", "kind": "object"},
            {"name": "Title", "file": "sub/title.py", "kind": "scene"},
            {"file": "plain.py", "kind": "bogus"},
        ],
    }
    data.update(over)
    return json.dumps(data)


def test_manifest_with_relative_paths(server):
    server.routes["/pack/index.json"] = ok(manifest())
    server.routes["/pack/circle.py"] = ok(PY)
    entries = resolve(server.base + "/pack/index.json")
    assert [e.name for e in entries] == ["Circle", "Title", "plain"]
    assert [e.kind_hint for e in entries] == ["object", "scene", ""]
    assert entries[0].description == "A circle"
    assert entries[0].url == server.base + "/pack/circle.py"
    assert entries[1].url == server.base + "/pack/sub/title.py"
    assert all(e.source == server.base + "/pack/index.json" for e in entries)
    assert fetch_entry(entries[0]) == PY


def test_manifest_drops_non_py_non_https_and_bad_items():
    items = [
        {"name": "ok", "file": "https://other.example/ok.py"},
        {"name": "txt", "file": "readme.txt"},
        {"name": "http", "file": "http://other.example/x.py"},
        {"name": "scheme", "file": "ftp://other.example/x.py"},
        {"name": "nofile"},
        {"name": "num", "file": 3},
        "junk",
    ]
    body = json.dumps({"format": 1, "presets": items})
    entries = resolve(
        "https://example.com/m.json", opener=Script({"https://example.com/m.json": FakeResponse(body)})
    )
    assert [e.name for e in entries] == ["ok"]
    assert entries[0].url == "https://other.example/ok.py"


def test_manifest_is_capped_at_200_entries():
    items = [{"name": f"p{i}", "file": f"p{i}.py"} for i in range(300)]
    body = json.dumps({"format": 1, "presets": items})
    entries = resolve(
        "https://example.com/m.json", opener=Script({"https://example.com/m.json": FakeResponse(body)})
    )
    assert len(entries) == 200 and entries[-1].name == "p199"


def test_manifest_unknown_format_version(server):
    server.routes["/m.json"] = ok(manifest(format=2))
    with pytest.raises(OnlineError, match="format 2"):
        resolve(server.base + "/m.json")


def test_manifest_without_format_or_not_a_manifest(server):
    server.routes["/m.json"] = ok(json.dumps({"presets": []}))
    server.routes["/list.json"] = ok("[1, 2]")
    for path in ("/m.json", "/list.json"):
        with pytest.raises(OnlineError, match="manifest"):
            resolve(server.base + path)


def test_manifest_without_usable_presets(server):
    server.routes["/m.json"] = ok(json.dumps({"format": 1, "presets": [{"file": "a.txt"}]}))
    with pytest.raises(OnlineError, match="no usable"):
        resolve(server.base + "/m.json")


def test_link_that_is_not_json_says_what_was_expected(server):
    server.routes["/page"] = ok("<html>hello</html>")
    with pytest.raises(OnlineError, match=r"\.py file"):
        resolve(server.base + "/page")


def test_resolve_404(server):
    with pytest.raises(OnlineError, match="404"):
        resolve(server.base + "/nothing.json")


def test_resolve_rejects_empty_and_plain_http():
    with pytest.raises(OnlineError):
        resolve("   ")
    with pytest.raises(OnlineError, match="https"):
        resolve("http://example.com/a.py")


# --- sanitising names -----------------------------------------------------------------------


def test_names_from_the_network_are_sanitised():
    evil = "  ..\\..//Bad\x00Name\x1b[31m\n\twith   spaces‮  " + "x" * 200
    body = json.dumps({"format": 1, "presets": [{"name": evil, "file": "a.py", "description": "d\x00e\nf"}]})
    (entry,) = resolve(
        "https://example.com/m.json", opener=Script({"https://example.com/m.json": FakeResponse(body)})
    )
    assert len(entry.name) <= 80
    assert "/" not in entry.name and "\\" not in entry.name
    assert not any(ord(c) < 32 or c in "‮" for c in entry.name)
    assert "  " not in entry.name and entry.name == entry.name.strip()
    assert entry.name.startswith(".. .. Bad")
    assert entry.description == "de f"


@pytest.mark.parametrize("raw", ["", "   ", "\x00\x01", "/\\", None, 5])
def test_empty_names_become_preset(raw):
    assert po._clean_name(raw) == "Preset"


def test_name_limit():
    assert len(po._clean_name("a" * 500)) == 80


# --- GitHub link parsing --------------------------------------------------------------------


def gh(url):
    return po.parse_github(url)


def test_blob_link_becomes_raw():
    kind, info = gh("https://github.com/example/presets/blob/main/shapes/Circle%20One.py")
    assert kind == "file"
    assert info["raw"] == "https://raw.githubusercontent.com/example/presets/main/shapes/Circle%20One.py"


@pytest.mark.parametrize("suffix", ["", "?plain=1", "#L10", "?raw=true#top"])
def test_blob_link_ignores_query_and_fragment(suffix):
    kind, info = gh("https://github.com/example/presets/blob/v1.2/a.py" + suffix)
    assert (kind, info["raw"]) == ("file", "https://raw.githubusercontent.com/example/presets/v1.2/a.py")


def test_blob_link_must_be_a_py_file():
    with pytest.raises(OnlineError, match=r"\.py"):
        gh("https://github.com/example/presets/blob/main/README.md")
    with pytest.raises(OnlineError):
        gh("https://github.com/example/presets/blob/main")


def test_www_prefix_and_raw_variant():
    assert gh("https://www.github.com/example/presets/raw/main/a.py")[0] == "file"


def test_tree_link_lists_a_folder():
    kind, info = gh("https://github.com/example/presets/tree/dev/packs/basic/")
    assert kind == "contents"
    assert info["api"] == "https://api.github.com/repos/example/presets/contents/packs/basic?ref=dev"


def test_tree_link_ref_only():
    assert gh("https://github.com/example/presets/tree/main")[1]["api"] == (
        "https://api.github.com/repos/example/presets/contents?ref=main"
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/example/presets",
        "https://github.com/example/presets/",
        "https://github.com/example/presets.git",
        "https://github.com/example/presets?tab=readme",
        "https://github.com/example/presets/#readme",
    ],
)
def test_repository_link_lists_the_root(url):
    kind, info = gh(url)
    assert (kind, info["api"]) == ("contents", "https://api.github.com/repos/example/presets/contents")


def test_raw_githubusercontent_links():
    url = "https://raw.githubusercontent.com/example/presets/main/a.py"
    assert gh(url) == ("file", {"raw": url})
    assert gh("https://raw.githubusercontent.com/example/presets/main/index.json")[0] == "other"


@pytest.mark.parametrize(
    "url",
    [
        "https://gist.github.com/someone/0123456789abcdef0123456789abcdef",
        "https://gist.github.com/someone/0123456789abcdef0123456789abcdef/",
        "https://gist.github.com/0123456789abcdef0123456789abcdef",
        "https://gist.github.com/someone/0123456789abcdef0123456789abcdef#file-a-py",
    ],
)
def test_gist_links(url):
    kind, info = gh(url)
    assert (kind, info["api"]) == ("gist", "https://api.github.com/gists/0123456789abcdef0123456789abcdef")


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/example",
        "https://github.com/",
        "https://github.com/example/presets/issues/3",
        "https://github.com/example/pre sets/tree/main",
        "https://github.com/example/presets/tree/main/../x",
        "https://gist.github.com/",
        "https://gist.github.com/someone/not-an-id",
    ],
)
def test_bad_github_links(url):
    with pytest.raises(OnlineError):
        gh(url)


def test_other_hosts_are_not_github():
    assert gh("https://example.com/example/presets")[0] == "other"
    assert gh("https://evilgithub.com/example/presets")[0] == "other"


# --- GitHub API shapes (injected) -----------------------------------------------------------

API = "https://api.github.com/repos/example/presets/contents"


def listing():
    return [
        {
            "name": "zeta.py",
            "type": "file",
            "size": 120,
            "download_url": "https://raw.githubusercontent.com/example/presets/main/zeta.py",
        },
        {
            "name": "alpha.py",
            "type": "file",
            "size": 80,
            "download_url": "https://raw.githubusercontent.com/example/presets/main/alpha.py",
        },
        {
            "name": "README.md",
            "type": "file",
            "size": 5,
            "download_url": "https://raw.githubusercontent.com/example/presets/main/README.md",
        },
        {"name": "sub", "type": "dir", "size": 0, "download_url": None},
        {"name": "link.py", "type": "file", "size": 1, "download_url": None},
        {"name": "http.py", "type": "file", "size": 1, "download_url": "http://example.com/http.py"},
    ]


def test_repository_listing_keeps_py_files_with_download_url():
    opener = Script({API: json_response(listing())})
    entries = resolve("https://github.com/example/presets", opener=opener)
    assert [e.name for e in entries] == ["alpha", "zeta"]
    assert entries[0].url == "https://raw.githubusercontent.com/example/presets/main/alpha.py"
    assert entries[0].size == 80
    assert entries[0].source == "https://github.com/example/presets"
    accept = opener.requests[0].get_header("Accept")
    assert accept and "github" in accept
    assert opener.requests[0].get_header("User-agent") == "Manim-Studio"


def test_folder_listing_passes_the_ref():
    url = API + "/packs?ref=dev"
    opener = Script({url: json_response(listing())})
    entries = resolve("https://github.com/example/presets/tree/dev/packs", opener=opener)
    assert len(entries) == 2 and opener.requests[0].full_url == url


def test_listing_is_capped_at_100():
    items = [
        {
            "name": f"p{i:03}.py",
            "type": "file",
            "download_url": f"https://raw.githubusercontent.com/e/p/m/p{i:03}.py",
        }
        for i in range(150)
    ]
    entries = resolve("https://github.com/example/presets", opener=Script({API: json_response(items)}))
    assert len(entries) == 100 and entries[0].name == "p000"


def test_listing_without_py_files():
    opener = Script(
        {API: json_response([{"name": "a.md", "type": "file", "download_url": "https://x.example/a.md"}])}
    )
    with pytest.raises(OnlineError, match=r"No \.py files"):
        resolve("https://github.com/example/presets", opener=opener)


def test_listing_error_object():
    opener = Script({API: json_response({"message": "Not Found"})})
    with pytest.raises(OnlineError, match="Not Found"):
        resolve("https://github.com/example/presets", opener=opener)


def test_listing_404_and_rate_limit():
    not_found = urllib.error.HTTPError(API, 404, "Not Found", {}, io.BytesIO(b"{}"))
    with pytest.raises(OnlineError, match="404"):
        resolve("https://github.com/example/presets", opener=Script({API: not_found}))
    limited = urllib.error.HTTPError(
        API, 403, "rate limit", {"X-RateLimit-Remaining": "0"}, io.BytesIO(b"{}")
    )
    with pytest.raises(OnlineError, match="limit"):
        resolve("https://github.com/example/presets", opener=Script({API: limited}))


def test_listing_not_json():
    with pytest.raises(OnlineError, match="not JSON"):
        resolve("https://github.com/example/presets", opener=Script({API: FakeResponse("<html>")}))


GIST_ID = "0123456789abcdef0123456789abcdef"
GIST_API = f"https://api.github.com/gists/{GIST_ID}"


def test_gist_json():
    data = {
        "description": "Two scenes",
        "files": {
            "intro.py": {
                "filename": "intro.py",
                "raw_url": "https://gist.githubusercontent.com/u/1/raw/intro.py",
                "size": 50,
                "type": "application/x-python",
            },
            "notes.txt": {
                "filename": "notes.txt",
                "raw_url": "https://gist.githubusercontent.com/u/1/raw/notes.txt",
                "size": 5,
            },
            "Outro.PY": {
                "filename": "Outro.PY",
                "raw_url": "https://gist.githubusercontent.com/u/1/raw/Outro.PY",
            },
            "bad.py": {"filename": "bad.py", "raw_url": "http://example.com/bad.py"},
        },
    }
    opener = Script({GIST_API: json_response(data)})
    entries = resolve(f"https://gist.github.com/someone/{GIST_ID}", opener=opener)
    assert [e.name for e in entries] == ["intro", "Outro"]
    assert entries[0].description == "Two scenes" and entries[0].size == 50
    assert entries[1].size is None


def test_gist_without_py_files_and_malformed():
    only_txt = {"files": {"a.txt": {"filename": "a.txt", "raw_url": "https://x.example/a.txt"}}}
    with pytest.raises(OnlineError, match=r"no \.py"):
        resolve(f"https://gist.github.com/{GIST_ID}", opener=Script({GIST_API: json_response(only_txt)}))
    with pytest.raises(OnlineError, match="gist"):
        resolve(f"https://gist.github.com/{GIST_ID}", opener=Script({GIST_API: json_response([1])}))


def test_blob_link_resolves_without_network():
    entries = resolve("https://github.com/example/presets/blob/main/shapes/Circle.py", opener=Script({}))
    assert entries[0].name == "Circle"
    assert entries[0].url == "https://raw.githubusercontent.com/example/presets/main/shapes/Circle.py"


def test_fetch_entry_uses_the_entry_url():
    entry = OnlineEntry(name="a", url="https://raw.githubusercontent.com/example/presets/main/a.py")
    opener = Script({entry.url: FakeResponse(PY)})
    assert fetch_entry(entry, opener=opener) == PY


def test_downloaded_code_is_never_executed():
    """The text is returned verbatim, even when it would do harm if it were run."""
    body = "raise SystemExit('run!')\nimport os\nos.remove('x')\n"
    entry = OnlineEntry(name="a", url="https://example.com/a.py")
    assert fetch_entry(entry, opener=lambda r, t: FakeResponse(body)) == body
