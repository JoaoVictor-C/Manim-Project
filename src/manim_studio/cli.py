"""Command line entry point: ``manim-studio render``, ``python``, ``import``, ``narrate`` and ``edit``."""

from __future__ import annotations

import argparse
import functools
import json
import sys
import time
from pathlib import Path

from pydantic import ValidationError

from . import lifeline
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
    render.add_argument(
        "--encoder",
        choices=("auto", "gpu", "cpu"),
        default="auto",
        help="what encodes the video: the graphics card (NVENC), the processor (x264), or auto: the card "
        "when it has one and the video is big enough to pay (default: auto; ADR 0065)",
    )
    render.add_argument(
        "--check",
        action="store_true",
        help="do not render: say what would be slow or would not work, and about how long (ADR 0066)",
    )
    render.add_argument(
        "--jobs",
        type=int,
        help="processes that draw frames side by side (default: as many as pay, by cores and free memory; "
        "1: this process alone; ADR 0065)",
    )
    render.add_argument(
        "--fresh",
        action="store_true",
        help="start again from the first frame: discard the segments an interrupted export of this project "
        "to this file left in OUTPUT_STEM.export (by default the export resumes from them; ADR 0081)",
    )
    render.add_argument(
        "--segment-seconds",
        type=float,
        default=10.0,
        help="a video of two segments or more is rendered in segments this long, so an interrupted export "
        "resumes (default: 10; ADR 0081)",
    )

    render.add_argument(
        "--deck",
        action="store_true",
        help="write an HTML slide deck instead of one video: OUTPUT.html and OUTPUT_files/ with a video "
        "per slide (cut at the slide stops), its last frame and its loop; --start and --end are ignored "
        "(ADR 0087)",
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

    narrate = sub.add_parser(
        "narrate",
        help="speak a project's subtitles with a voice and place the sounds at them (ADR 0060)",
    )
    narrate.add_argument("project", type=Path)
    narrate.add_argument(
        "-o", "--output", type=Path, help="the project file to write (default: the same file)"
    )
    narrate.add_argument("--voice", metavar="PROVIDER:VOICE", help="the voice (default: the project's)")
    narrate.add_argument("--rate", type=float, help="speaking speed, 1.0 is normal (default: the project's)")
    narrate.add_argument(
        "--all", action="store_true", help="speak every subtitle again, not only new and changed"
    )
    narrate.add_argument("--follow-speech", action="store_true", help="retime the subtitles to the speech")
    narrate.add_argument(
        "--pause", type=float, default=0.6, help="seconds between subtitles with --follow-speech"
    )
    narrate.add_argument(
        "--allow-online", action="store_true", help="let an online voice service receive the subtitle text"
    )
    narrate.add_argument("--script", type=Path, help="also write the narration as a plain text script")

    edit = sub.add_parser("edit", help="open the editor")
    edit.add_argument("project", type=Path, nargs="?")
    return parser


def main(argv: list[str] | None = None) -> int:
    lifeline.die_with_editor()  # the helper ends with the editor, whatever happens to it
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
    if args.command == "narrate":
        return _narrate(args)
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
            encoder=args.encoder,
            jobs=args.jobs,
            segment_seconds=args.segment_seconds,
        )
    except OptionsError as exc:
        return _fail(str(exc))
    return _render(
        args.project,
        args.output,
        args.cache_dir,
        args.progress,
        args.trust_code,
        options,
        args.check,
        args.fresh,
        args.deck,
    )


def _render(
    project_path: Path,
    output: Path,
    cache_dir: Path | None = None,
    mode: str = "text",
    trust_code: bool = False,
    options=None,
    check: bool = False,
    fresh: bool = False,
    deck: bool = False,
) -> int:
    from .core.engine import adapter
    from .core.model.schema import Project
    from .render import resume
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
    if check:
        return _check(project, output, options, trust_code)

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
    from .core.code import python_object

    if trust_code:  # Python objects run in this process (ADR 0051)
        python_object.trust_everything()
    warnings = _render_code_layers(
        sized, trust_code, mode, options.jobs
    )  # at the size being exported (ADR 0042)
    warnings += _untrusted_objects(sized)
    if deck:  # an HTML slide deck: a video per slide, made afresh (ADR 0087)
        from .render.slide_deck import export_deck

        export, pending = export_deck, None
    else:
        export = functools.partial(export_video, fresh=fresh)
        pending = (
            None if fresh else resume.pending(project, options, output, python_object.trusts_everything())
        )
    if pending is not None:  # an interrupted export of the same project and options (ADR 0081)
        text = f"Resuming: {pending.done} of {pending.total} segments already rendered"
        if mode == "json":
            _emit({"stage": text, "resumed": pending.done, "segments": pending.total})
        else:
            print(f"{text} (in {pending.work.name}; --fresh starts again)", flush=True)
    try:
        result = export(project, output, progress, options=options)
    except OSError as exc:
        return _fail(f"cannot write {output}: {exc.strerror or exc}")
    except KeyboardInterrupt:
        work = resume.work_dir(output)
        if work.is_dir():
            print(f"\nstopped; the finished segments are in {work}: run again to resume", file=sys.stderr)
        return 130
    warnings += [result.warning] if result.warning else []
    if mode == "json":
        for warning in warnings:
            _emit({"warning": warning})
        _emit({"how": result.how})
        _emit({"done": str(result.path)})
    else:
        print(f"\nwrote {result.path} ({result.how})")
        for warning in warnings:
            print(f"warning: {warning}", file=sys.stderr)
    log.info("rendered %s -> %s in %.1fs", project_path, result.path, time.perf_counter() - start)
    return 0


