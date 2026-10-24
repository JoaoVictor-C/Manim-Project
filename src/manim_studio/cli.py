"""Command line entry point: ``manim-studio render``, ``python``, ``import`` and ``edit``."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from pydantic import ValidationError

from .logging_config import get_logger, setup_logging

log = get_logger(__name__)


def version_text() -> str:
    """``manim-studio --version``: this package's version and the Manim it is pinned to (P6e)."""
    from importlib.metadata import PackageNotFoundError, version

    from . import __version__

    try:
        manim = version("manim")
    except PackageNotFoundError:  # pragma: no cover - manim is a hard dependency
        manim = "missing"
    return f"manim-studio {__version__} (Manim {manim}, Python {sys.version.split()[0]})"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="manim-studio")
    parser.add_argument("-v", "--verbose", action="count", default=0, help="-v info, -vv debug")
    parser.add_argument("--version", action="version", version=version_text())
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
        help="run the project's Python code: code layers not cached yet, and Python objects and "
        "helpers not in the trusted store (ADR 0019, 0051, 0058)",
    )
    render.add_argument("--size", metavar="WxH", help="video size in pixels (default: the project's canvas)")
    render.add_argument("--fps", type=int, help="frames per second (default: the project's canvas)")
    render.add_argument("--start", type=float, default=0.0, help="first second to render (default: 0)")
    render.add_argument("--end", type=float, help="end of the range, in seconds (default: the scene's end)")
    render.add_argument("--crf", type=int, default=18, help="H.264 quality, 0 best to 51 worst (default: 18)")
    render.add_argument(
        "--subtitles",
        choices=("burn", "srt", "none"),
        help="burn: drawn in the video and an .srt beside it; srt: only the .srt; none: neither "
        "(default: as the project)",
    )

    python = sub.add_parser("python", help="write a project.json as a Manim scene file (ADR 0031)")
    python.add_argument("project", type=Path)
    python.add_argument("output", type=Path)
    python.add_argument("--scene", help="the scene class name (default: from the output file's name)")
    python.add_argument("--cache-dir", type=Path, help="the editor's cache: code layers' frames (exact form)")

    scene_import = sub.add_parser(
        "import",
        help="turn a Manim scene file into a project: layers and clips, or one code layer (ADR 0053)",
    )
    scene_import.add_argument("file", type=Path, help="the Python file with the scene")
    scene_import.add_argument("-o", "--output", type=Path, required=True, help="the project file to write")
    scene_import.add_argument("--scene", help="the scene class (needed when the file has several)")
    scene_import.add_argument("--cache-dir", type=Path, help="Manim's cache (default: FILE_DIR/.cache/manim)")

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
    if args.command == "import":
        return _import(args.file, args.output, args.scene, args.cache_dir)
    if args.command == "python":
        return _python(args.project, args.output, args.scene, args.cache_dir)
    from .render.options import OptionsError, RenderOptions, parse_size

    try:
        size = parse_size(args.size) if args.size else (None, None)
        options = RenderOptions(
            width=size[0],
            height=size[1],
            fps=args.fps,
            start=args.start,
            end=args.end,
            crf=args.crf,
            subtitles=args.subtitles,
        )
    except OptionsError as exc:
        return _fail(str(exc))
    return _render(args.project, args.output, args.cache_dir, args.progress, args.trust_code, options)


def _render(
    project_path: Path,
    output: Path,
    cache_dir: Path | None = None,
    mode: str = "text",
    trust_code: bool = False,
    options=None,
) -> int:
    from .core import adapter
    from .core.schema import Project
    from .render.cairo_export import export_video
    from .render.options import OptionsError, RenderOptions, apply_options, frame_window

    options = options or RenderOptions()

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
        sized = apply_options(project, options)
        frame_window(sized.canvas, options)  # a bad range is refused before any code runs
    except OptionsError as exc:
        return _fail(str(exc))
    if trust_code:  # Python objects run in this process (ADR 0051)
        from .core import python_object

        python_object.trust_everything()
    warnings = _render_code_layers(sized, trust_code, mode)  # at the size being exported (ADR 0042)
    warnings += _untrusted_objects(sized)
    try:
        result = export_video(project, output, progress, options=options)
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


