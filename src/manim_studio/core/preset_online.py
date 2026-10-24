"""Fetching presets from the internet, safely (P12.3).

``resolve(url)`` turns what the user pasted into a list of ``OnlineEntry`` (a name and the
address of one raw ``.py`` file each); ``fetch_entry(entry)`` downloads one of them as text.
Accepted links:

* a direct ``.py`` file (``https://host/path/file.py``): one entry;
* a manifest, a JSON file ``{"format": 1, "name": ..., "presets": [{"name", "file",
  "description", "kind"}]}`` whose ``file`` is relative to the manifest or an absolute
  ``https`` URL; at most 200 entries;
* GitHub: a file (``/blob/``), a folder (``/tree/``) or a whole repository (``github.com/o/r``),
  listed through the contents API (``.py`` files only, at most 100), a ``raw.githubusercontent``
  link, and a gist (``gist.github.com/<user>/<id>``). The branch of a ``/tree/`` or ``/blob/``
  link is the one path segment after it, so a branch name containing ``/`` is not understood.

Everything downloaded is **data**. It is only ever returned as a ``str``: nothing here compiles,
executes, imports or writes it to disk, and it stays untrusted until the user runs it.

Network rules (``fetch_text``): HTTPS only (plain HTTP only for ``localhost``, ``127.0.0.1`` and
``[::1]``, which the tests use); at most 3 redirects, never from HTTPS to HTTP; the body is read
with a hard cap; UTF-8 text without NUL bytes; every failure becomes an ``OnlineError`` whose text
is meant to be shown to the user as is.

Pure: standard library only, no Qt, no Manim.
"""

from __future__ import annotations

import contextlib
import json
import re
import socket
import ssl
import unicodedata
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, unquote, urljoin, urlsplit

USER_AGENT = "Manim-Studio"
MAX_BYTES = 1_000_000
TIMEOUT = 10.0
MAX_REDIRECTS = 3
MAX_MANIFEST_ENTRIES = 200
MAX_LISTING_ENTRIES = 100
MANIFEST_FORMAT = 1
NAME_LIMIT = 80
DESCRIPTION_LIMIT = 300

_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_REDIRECT_CODES = frozenset({301, 302, 303, 307, 308})
_KINDS = ("object", "scene")
_GITHUB_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
_GIST_ID = re.compile(r"^[0-9A-Fa-f]{6,}$")

Opener = Callable[[urllib.request.Request, float], Any]


class OnlineError(Exception):
    """A short, user-readable reason why something could not be fetched or understood."""


@dataclass(frozen=True)
class OnlineEntry:
    """One preset found online: ``url`` is the absolute address of the raw ``.py`` file."""

    name: str
    url: str
    kind_hint: str = ""  # "object" | "scene" | "" (unknown)
    description: str = ""
    size: int | None = None
    source: str = ""  # the link the user typed


# --- sanitising -----------------------------------------------------------------------------


def _clean(text: object, limit: int, fallback: str = "") -> str:
    """Text from the network made safe to show: no control characters or path separators,
    whitespace collapsed, at most ``limit`` characters; ``fallback`` when nothing is left."""
    if not isinstance(text, str):
        return fallback
    kept = []
    for ch in text:
        if ch in "/\\":
            kept.append(" ")
        elif unicodedata.category(ch)[0] == "C":
            kept.append(" " if ch in "\t\n\r\x0b\x0c" else "")
        else:
            kept.append(ch)
    cleaned = " ".join("".join(kept).split())[:limit].rstrip()
    return cleaned or fallback


def _clean_name(text: object) -> str:
    return _clean(text, NAME_LIMIT, "Preset")


def _clean_description(text: object) -> str:
    return _clean(text, DESCRIPTION_LIMIT)


# --- URL rules ------------------------------------------------------------------------------


def _is_local(host: str | None) -> bool:
    return (host or "").lower() in _LOCAL_HOSTS


def _url_allowed(url: str) -> bool:
    """True for an https URL, or an http one on a local host."""
    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError:
        return False
    if not host:
        return False
    return parts.scheme == "https" or (parts.scheme == "http" and _is_local(host))


def _require_allowed(url: str) -> None:
    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError:
        raise OnlineError("That is not a valid web address.") from None
    if not host or parts.scheme not in ("http", "https"):
        raise OnlineError("That is not a web address. Paste a link starting with https://")
    if parts.scheme == "http" and not _is_local(host):
        raise OnlineError("Only https:// links are allowed (plain http is refused).")


def _path_is_py(url: str) -> bool:
    return unquote(urlsplit(url).path).lower().endswith(".py")


def _stem_of(url: str) -> str:
    base = unquote(urlsplit(url).path).rstrip("/").rsplit("/", 1)[-1]
    if base.lower().endswith(".py"):
        base = base[:-3]
    return base