def _check(project, output: Path, options, trust_code: bool) -> int:
    """The export health report (ADR 0066), with the cost of a frame measured here; exit 1 on a problem."""
    from .core.engine import adapter
    from .processes import export_health

    seconds = export_health.measure(project, options)
    report = export_health.check(project, options, adapter.cache_dir(), output, trust_code, seconds)
    print(
        f"{report.frames} frames; about {export_health.clock(report.seconds)} before the frames are encoded"
    )
    for line in report.lines():
        print(line)
    return 1 if report.worst == export_health.PROBLEM else 0


def _python(project_path: Path, output: Path, scene: str | None, cache_dir: Path | None) -> int:
    """Write the project as Manim code: readable when it can be, exact otherwise (ADR 0031)."""
    from .core.engine.python_export import class_name, to_python
    from .core.model.schema import Project

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
    from .core.exchange.scene_import import import_scene, scene_classes
    from .processes.scene_recorder import RecordError, run_recorder

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


def _narrate(args: argparse.Namespace) -> int:
    """Speak the subtitles that need it and place the sounds (ADR 0060), without the editor. Exit code 0
    when every subtitle that needed speech has it, 1 when some failed, 2 when it cannot start."""
    from . import plugins
    from .core.editing import edits
    from .core.model.scene_length import grow_to_fit
    from .core.model.schema import Project, VoiceChoice
    from .core.sound import audio
    from .core.voice import narration, voice_cache
    from .processes.voice import run_job

    path: Path = args.project
    try:
        project = Project.model_validate_json(path.read_text(encoding="utf-8"))
    except OSError as exc:
        return _fail(f"cannot read {path}: {exc.strerror or exc}")
    except ValidationError as exc:
        return _fail(f"{path} is not a valid project:\n{exc}")
    providers = plugins.voice_providers()
    if args.voice or args.rate:
        base = project.voice or VoiceChoice(provider="", voice="")
        provider, _, voice = (args.voice or f"{base.provider}:{base.voice}").partition(":")
        if provider not in providers or not voice:
            return _fail(f"--voice wants PROVIDER:VOICE with a provider among {', '.join(sorted(providers))}")
        try:
            choice = VoiceChoice(provider=provider, voice=voice, rate=args.rate or base.rate)
        except ValidationError as exc:
            return _fail(f"--rate: {exc.errors()[0]['msg']}")
        project = edits.set_voice(project, choice).project
    plan = narration.plan(project, None, voice_cache.folder_for(path), only_missing=not args.all)
    for cue_id, why in plan.skipped.items():
        if why not in (narration.EMPTY, narration.NO_VOICE):
            print(f"  {cue_id}: {why}")
    if narration.NO_VOICE in plan.skipped.values():
        return _fail("some subtitles have no voice: pass --voice PROVIDER:VOICE or choose one in the editor")
    online = sorted({j.provider for j in plan.jobs if providers[j.provider].online})
    if online and not args.allow_online:
        return _fail(f"{', '.join(online)} sends the subtitle text over the internet: pass --allow-online")
    failed: dict[str, str] = {}
    done: set[str] = set()
    for provider in dict.fromkeys(j.provider for j in plan.jobs):
        jobs = [j for j in plan.jobs if j.provider == provider]
        first = {str(j.out): j for j in reversed(jobs)}  # one text per file: equal texts share it
        items = [
            {"id": j.cue_id, "text": j.text, "voice": j.voice, "rate": j.rate, "out": out}
            for out, j in first.items()
        ]
        outs = {j.cue_id: str(j.out) for j in first.values()}

        def show(message: dict, jobs=jobs, outs=outs) -> None:
            if "id" in message:
                for job in (j for j in jobs if str(j.out) == outs[message["id"]]):
                    if message["ok"]:
                        done.add(job.cue_id)
                    else:
                        failed[job.cue_id] = message["error"]
                print(
                    f"  {message['id']}: {'ok' if message['ok'] else 'FAILED: ' + message['error']}",
                    flush=True,
                )
            elif message.get("ok") is False:
                for job in jobs:
                    failed.setdefault(job.cue_id, str(message.get("error")))
                print(f"error: {message.get('error')}", file=sys.stderr)

        print(f"speaking {len(items)} text{'s' if len(items) != 1 else ''} with {provider}...", flush=True)
        run_job({"op": "speak", "provider": provider, "items": items}, show)
    spoken = []
    by_cue = {c.id: c for c in project.subtitles}
    for job in [*plan.cached, *plan.jobs]:
        if job.cue_id in failed or (job in plan.jobs and job.cue_id not in done):
            continue
        seconds = audio.probe(str(job.out))
        cue = by_cue.get(job.cue_id)
        if seconds and cue is not None and narration.key_for(project, cue) == job.key:
            spoken.append(narration.Spoken(job.cue_id, job.key, job.out, seconds))
    if spoken:
        project = grow_to_fit(
            narration.place(project, spoken, follow=args.follow_speech, pause=args.pause).project
        )
    output = args.output or path
    try:
        output.write_text(project.model_dump_json(by_alias=True, indent=2), encoding="utf-8")
        if args.script:
            args.script.write_text(narration.script(project), encoding="utf-8")
    except OSError as exc:
        return _fail(f"cannot write {exc.filename}: {exc.strerror or exc}")
    print(f"wrote {output}: {len(spoken)} sound(s) placed, {len(failed)} failed")
    return 1 if failed else 0