def _import(path: Path, output: Path, scene: str | None, cache_dir: Path | None) -> int:
    """Run a Manim scene once in another process and write it as a project (ADR 0053): its objects
    as layers and clips, or the whole scene as one code layer with the reasons. Prints the report;
    exit code 0 either way, 2 when the scene cannot be run."""
    from .core.scene_import import import_scene, scene_classes
    from .scene_recorder import RecordError, run_recorder

    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return _fail(f"cannot read {path}: {exc}")
    scenes = scene_classes(source)
    if scene is None and len(scenes) > 1:
        return _fail(f"{path.name} has several scenes: choose one with --scene ({', '.join(scenes)})")
    started = time.perf_counter()
    try:
        recording = run_recorder(path, scene, cache_dir or path.resolve().parent / ".cache" / "manim")
    except RecordError as exc:
        where = f" (line {exc.line})" if exc.line else ""
        return _fail(f"{path.name}{where}: {exc}")
    try:
        result = import_scene(recording, source)
    except ValueError as exc:  # a code layer cannot hold it either
        return _fail(str(exc))
    try:
        output.write_text(result.project.model_dump_json(by_alias=True, indent=1), encoding="utf-8")
    except OSError as exc:
        return _fail(f"cannot write {output}: {exc.strerror or exc}")
    for line in result.report:
        print(line)
    print(f"wrote {output} in {time.perf_counter() - started:.1f} s")
    return 0


def _render_code_layers(project, trust_code: bool, mode: str) -> list[str]:
    """Render code layers missing from the cache (ADR 0019); warnings for those left as placeholders."""
    from .code_runner import CodeError, Job, render_code
    from .core import helpers
    from .core.evaluator import Evaluator
    from .core.schema import CODE_TYPES

    evaluator = Evaluator(project)
    canvas, warnings = project.canvas, []
    # A code layer runs only with --trust-code, which trusts the helpers too (ADR 0058).
    pairs = tuple(sorted(helpers.sources(project).items()))
    trusted = tuple(name for name, _ in pairs)
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
        job = Job(
            key, code, canvas.width_px, canvas.height_px, canvas.fps, canvas.frame_height, pairs, trusted
        )
        try:
            render_code(job, evaluator.code_cache)
        except CodeError as error:
            where = f" (line {error.line})" if error.line else ""
            if error.where != "code":
                at = f", line {error.helper_line}" if error.helper_line else ""
                where = f" (in helper {error.where.removeprefix('helper:')}{at})"
            warnings.append(f"code layer {layer.id!r} failed{where}: {error}")
    return warnings


def _untrusted_objects(project) -> list[str]:
    """Warnings for Python objects whose code may not run here (ADR 0051): they draw a placeholder;
    so do those importing a helper that may not run (ADR 0058)."""
    from .core import helpers, python_object
    from .core.schema import PYTHON_TYPES

    out = [
        f"Python object {layer.id!r} is drawn as a placeholder (pass --trust-code to run its code)"
        for layer in project.layers
        if layer.spec is not None
        and layer.spec.type in PYTHON_TYPES
        and not python_object.is_trusted(str(layer.spec.params.get("code", "")))
    ]
    used = {
        name
        for layer in project.layers
        if layer.spec is not None and layer.spec.type in PYTHON_TYPES
        for name in helpers.needed(project, str(layer.spec.params.get("code", "")))
    }
    out += [
        f"helper {helper.name!r} is not trusted: Python objects importing it are drawn as a placeholder "
        "(pass --trust-code to run its code)"
        for helper in project.helpers
        if helper.name in used and not python_object.is_trusted(helper.code)
    ]
    return out


def _emit(message: dict) -> None:
    """One JSON object per line, flushed: a reader on a pipe sees it at once (ADR 0017)."""
    print(json.dumps(message), flush=True)


def _fail(message: str) -> int:
    """User errors: one readable message on stderr and exit code 2, no traceback."""
    log.info("user error: %s", message)  # the console already shows it via stderr
    print(f"error: {message}", file=sys.stderr)
    return 2
