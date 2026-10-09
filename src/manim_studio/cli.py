"""Command line entry point: ``manim-studio render`` and ``manim-studio edit``."""

from __future__ import annotations

import argparse
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
    return _render(args.project, args.output)


def _render(project_path: Path, output: Path) -> int:
    from .core import adapter
    from .core.schema import Project
    from .render.cairo_export import export_video

    try:
        project = Project.model_validate_json(project_path.read_text(encoding="utf-8"))
    except OSError as exc:
        return _fail(f"cannot read {project_path}: {exc.strerror or exc}")
    except ValidationError as exc:
        return _fail(f"{project_path} is not a valid project:\n{exc}")
    adapter.configure(project_path.resolve().parent / ".cache" / "manim")

    def progress(done: int, total: int) -> None:
        print(f"\rframe {done}/{total}", end="", flush=True)

    start = time.perf_counter()
    export_video(project, output, progress)
    print(f"\nwrote {output}")
    log.info("rendered %s -> %s in %.1fs", project_path, output, time.perf_counter() - start)
    return 0


def _fail(message: str) -> int:
    """User errors: one readable message on stderr and exit code 2, no traceback."""
    log.info("user error: %s", message)  # the console already shows it via stderr
    print(f"error: {message}", file=sys.stderr)
    return 2