# --- fetching -------------------------------------------------------------------------------


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Let redirects surface as errors: ``fetch_text`` follows them itself, under its rules."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _default_opener(request: urllib.request.Request, timeout: float) -> Any:
    opener = urllib.request.build_opener(_NoRedirect)
    return opener.open(request, timeout=timeout)


def _header(response: Any, name: str) -> str | None:
    headers = getattr(response, "headers", None)
    if headers is not None:
        value = headers.get(name)
    elif hasattr(response, "getheader"):
        value = response.getheader(name)
    else:
        value = None
    return None if value is None else str(value)


def _http_error(code: int, headers: Any, url: str) -> OnlineError:
    """The friendly error for a failing HTTP status."""
    get = headers.get if headers is not None else (lambda _name: None)
    host = (urlsplit(url).hostname or "").lower()
    if code == 404:
        return OnlineError("Not found (404). Check the link; a private repository cannot be read.")
    if code in (403, 429):
        if (
            host.endswith("github.com")
            or host.endswith("githubusercontent.com")
            or get("X-RateLimit-Remaining") == "0"
        ):
            return OnlineError(
                f"The server refused the request ({code}). If this is GitHub, it is probably its "
                "limit for anonymous requests (60 per hour); wait a while, or paste the link of "
                "a single .py file instead."
            )
        return OnlineError(f"The server refused the request ({code}).")
    if code in (401, 410):
        return OnlineError(f"The server will not give this file ({code}).")
    if 500 <= code < 600:
        return OnlineError(f"The server had a problem ({code}). Try again later.")
    return OnlineError(f"The server answered {code}.")


def _network_error(exc: BaseException) -> OnlineError:
    """The friendly error for a failure below HTTP (DNS, TLS, timeout, connection)."""
    reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
    if isinstance(reason, TimeoutError):
        return OnlineError("The server took too long to answer (timeout).")
    if isinstance(reason, ssl.SSLCertVerificationError):
        return OnlineError("The server's security certificate could not be verified.")
    if isinstance(reason, ssl.SSLError):
        return OnlineError("A secure (TLS) connection could not be made.")
    if isinstance(reason, socket.gaierror):
        return OnlineError("The address could not be found. Check the link and your connection.")
    if isinstance(reason, ConnectionRefusedError):
        return OnlineError("The server refused the connection.")
    if isinstance(reason, OSError):
        return OnlineError("The connection failed. Check your internet connection.")
    return OnlineError("The download failed.")


def _read_capped(response: Any, max_bytes: int) -> bytes:
    """At most ``max_bytes`` of the body; stops reading as soon as one byte more shows up."""
    declared = _header(response, "Content-Length")
    if declared is not None and declared.strip().isdigit() and int(declared) > max_bytes:
        raise OnlineError(f"That file is too large (over {max_bytes // 1000} KB).")
    chunks: list[bytes] = []
    total = 0
    while total <= max_bytes:
        chunk = response.read(min(65536, max_bytes + 1 - total))
        if not chunk:
            break
        chunks.append(bytes(chunk))
        total += len(chunk)
    if total > max_bytes:
        raise OnlineError(f"That file is too large (over {max_bytes // 1000} KB).")
    return b"".join(chunks)


def _decode(data: bytes) -> str:
    if b"\x00" in data:
        raise OnlineError("That is not a text file (it contains binary data).")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise OnlineError("That file is not UTF-8 text.") from None


def _next_url(current: str, location: str) -> str:
    target = urljoin(current, location.strip())
    if not _url_allowed(target):
        raise OnlineError("The link redirects somewhere that is not allowed (only https).")
    if urlsplit(target).scheme == "http" and urlsplit(current).scheme != "http":
        raise OnlineError("The link redirects from https to plain http, which is refused.")
    return target


def _fetch(url: str, *, max_bytes: int, timeout: float, opener: Opener | None, accept: str | None) -> str:
    _require_allowed(url)
    open_ = opener or _default_opener
    current = url
    for hops in range(MAX_REDIRECTS + 1):
        request = urllib.request.Request(current, headers={"User-Agent": USER_AGENT})
        if accept:
            request.add_header("Accept", accept)
        response = None
        try:
            try:
                response = open_(request, timeout)
            except urllib.error.HTTPError as err:
                response = err  # an HTTPError is also a response: look at its status
            status = getattr(response, "status", None) or getattr(response, "code", None) or 200
            if status in _REDIRECT_CODES:
                location = _header(response, "Location")
                if not location:
                    raise OnlineError("The server redirected without saying where.")
                if hops == MAX_REDIRECTS:
                    raise OnlineError("The link redirects too many times.")
                current = _next_url(current, location)
                continue
            if status >= 400:
                raise _http_error(int(status), getattr(response, "headers", None), current)
            return _decode(_read_capped(response, max_bytes))
        except OnlineError:
            raise
        except urllib.error.URLError as err:
            raise _network_error(err) from None
        except (OSError, ValueError) as err:  # timeouts, TLS, resets, bad ports, ...
            raise _network_error(err) from None
        except Exception as err:  # http.client.HTTPException and friends
            raise OnlineError("The download failed.") from err
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                with contextlib.suppress(Exception):  # closing must never hide the real result
                    close()
    raise OnlineError("The link redirects too many times.")  # pragma: no cover


