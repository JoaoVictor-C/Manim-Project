"""Command line entry point: ``manim-studio render``, ``python`` and ``edit``."""

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
    render.add_argument(
        "--trust-code",
        action="store_true",
        help="render code layers that are not cached yet (runs the project's Python code; ADR 0019)",
    )

    python = sub.add_parser("python", help="write a project.json as a Manim scene file (ADR 0031)")
    python.add_argument("project", type=Path)
    python.add_argument("output", type=Path)
    python.add_argument("--scene", help="the scene class name (default: from the output file's name)")
    python.add_argument("--cache-dir", type=Path, help="the editor's cache: code layers' frames (exact form)")

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
    if args.command == "python":
        return _python(args.project, args.output, args.scene, args.cache_dir)
    return _render(args.project, args.output, args.cache_dir, args.progress, args.trust_code)


def _render(
    project_path: Path,
    output: Path,
    cache_dir: Path | None = None,
    mode: str = "text",
    trust_code: bool = False,
) -> int:
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
    warnings = _render_code_layers(project, trust_code, mode)
    try:
        result = export_video(project, output, progress)
    except OSError as exc:
        return _fail(f"cannot write {output}: {exc.strerror or exc}")
    warnings += [result.warning] if result.warning else []
    if mode == "json":
        for warning in warnings:
            _emit({"warning": warning})
        _emit({"done": str(result.path)})
    else:
        print(f"\nwrote {result.path}")
        for warning in warnings:
            print(f"warning: {warning}", file=sys.stderr)
    log.info("rendered %s -> %s in %.1fs", project_path, result.path, time.perf_counter() - start)
    return 0


def _python(project_path: Path, output: Path, scene: str | None, cache_dir: Path | None) -> int:
    """Write the project as Manim code: readable when it can be, exact otherwise (ADR 0031)."""
    from .core.python_export import class_name, to_python
    from .core.schema import Project

    try:
        project = Project.model_validate_json(project_path.read_text(encoding="utf-8"))
    except OSError as exc:
        return _fail(f"cannot read {project_path}: {exc.strerror or exc}")
    except ValidationError as exc:
        return _fail(f"{project_path} is not a valid project:\n{exc}")
    code_dir = (cache_dir or project_path.resolve().parent / ".cache" / "manim") / "code"
    export = to_python(project, scene or class_name(output.stem), str(code_dir))
    try:
        output.write_text(export.code, encoding="utf-8")
    except OSError as exc:
        return _fail(f"cannot write {output}: {exc.strerror or exc}")
    print(f"wrote {output} ({'readable' if export.readable else 'exact'})")
    for problem in export.problems:
        print(f"  exact because: {problem}")
    return 0


def _render_code_layers(project, trust_code: bool, mode: str) -> list[str]:
    """Render code layers missing from the cache (ADR 0019); warnings for those left as placeholders."""
    from .code_runner import CodeError, Job, render_code
    from .core.evaluator import Evaluator
    from .core.schema import CODE_TYPES

    evaluator = Evaluator(project)
    canvas, warnings = project.canvas, []
    for layer in project.layers:
        if layer.spec is None or layer.spec.type not in CODE_TYPES:
            continue
        key = evaluator.code_key(layer)
        if evaluator.code_cache.has(key):
            continue
        if not trust_code:
            warnings.append(f"code layer {layer.id!r} is not rendered (pass --trust-code to run its code)")
            continue
        if mode == "text":
            print(f"rendering code layer {layer.id}...", flush=True)
        code = str(layer.spec.params.get("code", ""))
        job = Job(key, code, canvas.width_px, canvas.height_px, canvas.fps, canvas.frame_height)
        try:
            render_code(job, evaluator.code_cache)
        except CodeError as error:
            where = f" (line {error.line})" if error.line else ""
            warnings.append(f"code layer {layer.id!r} failed{where}: {error}")
    return warnings


def _emit(message: dict) -> None:
    """One JSON object per line, flushed: a reader on a pipe sees it at once (ADR 0017)."""
    print(json.dumps(message), flush=True)


def _fail(message: str) -> int:
    """User errors: one readable message on stderr and exit code 2, no traceback."""
    log.info("user error: %s", message)  # the console already shows it via stderr
    print(f"error: {message}", file=sys.stderr)
    return 2
