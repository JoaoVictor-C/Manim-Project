"""The HTML slide deck's page (ADR 0087): one self-contained HTML text built from a manifest.

A deck is ``<name>.html`` beside ``<name>_files/``, which holds per slide ``slide-NN.mp4`` (with its sound),
``slide-NN-end.png`` (the stop's frame) and, for a looping stop, ``slide-NN-loop.mp4`` (silent).
``render/slide_deck.py`` renders those files and describes them in a ``Deck``; ``page`` writes the page that
plays them: inline CSS and JavaScript, no external URL, so it opens from disk offline.

How the page plays (the same rules as present mode in the editor):

* it opens on a cover with the title and the number of slides; a click (or a key) starts it, because browsers
  allow sound only after a gesture;
* a slide plays, then waits on its end picture, or on its loop (muted, repeating) when its stop loops;
* **Next** (click, Right, Page Down, Space, Enter) while a slide plays shows its end picture at once (then its
  loop); while it waits, plays the next slide;
* **Previous** (Left, Page Up, Backspace) shows the previous slide's end picture, paused; Home goes back
  before the first slide, End to the last one's end; F toggles full screen;
* two ``<video>`` elements take turns: the next slide loads in the hidden one, and a layer is shown only once
  it can play, so nothing flashes black between slides. The picture is letterboxed on black, and a small
  "3 / 8" fades in and out when the slide changes.

Pure: no Qt, no Manim.
"""

from __future__ import annotations

import html
import json
from dataclasses import dataclass
from urllib.parse import quote


@dataclass(frozen=True)
class DeckSlide:
    index: int  # 1-based, as the files are numbered
    video: str  # relative URL of the slide's video, from the page
    end: str  # relative URL of its last frame, a PNG
    loop: str | None = None  # relative URL of its silent loop, when its stop loops
    stop: str = ""  # the stop marker's name


@dataclass(frozen=True)
class Deck:
    title: str
    width: int
    height: int
    slides: tuple[DeckSlide, ...]


def files_folder(stem: str) -> str:
    """The folder beside ``<stem>.html`` that holds its videos and pictures."""
    return f"{stem}_files"


def slide_file(number: int, kind: str = "") -> str:
    """``slide-03.mp4``, ``slide-03-end.png`` (``kind="end"``) or ``slide-03-loop.mp4`` (``kind="loop"``)."""
    suffix = ".png" if kind == "end" else ".mp4"
    return f"slide-{number:02d}{'-' + kind if kind else ''}{suffix}"


def deck_slide(folder: str, number: int, loops: bool, stop: str = "") -> DeckSlide:
    """Slide ``number``'s entry, its file names relative to the page (URL-quoted: a name may hold spaces)."""

    def url(kind: str = "") -> str:
        return quote(f"{folder}/{slide_file(number, kind)}", safe="/")

    return DeckSlide(number, url(), url("end"), url("loop") if loops else None, stop)


def _json_for_script(data: object) -> str:
    """JSON safe inside a ``<script>`` element: no ``<``, ``>`` or ``&`` that could end it."""
    text = json.dumps(data, ensure_ascii=True)
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def page(deck: Deck) -> str:
    """The deck's complete HTML page."""
    if not deck.slides:
        raise ValueError("a deck needs at least one slide")
    title = html.escape(deck.title or "Slides", quote=True)
    count = len(deck.slides)
    data = {
        "width": deck.width,
        "height": deck.height,
        "slides": [
            {"index": s.index, "video": s.video, "end": s.end, "loop": s.loop, "stop": s.stop}
            for s in deck.slides
        ],
    }
    return (
        _PAGE.replace("@TITLE@", title)
        .replace("@COUNT@", f"{count} slide{'s' if count != 1 else ''}")
        .replace("@DATA@", _json_for_script(data))
    )


