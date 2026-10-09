"""Command line entry point: ``manim-studio render`` and ``manim-studio edit``."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from pydantic import ValidationError

from .logging_config import get_logger, setup_logging

log = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="manim-studio")
    parser.add_argument("-v", "--verbose", action="count", default=0, help="-v info, -vv debug")
    sub = parser.add_subparsers(dest="command", required=True)

    render = sub.add_parser("render", help="render a project.json to a video")
    render.add_argument("project", type=Path)
    render.add_argument("output", type=Path)
    render.add_argument("--cache-dir", type=Path, help="Manim's cache (default: PROJECT_DIR/.cache/manim)")
    render.add_argument(
        "--progress", choices=("text", "json"), default="text", help="json: one flushed JSON object per line"
    )

    edit = sub.add_parser("edit", help="open the editor")
    edit.add_argument("project", type=Path, nargs="?")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    log_file = setup_logging(args.verbose)
    log.debug("command=%s log_file=%s", args.command, log_file)

    if args.command == "edit":
        from .ui.main_window import run

        return run([sys.argv[0]] + ([str(args.project)] if args.project else []))
    return _render(args.project, args.output, args.cache_dir, args.progress)


def _render(project_path: Path, output: Path, cache_dir: Path | None = None, mode: str = "text") -> int:
    from .core import adapter
    from .core.schema import Project
    from .render.cairo_export import export_video

    try:
        project = Project.model_validate_json(project_path.read_text(encoding="utf-8"))
    except OSError as exc:
        return _fail(f"cannot read {project_path}: {exc.strerror or exc}")
    except ValidationError as exc:
        return _fail(f"{project_path} is not a valid project:\n{exc}")
    adapter.configure(cache_dir or project_path.resolve().parent / ".cache" / "manim")

    def progress(done: int, total: int) -> None:
        if mode == "json":
            _emit({"frame": done, "total": total})
        else:
            print(f"\rframe {done}/{total}", end="", flush=True)

    start = time.perf_counter()
    try:
        result = export_video(project, output, progress)
    except OSError as exc:
        return _fail(f"cannot write {output}: {exc.strerror or exc}")
    if mode == "json":
        if result.warning:
            _emit({"warning": result.warning})
        _emit({"done": str(result.path)})
    else:
        print(f"\nwrote {result.path}")
        if result.warning:
            print(f"warning: {result.warning}", file=sys.stderr)
    log.info("rendered %s -> %s in %.1fs", project_path, result.path, time.perf_counter() - start)
    return 0


def _emit(message: dict) -> None:
    """One JSON object per line, flushed: a reader on a pipe sees it at once (ADR 0017)."""
    print(json.dumps(message), flush=True)


def _fail(message: str) -> int:
    """User errors: one readable message on stderr and exit code 2, no traceback."""
    log.info("user error: %s", message)  # the console already shows it via stderr
    print(f"error: {message}", file=sys.stderr)
    return 2
