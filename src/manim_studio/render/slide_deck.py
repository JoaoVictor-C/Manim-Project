"""Export the HTML slide deck (ADR 0087): one video per slide, its end picture, a silent loop, and the page.

``export_deck(project, talk.html)`` cuts the scene into slides with ``core.editing.slides.windows`` on the
export's frame grid (``options.fps`` or the canvas's) and, per slide ``NN``, writes into ``talk_files/``:

* ``slide-NN.mp4`` - the slide's frames with the sound under them (``export_video`` of its window);
* ``slide-NN-end.png`` - the video's own last frame, decoded from it, so the picture the page shows while it
  waits is exactly the one the video stopped on;
* ``slide-NN-loop.mp4`` - for a looping stop, the frames of ``loop_window`` with no sound.

The page is written by ``core.exchange.slide_deck.page``. Everything is made in a work folder beside the page
(``<stem>.deck-partial``) and an existing deck is replaced only once the new one is complete (as videos are,
ADR 0017); if the old deck's folder cannot be moved (a video open in a browser on Windows), the new deck is
saved as ``<stem> (n).html``. Progress counts the frames of every window together.
"""

from __future__ import annotations

import contextlib
import dataclasses
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

import av

from ..core.editing.slides import loop_window, windows
from ..core.exchange.slide_deck import Deck, deck_slide, files_folder, page, slide_file
from ..core.model.schema import Project
from ..logging_config import get_logger
from .cairo_export import export_video
from .options import RenderOptions, apply_options

log = get_logger(__name__)

WORK_SUFFIX = ".deck-partial"
OLD_SUFFIX = ".deck-old"


@dataclass(frozen=True)
class DeckExported:
    path: Path  # the page (the requested path, unless the old deck was in use)
    warning: str | None = None
    how: str = ""  # "3 slides; CPU (x264)"
    slides: int = 0


def work_folder(out_html: Path) -> Path:
    """Where a deck is made until it is complete: ``<stem>.deck-partial`` beside the page."""
    out_html = Path(out_html)
    return out_html.with_name(f"{out_html.stem}{WORK_SUFFIX}")


def export_deck(
    project: Project,
    out_html: Path,
    progress=None,
    options: RenderOptions | None = None,
    title: str | None = None,
) -> DeckExported:
    """Render ``project`` as an HTML slide deck at ``out_html`` (see the module's docstring).

    ``options`` give the size, fps, quality, subtitles, encoder and processes; their range is ignored (a deck
    is the whole scene). Subtitles are burned in or left out: a deck has no ``.srt``.
    """
    options = options or RenderOptions()  # each window sets its own range
    out_html = Path(out_html)
    if out_html.is_dir():
        raise IsADirectoryError(f"{out_html} is a folder, not a page")
    fps = options.fps or project.canvas.fps
    slides = windows(project, fps)
    silent = project.model_copy(update={"audio": []})  # the loops play while the speaker talks
    loops = {slide.index: loop_window(slide) for slide in slides}
    total = sum(s.frames for s in slides) + sum(b - a for a, b in filter(None, loops.values()))
    canvas = apply_options(project, options).canvas

    work = work_folder(out_html)
    shutil.rmtree(work, ignore_errors=True)
    files = work / "files"
    files.mkdir(parents=True)
    done = 0
    how = ""

    def window(source: Project, path: Path, first: int, last: int) -> str:
        nonlocal done
        base = done

        def report(k: int, _total: int) -> None:
            if progress:
                progress(base + k, total)

        ranged = dataclasses.replace(options, start=first / fps, end=last / fps)
        result = export_video(source, path, report, replace_timeout=0.0, options=ranged)
        path.with_suffix(".srt").unlink(missing_ok=True)  # the deck plays no .srt
        done = base + (last - first)
        return result.how

    try:
        entries = []
        for slide in slides:
            number = slide.index + 1
            video = files / slide_file(number)
            how = window(project, video, slide.first, slide.last) or how
            _end_picture(video, files / slide_file(number, "end"))
            loop = loops[slide.index]
            if loop is not None:
                window(silent, files / slide_file(number, "loop"), *loop)
            entries.append((number, loop is not None, slide.stop.name if slide.stop else ""))
        path, warning = _publish(work, files, out_html)
        folder = files_folder(path.stem)
        deck = Deck(
            title=title if title is not None else out_html.stem,
            width=canvas.width_px,
            height=canvas.height_px,
            slides=tuple(deck_slide(folder, n, looping, stop) for n, looping, stop in entries),
        )
        partial = path.with_name(f"{path.stem}.partial.html")
        partial.write_text(page(deck), encoding="utf-8")
        os.replace(partial, path)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    count = len(slides)
    log.info("deck %s: %d slides, %d frames", path, count, total)
    return DeckExported(path, warning, f"{count} slide{'s' if count != 1 else ''}; {how}", count)


def _end_picture(video: Path, out_png: Path) -> None:
    """The last frame of ``video`` as a PNG."""
    last = None
    with av.open(str(video)) as container:
        for frame in container.decode(video=0):
            last = frame
    if last is None:
        raise RuntimeError(f"{video.name} has no frames")
    picture = last.reformat(format="rgb24")
    with av.open(str(out_png), mode="w", format="image2", options={"update": "1"}) as out:
        stream = out.add_stream("png")
        stream.width, stream.height, stream.pix_fmt = picture.width, picture.height, "rgb24"
        out.mux(stream.encode(picture))
        out.mux(stream.encode())


def _publish(work: Path, files: Path, out_html: Path) -> tuple[Path, str | None]:
    """Move the finished ``files`` to ``<stem>_files`` beside ``out_html``, the old deck's folder out of the
    way first (removed once the new one is in place). Returns the page's path, which is ``<stem> (n).html``
    when the old folder is in use, and a warning saying so."""
    target = out_html.with_name(files_folder(out_html.stem))
    if target.exists():
        old = work.with_name(f"{out_html.stem}{OLD_SUFFIX}")
        shutil.rmtree(old, ignore_errors=True)
        try:
            os.replace(target, old)
        except PermissionError:
            n = 2
            while (alt := out_html.with_name(f"{out_html.stem} ({n}).html")).exists() or alt.with_name(
                files_folder(alt.stem)
            ).exists():
                n += 1
            os.replace(files, alt.with_name(files_folder(alt.stem)))
            log.warning("%s is in use; saved the deck as %s", target, alt)
            return alt, f"{target.name} is in use (open in a browser?); saved the deck as {alt.name}"
        os.replace(files, target)
        with contextlib.suppress(OSError):
            shutil.rmtree(old)
    else:
        os.replace(files, target)
    return out_html, None