def fetch_text(
    url: str,
    *,
    max_bytes: int = MAX_BYTES,
    timeout: float = TIMEOUT,
    opener: Opener | None = None,
) -> str:
    """GET ``url`` and return its body as text. Raises ``OnlineError`` with a friendly message.

    ``opener(request, timeout)`` returns a response-like object (``status``, ``headers``,
    ``read(n)``); it exists so tests can inject responses. The default one is ``urlopen`` with
    redirects switched off (they are followed here, at most 3 times, never from https to http).
    """
    return _fetch(url, max_bytes=max_bytes, timeout=timeout, opener=opener, accept=None)


def fetch_entry(entry: OnlineEntry, *, opener: Opener | None = None) -> str:
    """The source text of ``entry``. It is not compiled, run or saved: it is only a string."""
    return fetch_text(entry.url, opener=opener)


def _fetch_json(url: str, opener: Opener | None, what: str) -> Any:
    text = _fetch(
        url,
        max_bytes=MAX_BYTES,
        timeout=TIMEOUT,
        opener=opener,
        accept="application/vnd.github+json" if "api.github.com" in url else "application/json",
    )
    try:
        return json.loads(text)
    except ValueError:
        raise OnlineError(f"{what} answered something that is not JSON.") from None


# --- resolving ------------------------------------------------------------------------------


def _py_entry(name: str, url: str, source: str, **extra: Any) -> OnlineEntry:
    return OnlineEntry(name=_clean_name(name), url=url, source=source, **extra)