def _render_code_layers(project, trust_code: bool, mode: str, jobs: int | None = None) -> list[str]:
    """Render code layers missing from the cache (ADR 0019); warnings for those left as placeholders.

    Layers are independent, so several are rendered at once, in runner processes (``jobs`` as for the frames;
    ADR 0065); one layer, or ``jobs`` 1, is rendered here as before. Layers with the same code render once."""
    import threading

    from .core.code import helpers
    from .core.engine import adapter
    from .core.engine.evaluator import Evaluator
    from .core.model.schema import CODE_TYPES
    from .processes import code_batch
    from .processes.code_runner import CodeError, Job, render_code

    evaluator = Evaluator(project)
    canvas, warnings = project.canvas, []
    # A code layer runs only with --trust-code, which trusts the helpers too (ADR 0058).
    pairs = tuple(sorted(helpers.sources(project).items()))
    trusted = tuple(name for name, _ in pairs)
    todo: dict[str, tuple[str, Job]] = {}  # cache key -> (the first layer with that code, its job)
    sharing: dict[str, list[str]] = {}  # cache key -> every layer with that code
    for layer in project.layers:
        if layer.spec is None or layer.spec.type not in CODE_TYPES:
            continue
        key = evaluator.code_key(layer)
        if evaluator.code_cache.has(key):
            continue
        if not trust_code:
            warnings.append(f"code layer {layer.id!r} is not rendered (pass --trust-code to run its code)")
            continue
        sharing.setdefault(key, []).append(layer.id)
        if key in todo:
            continue
        code = str(layer.spec.params.get("code", ""))
        todo[key] = (
            layer.id,
            Job(
                key,
                code,
                canvas.width_px,
                canvas.height_px,
                canvas.fps,
                canvas.frame_height,
                pairs,
                trusted,
                int(layer.spec.params.get("start_frame", 0) or 0),
                (float(t) if (t := layer.spec.params.get("start_time")) is not None else None),
            ),
        )
    announced, say = [0], threading.Lock()

    def announce(layer_id: str) -> None:
        with say:  # layers start in several threads: one line at a time
            announced[0] += 1
            if mode == "text":
                print(f"rendering code layer {layer_id}...", flush=True)
            else:
                _emit({"stage": f"Rendering code layer {layer_id} ({announced[0]} of {len(todo)})"})

    workers = code_batch.plan(jobs, len(todo))
    failures: dict[str, CodeError] = {}
    if workers > 1:
        failures = code_batch.render_all(list(todo.values()), adapter.cache_dir(), workers, announce)
    else:
        for layer_id, job in todo.values():
            announce(layer_id)
            try:
                render_code(job, evaluator.code_cache)
            except CodeError as error:
                failures[layer_id] = error
    for key, (layer_id, _) in todo.items():
        error = failures.get(layer_id)
        if error is None:
            continue
        where = f" (line {error.line})" if error.line else ""
        if error.frame:
            where = (
                where[:-1] + f", after {error.frame / canvas.fps:.1f} s)"
                if where
                else f" (after {error.frame / canvas.fps:.1f} s)"
            )
        if error.where != "code":
            at = f", line {error.helper_line}" if error.helper_line else ""
            where = f" (in helper {error.where.removeprefix('helper:')}{at})"
        warnings += [f"code layer {name!r} failed{where}: {error}" for name in sharing[key]]
    return warnings


def _untrusted_objects(project) -> list[str]:
    """Warnings for Python objects whose code may not run here (ADR 0051): they draw a placeholder;
    so do those importing a helper that may not run (ADR 0058)."""
    from .core.code import helpers, python_object
    from .core.model.schema import PYTHON_TYPES

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