_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>@TITLE@</title>
<style>
html, body { margin: 0; height: 100%; background: #000; overflow: hidden; }
body { font-family: system-ui, "Segoe UI", sans-serif; color: #f2f2f2; cursor: pointer; }
.layer { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: contain; background: #000;
  opacity: 0; }
.layer.on { opacity: 1; z-index: 1; }
#cover { position: absolute; inset: 0; z-index: 3; display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 12px; background: #000; text-align: center; }
#cover h1 { margin: 0; font-size: 2.6em; font-weight: 600; }
#cover .count { color: #a0a0a0; }
#cover .start { margin-top: 18px; padding: 10px 26px; border: 1px solid #f2f2f2; border-radius: 22px; }
#cover .keys { margin-top: 20px; color: #808080; font-size: 0.85em; }
#where { position: absolute; right: 18px; bottom: 14px; z-index: 2; padding: 4px 10px; border-radius: 12px;
  background: rgba(0, 0, 0, 0.55); color: #f2f2f2; font-size: 0.9em; opacity: 0;
  transition: opacity 0.6s; pointer-events: none; }
#where.on { opacity: 1; transition: opacity 0.15s; }
</style>
</head>
<body>
<video id="v0" class="layer" preload="auto" playsinline></video>
<video id="v1" class="layer" preload="auto" playsinline></video>
<img id="still" class="layer" alt="">
<div id="where"></div>
<div id="cover">
<h1>@TITLE@</h1>
<div class="count">@COUNT@</div>
<div class="start">Click to start</div>
<div class="keys">Next: click, &rarr;, Page Down, Space &middot; Previous: &larr;, Page Up &middot;
Full screen: F</div>
</div>
<script id="deck" type="application/json">@DATA@</script>
<script>
(function () {
  "use strict";
  var deck = JSON.parse(document.getElementById("deck").textContent);
  var S = deck.slides;
  var videos = [document.getElementById("v0"), document.getElementById("v1")];
  var still = document.getElementById("still");
  var cover = document.getElementById("cover");
  var where = document.getElementById("where");
  var state = "cover";  // cover, playing, waiting
  var cur = -1;  // the slide playing or waited on; -1: before the first
  var token = 0;  // a newer step makes the callbacks of older ones do nothing
  var shown = null;
  var fade = 0;

  function show(layer) {
    [videos[0], videos[1], still].forEach(function (el) { el.classList.toggle("on", el === layer); });
    if (shown && shown !== layer && shown.tagName === "VIDEO") { shown.pause(); }
    shown = layer;
  }
  function holding(src) {
    return videos.filter(function (v) { return v.dataset.src === src; })[0] || null;
  }
  function load(v, src) {
    if (v.dataset.src !== src) { v.dataset.src = src; v.src = src; v.load(); }
    return v;
  }
  function free() {  // a video element not on screen
    return videos[0] === shown ? videos[1] : videos[0];
  }
  function ready(v, mine, then) {
    function go() { if (mine === token) { then(); } }
    if (v.readyState >= 3) { go(); } else { v.addEventListener("canplay", go, { once: true }); }
  }
  function start(v) {
    var p = v.play();
    if (p && p.catch) { p.catch(function () { v.muted = true; v.play().catch(function () {}); }); }
  }
  function preload(i) {
    if (i < S.length && !holding(S[i].video)) { load(free(), S[i].video); }
  }
  function tell() {
    where.textContent = (cur + 1) + " / " + S.length;
    where.classList.add("on");
    clearTimeout(fade);
    fade = setTimeout(function () { where.classList.remove("on"); }, 1500);
  }
  function stillOf(i, mine, then) {
    if (still.dataset.src !== S[i].end) { still.dataset.src = S[i].end; still.src = S[i].end; }
    if (still.complete && still.naturalWidth) { then(); return; }
    still.addEventListener("load", function () { if (mine === token) { then(); } }, { once: true });
  }

  function play(i) {
    var mine = ++token;
    state = "playing"; cur = i; tell();
    var v = holding(S[i].video);
    if (!v) { v = load(free(), S[i].video); }
    v.loop = false; v.muted = false;
    v.onended = function () { if (mine === token) { wait(i, true); } };
    if (still.dataset.src !== S[i].end) { still.dataset.src = S[i].end; still.src = S[i].end; }
    ready(v, mine, function () {
      v.currentTime = 0;
      start(v);
      show(v);
      preload(i + 1);
    });
  }

  function wait(i, loops) {  // the end of slide i: its picture, then its loop
    var mine = ++token;
    state = "waiting"; cur = i;
    stillOf(i, mine, function () {
      show(still);
      if (!loops || !S[i].loop) { preload(i + 1); return; }
      var next = i + 1 < S.length ? holding(S[i + 1].video) : null;
      var v = holding(S[i].loop) || load(videos[0] === next ? videos[1] : videos[0], S[i].loop);
      v.onended = null; v.loop = true; v.muted = true;
      ready(v, mine, function () {
        v.currentTime = 0;
        start(v);
        show(v);
        preload(i + 1);
      });
    });
  }

  function before() {  // Home: paused on the first slide's first frame
    var mine = ++token;
    state = "waiting"; cur = -1; tell();
    var v = holding(S[0].video) || load(free(), S[0].video);
    v.onended = null;
    ready(v, mine, function () { v.pause(); v.currentTime = 0; show(v); });
  }

  function next() {
    if (state === "cover") { begin(); return; }
    if (state === "playing") { wait(cur, true); return; }
    if (cur + 1 < S.length) { play(cur + 1); }
  }
  function previous() {
    if (state === "cover") { return; }
    if (cur - 1 < 0) { before(); return; }
    wait(cur - 1, false); tell();
  }
  function last() {  // End: waiting at the last slide's end
    cover.style.display = "none";
    wait(S.length - 1, true); tell();
  }
  function begin() {
    cover.style.display = "none";
    play(0);
  }
  function fullscreen() {
    if (document.fullscreenElement) { document.exitFullscreen(); }
    else if (document.documentElement.requestFullscreen) { document.documentElement.requestFullscreen(); }
  }

  var NEXT = ["ArrowRight", "PageDown", " ", "Enter"];
  var PREVIOUS = ["ArrowLeft", "PageUp", "Backspace"];
  document.addEventListener("keydown", function (e) {
    if (e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) { return; }
    if (NEXT.indexOf(e.key) >= 0) { next(); }
    else if (PREVIOUS.indexOf(e.key) >= 0) { previous(); }
    else if (e.key === "Home") { if (state !== "cover") { before(); } }
    else if (e.key === "End") { last(); }
    else if (e.key === "f" || e.key === "F") { fullscreen(); }
    else { return; }
    e.preventDefault();
  });
  document.addEventListener("click", function () { next(); });
  load(videos[0], S[0].video);
})();
</script>
</body>
</html>
"""