def _size(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _github_segments(parts: Any) -> list[str]:
    path = parts.path.strip("/")
    segments = [unquote(s) for s in path.split("/") if s]
    if segments and segments[-1].lower().endswith(".git") and len(segments) == 2:
        segments[-1] = segments[-1][:-4]
    return segments


def _check_github_segments(segments: list[str]) -> None:
    if any(s in (".", "..") for s in segments):
        raise OnlineError("That GitHub link is not valid.")
    if not _GITHUB_NAME.match(segments[0]) or not _GITHUB_NAME.match(segments[1]):
        raise OnlineError("That GitHub link is not valid.")


def parse_github(url: str) -> tuple[str, dict[str, str]]:
    """Classify a GitHub-family link without touching the network.

    Returns ``(kind, info)`` where kind is ``"file"`` (``info["raw"]`` is the raw URL),
    ``"contents"`` (``info["api"]`` is the contents API URL), ``"gist"`` (``info["api"]`` is the
    gist API URL) or ``"other"`` (not a GitHub link; ``info`` is empty).
    """
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if host == "raw.githubusercontent.com":
        return ("file", {"raw": url}) if _path_is_py(url) else ("other", {})
    if host == "gist.github.com":
        segments = [unquote(s) for s in parts.path.split("/") if s]
        candidate = segments[1] if len(segments) >= 2 else (segments[0] if segments else "")
        if not _GIST_ID.match(candidate):
            raise OnlineError("That gist link is not valid. Use gist.github.com/<user>/<id>.")
        return "gist", {"api": f"https://api.github.com/gists/{candidate}"}
    if host != "github.com":
        return "other", {}
    segments = _github_segments(parts)
    if len(segments) < 2:
        raise OnlineError("Paste a link to a repository, a folder or a .py file on GitHub.")
    _check_github_segments(segments)
    owner, repo = segments[0], segments[1]
    mode = segments[2] if len(segments) > 2 else ""
    if mode in ("blob", "raw"):
        if len(segments) < 5:
            raise OnlineError("That GitHub link does not point to a file.")
        ref, path = segments[3], segments[4:]
        if not path[-1].lower().endswith(".py"):
            raise OnlineError("That GitHub file is not a .py file. Link to a .py file or to a folder.")
        raw = "https://raw.githubusercontent.com/" + "/".join(quote(s) for s in [owner, repo, ref, *path])
        return "file", {"raw": raw}
    if mode in ("", "tree"):
        ref = segments[3] if mode == "tree" and len(segments) > 3 else ""
        path = segments[4:] if mode == "tree" else []
        api = f"https://api.github.com/repos/{quote(owner)}/{quote(repo)}/contents"
        if path:
            api += "/" + "/".join(quote(s) for s in path)
        if ref:
            api += f"?ref={quote(ref, safe='')}"
        return "contents", {"api": api}
    raise OnlineError("Paste a link to a repository, a folder or a .py file on GitHub.")


def _entries_from_contents(data: Any, source: str) -> list[OnlineEntry]:
    if isinstance(data, dict) and data.get("type") == "file":
        data = [data]  # a link to one file through the folder syntax
    if not isinstance(data, list):
        message = data.get("message") if isinstance(data, dict) else None
        raise OnlineError(
            f"GitHub did not list that folder{f' ({_clean_description(message)})' if message else ''}."
        )
    entries: list[OnlineEntry] = []
    for item in data:
        if not isinstance(item, dict) or item.get("type") != "file":
            continue
        name = item.get("name")
        download = item.get("download_url")
        if not isinstance(name, str) or not name.lower().endswith(".py"):
            continue
        if not isinstance(download, str) or not _url_allowed(download):
            continue
        entries.append(_py_entry(name[:-3], download, source, size=_size(item.get("size"))))
    entries.sort(key=lambda e: e.name.lower())
    return entries[:MAX_LISTING_ENTRIES]


def _entries_from_gist(data: Any, source: str) -> list[OnlineEntry]:
    files = data.get("files") if isinstance(data, dict) else None
    if not isinstance(files, dict):
        raise OnlineError("GitHub did not return that gist.")
    description = _clean_description(data.get("description"))
    entries: list[OnlineEntry] = []
    for key, item in files.items():
        if not isinstance(item, dict):
            continue
        filename = item.get("filename") if isinstance(item.get("filename"), str) else key
        raw = item.get("raw_url")
        if not isinstance(filename, str) or not filename.lower().endswith(".py"):
            continue
        if not isinstance(raw, str) or not _url_allowed(raw):
            continue
        entries.append(
            _py_entry(filename[:-3], raw, source, description=description, size=_size(item.get("size")))
        )
    entries.sort(key=lambda e: e.name.lower())
    return entries[:MAX_LISTING_ENTRIES]


def _entries_from_manifest(data: Any, manifest_url: str, source: str) -> list[OnlineEntry]:
    if not isinstance(data, dict) or "format" not in data:
        raise OnlineError(
            "That link is not a .py file, a GitHub link or a preset manifest "
            '(a JSON file with "format": 1 and a "presets" list).'
        )
    version = data["format"]
    if version != MANIFEST_FORMAT or isinstance(version, bool):
        raise OnlineError(
            f"This preset list uses format {_clean(str(version), 20, '?')}; "
            f"this version of Manim Studio understands format {MANIFEST_FORMAT}."
        )
    presets = data.get("presets")
    if not isinstance(presets, list):
        raise OnlineError('The preset list has no "presets" list.')
    entries: list[OnlineEntry] = []
    for item in presets:
        if not isinstance(item, dict):
            continue
        file = item.get("file")
        if not isinstance(file, str) or not file.strip():
            continue
        url = urljoin(manifest_url, file.strip())
        if not _url_allowed(url) or not _path_is_py(url):
            continue
        name = item.get("name") if isinstance(item.get("name"), str) else _stem_of(url)
        kind = item.get("kind") if item.get("kind") in _KINDS else ""
        entries.append(
            _py_entry(
                name or _stem_of(url),
                url,
                source,
                kind_hint=kind,
                description=_clean_description(item.get("description")),
                size=_size(item.get("size")),
            )
        )
        if len(entries) >= MAX_MANIFEST_ENTRIES:
            break
    return entries


def resolve(url: str, *, opener: Opener | None = None) -> list[OnlineEntry]:
    """What the pasted link offers: a list of entries (never empty; ``OnlineError`` otherwise)."""
    source = (url or "").strip()
    if not source:
        raise OnlineError("Paste a link first.")
    _require_allowed(source)
    kind, info = parse_github(source)
    if kind == "file":
        entries = [_py_entry(_stem_of(info["raw"]), info["raw"], source)]
    elif kind == "contents":
        entries = _entries_from_contents(_fetch_json(info["api"], opener, "GitHub"), source)
        if not entries:
            raise OnlineError("No .py files were found there.")
    elif kind == "gist":
        entries = _entries_from_gist(_fetch_json(info["api"], opener, "GitHub"), source)
        if not entries:
            raise OnlineError("That gist has no .py files.")
    elif _path_is_py(source):
        entries = [_py_entry(_stem_of(source), source, source)]
    else:
        text = fetch_text(source, opener=opener)
        try:
            data = json.loads(text)
        except ValueError:
            raise OnlineError(
                "That link is not a .py file, a GitHub link or a preset manifest (JSON)."
            ) from None
        entries = _entries_from_manifest(data, source, source)
        if not entries:
            raise OnlineError("That preset list has no usable .py presets (https links to .py files).")
    return entries
