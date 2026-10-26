"""Where a long scene can be cut into independent chapters (ADR 0061).

A code layer plays one ``Scene`` from start to end, so any edit renders all of it. Many scenes are a sequence
of phases: something appears, plays, and is removed before the next phase. Such a scene can be rendered as
**chapters**: each chapter is the scene's setup plus its own statements, started at the frame where the whole
scene reached the same point. A cut between two top-level statements of ``construct`` is valid when

1. **the picture is back to its baseline** - what is drawn at the cut equals what was drawn right after the
   setup (the *prelude*, the statements before the first frame), with the same camera and the same updaters on
   visible things (a *probe* recorded by the renderer, ``scene_probe``);
2. **nothing invisible can move it** - no updater of an invisible object (a tracker) reaches a visible one;
3. **no later statement needs an earlier chapter's work** - no name a later statement reads was defined, or
   changed, by a statement between the prelude and the cut (a name defined again before it is read does not
   count), and no earlier statement changed the scene itself (camera, background, configuration).

The static half (3) is read from the code with ``ast`` and is deliberately conservative: an object variable
made in the prelude counts as changed by any statement that uses it, because animations change what they are
given. The dynamic half (1, 2) comes from the probes. Neither is trusted alone: a split is always compared
with the full render (``scene_split``). Pure: ``ast`` and the standard library only.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any

# Calls on ``self`` that act on the scene's mobjects: the probes see their effect (no hidden state).
SCENE_METHODS = frozenset(
    {
        "play", "wait", "add", "remove", "clear", "bring_to_front", "bring_to_back", "add_foreground_mobject",
        "remove_foreground_mobject", "add_sound", "wait_until", "next_section", "pause", "update_self",
    }
)  # fmt: skip
MUTATORS = frozenset(
    {
        "append", "extend", "insert", "remove", "pop", "clear", "update", "add", "discard", "setdefault",
        "sort", "reverse", "popitem", "appendleft", "extendleft",
    }
)  # fmt: skip
PURE_METHODS = frozenset({"copy", "keys", "values", "items", "count", "index", "join", "format"})
MIN_CHAPTER_SECONDS = 1.0


@dataclass(frozen=True)
class Statement:
    index: int
    first_line: int
    last_line: int
    text: str  # the first line, trimmed
    defines: frozenset[str]
    reads: frozenset[str]
    touches: frozenset[
        str
    ]  # names whose value this statement may change (calls on them, passed as arguments)
    scene_state: bool = False  # sets something about the scene itself (camera, configuration)
    kills: frozenset[str] = frozenset()  # defined here without being read here (the old value is dead)


@dataclass(frozen=True)
class Cut:
    stmt: int  # the cut is before this statement
    frame: int
    time: float
    ok: bool
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class Chapter:
    first: int  # statements [first, end)
    end: int
    start_frame: int
    end_frame: int | None  # None: to the end of the scene
    start_time: float = 0.0  # the whole scene's clock at start_frame, exactly

    @property
    def frames(self) -> int | None:
        return None if self.end_frame is None else self.end_frame - self.start_frame


@dataclass
class Analysis:
    class_name: str = ""
    ok: bool = False  # the code could be analysed at all
    problem: str = ""
    statements: list[Statement] = field(default_factory=list)
    prelude_end: int = 0  # statements [0, prelude_end) run before the first frame
    first_animated: int = 0
    total_frames: int = 0
    fps: int = 0
    cuts: list[Cut] = field(default_factory=list)  # every boundary after the prelude, with the verdict
    chapters: list[Chapter] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def splittable(self) -> bool:
        return len(self.chapters) > 1

    def report(self) -> str:
        """The read-only report shown by Analyse scene."""
        if not self.ok:
            return f"This scene cannot be analysed: {self.problem}"
        lines = [
            f"Scene {self.class_name}: {len(self.statements)} statements in construct, "
            f"{self.total_frames} frames."
        ]
        lines += self.notes
        if self.first_animated >= len(self.statements) or not self.total_frames:
            lines.append("Nothing plays before the end of the setup: there is nothing to cut.")
            return "\n".join(lines)
        lines.append(f"Setup: statements 1-{self.first_animated} (they run in every chapter).")
        if not self.splittable:
            lines.append("No valid cut point: the scene is one chapter.")
        else:
            lines.append(f"{len(self.chapters)} chapters:")
            for n, chapter in enumerate(self.chapters, 1):
                span = (
                    f"frames {chapter.start_frame}-{chapter.end_frame}"
                    if chapter.end_frame is not None
                    else f"frames {chapter.start_frame}-end"
                )
                share = ""
                if chapter.frames is not None and self.total_frames:
                    share = f" ({100 * chapter.frames / self.total_frames:.0f}% of the scene)"
                elif self.total_frames:
                    rest = self.total_frames - chapter.start_frame
                    share = f" ({100 * rest / self.total_frames:.0f}% of the scene)"
                first = self.statements[chapter.first].first_line
                lines.append(
                    f"  {n}. statements {chapter.first + 1}-{chapter.end}, line {first}, {span}{share}"
                )
            biggest = max(
                (c.frames if c.frames is not None else self.total_frames - c.start_frame)
                for c in self.chapters
            )
            share = 100 * biggest / self.total_frames
            lines.append(f"Editing one chapter re-renders at most {share:.0f}% of the scene.")
            if share >= 90:
                lines.append("That saves little: one chapter holds nearly the whole scene.")
        refused = [c for c in self.cuts if not c.ok]
        if refused:
            lines.append("Boundaries that are not cut points:")
            for cut in refused[:12]:
                lines.append(
                    f"  before statement {cut.stmt + 1} (frame {cut.frame}): " + "; ".join(cut.reasons)
                )
            if len(refused) > 12:
                lines.append(f"  ... and {len(refused) - 12} more")
        return "\n".join(lines)


# -- reading the names -----------------------------------------------------------------------------


class _Names(ast.NodeVisitor):
    """Names a statement defines, reads and may change. Lambdas, comprehensions and nested functions
    keep their own parameters and targets to themselves; what they read from outside counts as read."""

    def __init__(self, objects: set[str]) -> None:
        self.objects = objects  # prelude variables that hold something mutable
        self.defines: set[str] = set()
        self.reads: set[str] = set()
        self.touches: set[str] = set()
        self.scene_state = False
        self._local: list[set[str]] = []

    # scopes
    def _is_local(self, name: str) -> bool:
        return any(name in scope for scope in self._local)

    def _scoped(self, node, params: set[str]) -> None:
        self._local.append(params)
        self.generic_visit(node)
        self._local.pop()

    def visit_Lambda(self, node: ast.Lambda) -> None:
        names = {a.arg for a in node.args.args + node.args.kwonlyargs + node.args.posonlyargs}
        for extra in (node.args.vararg, node.args.kwarg):
            if extra is not None:
                names.add(extra.arg)
        self._scoped(node, names)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.defines.add(node.name)
        names = {a.arg for a in node.args.args + node.args.kwonlyargs + node.args.posonlyargs}
        for extra in (node.args.vararg, node.args.kwarg):
            if extra is not None:
                names.add(extra.arg)
        self._local.append(names)
        for child in node.body:
            self.visit(child)
        self._local.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.visit_FunctionDef(node)  # type: ignore[arg-type]

    def _comprehension(self, node) -> None:
        bound: set[str] = set()
        for generator in node.generators:
            for target in ast.walk(generator.target):
                if isinstance(target, ast.Name):
                    bound.add(target.id)
        self._scoped(node, bound)

    def visit_ListComp(self, node: ast.ListComp) -> None:
        self._comprehension(node)

    def visit_SetComp(self, node: ast.SetComp) -> None:
        self._comprehension(node)

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        self._comprehension(node)

    def visit_DictComp(self, node: ast.DictComp) -> None:
        self._comprehension(node)

    # names
    def visit_Name(self, node: ast.Name) -> None:
        if self._is_local(node.id):
            return
        if isinstance(node.ctx, ast.Store):
            self.defines.add(node.id)
        elif isinstance(node.ctx, ast.Del):
            self.touches.add(node.id)
        else:
            self.reads.add(node.id)
            if node.id == "self":
                return

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.defines.add((alias.asname or alias.name).split(".")[0])

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            self.defines.add(alias.asname or alias.name)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.defines.add(node.name)
        self.generic_visit(node)

    def visit_Global(self, node: ast.Global) -> None:
        self.scene_state = True  # code that writes module state: carries it across chapters

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        self.scene_state = True

    # attribute chains and calls
    @staticmethod
    def _chain(node: ast.AST) -> tuple[str | None, list[str]]:
        """``a.b.c(...)`` -> ('a', ['b', 'c']); anything not rooted at a plain name -> (None, [])."""
        attrs: list[str] = []
        while True:
            if isinstance(node, ast.Attribute):
                attrs.append(node.attr)
                node = node.value
            elif isinstance(node, ast.Call):
                node = node.func
            elif isinstance(node, ast.Subscript):
                node = node.value
            else:
                break
        attrs.reverse()
        return (node.id, attrs) if isinstance(node, ast.Name) else (None, [])

    def _touch(self, root: str | None, attrs: list[str]) -> None:
        if root is None or self._is_local(root):
            return
        if root == "self":
            if not attrs:
                return
            if attrs[0] in SCENE_METHODS:
                return
            self.touches.add(f"self.{attrs[0]}")
            self.scene_state = True
            return
        if root in ("config", "tempconfig") or (root == "m" and attrs[:1] == ["config"]):
            self.scene_state = True
        self.touches.add(root)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        root, attrs = self._chain(node)
        if root == "self" and attrs and attrs[0] not in SCENE_METHODS:
            pseudo = f"self.{attrs[0]}"
            if isinstance(node.ctx, ast.Store):
                self.defines.add(pseudo)
                self.scene_state = True
            else:
                self.reads.add(pseudo)
        if isinstance(node.ctx, ast.Store):
            self._touch(root, attrs)
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        if isinstance(node.ctx, ast.Store | ast.Del):
            root, attrs = self._chain(node)
            self._touch(root, attrs)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        root, attrs = self._chain(node.func)
        if isinstance(node.func, ast.Attribute):
            last = attrs[-1] if attrs else ""
            if not (last.startswith("get_") or last in PURE_METHODS):
                self._touch(root, attrs)
            if last in MUTATORS and root is not None and root != "self":
                self.touches.add(root)
        elif isinstance(node.func, ast.Name) and node.func.id in ("setattr", "delattr") and node.args:
            first = node.args[0]
            if isinstance(first, ast.Name):
                self.touches.add(first.id)
        # an object passed as an argument can be changed by what receives it (FadeIn(x), group.add(x))
        for argument in [*node.args, *(k.value for k in node.keywords)]:
            for inner in ast.walk(argument):
                if isinstance(inner, ast.Name) and inner.id in self.objects and not self._is_local(inner.id):
                    self.touches.add(inner.id)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        target = node.target
        if isinstance(target, ast.Name) and not self._is_local(target.id):
            self.reads.add(target.id)
            self.defines.add(target.id)
        else:
            root, attrs = self._chain(target)
            self._touch(root, attrs)
        self.visit(node.value)
        if not isinstance(target, ast.Name):
            self.visit(target)


def _find_construct(tree: ast.Module) -> tuple[ast.ClassDef, ast.FunctionDef] | None:
    scene = None
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "construct":
                    if scene is not None:
                        return None  # two scenes: the runner refuses it too
                    scene = (node, item)
    return scene


def _pure_value(node: ast.AST, known: set[str]) -> bool:
    """A value made only of constants and arithmetic on names that are not objects of the prelude."""
    for inner in ast.walk(node):
        if isinstance(
            inner, ast.Call | ast.Lambda | ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp
        ):
            return False
        if isinstance(inner, ast.Name) and inner.id in known:
            return False
        if isinstance(inner, ast.List | ast.Dict | ast.Set):
            return False  # mutable containers carry state
    return True


def read_statements(code: str) -> tuple[str, list[Statement], str]:
    """(class name, statements of ``construct``, problem). The problem is '' when the code could be read."""
    try:
        tree = ast.parse(code)
    except SyntaxError as error:
        return "", [], f"it does not parse ({error.msg}, line {error.lineno})"
    found = _find_construct(tree)
    if found is None:
        return "", [], "it must define exactly one Scene with a construct method"
    scene, construct = found
    body = construct.body
    lines = [(stmt.lineno, stmt.end_lineno or stmt.lineno) for stmt in body]
    for (_first_a, last_a), (first_b, _last_b) in pairwise(lines):
        if first_b <= last_a:
            return scene.name, [], "two statements share a line"
    # which variables hold objects: assigned from anything but constants and arithmetic
    objects: set[str] = set()
    for stmt in body:
        if isinstance(stmt, ast.Assign) and not _pure_value(stmt.value, objects):
            for target in stmt.targets:
                for name in ast.walk(target):
                    if isinstance(name, ast.Name):
                        objects.add(name.id)
        elif isinstance(stmt, ast.AnnAssign | ast.For | ast.With | ast.FunctionDef):
            for name in ast.walk(stmt):
                if isinstance(name, ast.Name) and isinstance(name.ctx, ast.Store):
                    objects.add(name.id)
    statements = []
    source = code.splitlines()
    for index, stmt in enumerate(body):
        visitor = _Names(objects)
        visitor.visit(stmt)
        kills = frozenset(n for n in visitor.defines if n not in visitor.reads)
        first, last = lines[index]
        text = source[first - 1].strip() if first - 1 < len(source) else ""
        statements.append(
            Statement(
                index,
                first,
                last,
                text[:80],
                frozenset(visitor.defines),
                frozenset(visitor.reads - {"self"}),
                frozenset(visitor.touches),
                visitor.scene_state,
                kills,
            )
        )
    return scene.name, statements, ""


# -- the verdict -----------------------------------------------------------------------------------


def _needed_later(statements: list[Statement], start: int) -> set[str]:
    """Names statements from ``start`` on read (or change) before they define them again."""
    needed: set[str] = set()
    dead: set[str] = set()
    for stmt in statements[start:]:
        for name in sorted(stmt.reads | stmt.touches):
            if name not in dead:
                needed.add(name)
        dead |= stmt.kills
    return needed


def _closure(statements: list[Statement], first_animated: int, names: set[str]) -> set[str]:
    """``names`` and everything the setup says they are made from: a mobject built from a function that
    reads a tracker depends on that tracker even though no later statement mentions it."""
    makers: dict[str, list[Statement]] = {}
    for stmt in statements[:first_animated]:
        for name in stmt.defines:
            makers.setdefault(name, []).append(stmt)
    seen = set(names)
    queue = list(names)
    while queue:
        name = queue.pop()
        for stmt in makers.get(name, ()):
            for dependency in stmt.reads:
                if dependency not in seen:
                    seen.add(dependency)
                    queue.append(dependency)
    return seen


def _static_reasons(statements: list[Statement], first_animated: int, cut: int) -> list[str]:
    """Why statements [first_animated, cut) cannot be left out of a chapter that starts at ``cut``."""
    reasons: list[str] = []
    needed = _needed_later(statements, cut)
    earlier = statements[first_animated:cut]
    defined: set[str] = set()
    touched: set[str] = set()
    for stmt in earlier:
        defined |= stmt.defines
        touched |= stmt.touches
        if stmt.scene_state:
            reasons.append(f"statement {stmt.index + 1} changes the scene itself ({stmt.text!r})")
    prelude_names: set[str] = set()
    for stmt in statements[:first_animated]:
        prelude_names |= stmt.defines
    carried = sorted((defined & needed) - set())
    if carried:
        reasons.append("later statements read " + ", ".join(carried) + " from this part")
    changed = sorted((touched & needed & prelude_names) - set(carried))
    if changed:
        reasons.append("later statements use " + ", ".join(changed) + ", which this part changes")
    return reasons


def _state_reasons(
    statements: list[Statement], first_animated: int, cut: int, base: dict, probe: dict
) -> list[str]:
    """What a later statement needs from the setup (directly or through what the setup built) must be
    in the state the setup left it: a tracker its updater keeps moving is not."""
    if "names" not in base or "names" not in probe:
        return ["the render did not record the state of the variables: render the scene again"]
    needed = _closure(statements, first_animated, _needed_later(statements, cut))
    moved = sorted(
        name for name in needed if name in base["names"] and probe["names"].get(name) != base["names"][name]
    )
    if moved:
        return [", ".join(moved) + " moved on since the setup and later statements depend on it"]
    return []


def analyse(
    code: str, probes: list[dict[str, Any]] | None, fps: int = 30, total_frames: int | None = None
) -> Analysis:
    """Read the code, read the probes of its render, find the chapters."""
    name, statements, problem = read_statements(code)
    result = Analysis(class_name=name, statements=statements, fps=fps)
    if problem:
        result.problem = problem
        return result
    result.ok = True
    if not probes:
        result.notes.append(
            "Render the scene once with this version of Studio: the cut points need what the render records."
        )
        return result
    by_stmt = {p["stmt"]: p for p in probes if "stmt" in p}
    if any("error" in p for p in probes):
        result.notes.append("Some boundaries could not be surveyed; they are not cut points.")
    emitted = max((p.get("frame", 0) for p in probes), default=0)
    result.total_frames = max(emitted, total_frames or 0)
    first_animated = len(statements)
    for index in range(len(statements)):
        nxt = by_stmt.get(index + 1)
        if nxt is not None and nxt.get("frame", 0) > 0:
            first_animated = index
            break
    else:
        last = by_stmt.get(len(statements) - 1)
        if last is not None and last.get("frame", 0) == 0:
            first_animated = len(statements) - 1  # the last statement is the one that plays
    result.first_animated = first_animated
    result.prelude_end = first_animated
    base = by_stmt.get(first_animated)
    if base is None or "visible" not in base:
        result.notes.append("The baseline could not be surveyed.")
        return result
    minimum = int(MIN_CHAPTER_SECONDS * fps)
    chosen: list[Cut] = []
    last_frame = base.get("frame", 0)
    for cut in range(first_animated + 1, len(statements)):
        probe = by_stmt.get(cut)
        if probe is None or "visible" not in probe:
            continue
        reasons: list[str] = []
        if probe["visible"] != base["visible"]:
            reasons.append("something is still on screen that was not in the setup")
        if probe.get("camera", "") != base.get("camera", ""):
            reasons.append("the camera moved")
        if probe.get("visible_updaters", 0) != base.get("visible_updaters", 0):
            reasons.append("an updater still runs on something visible")
        if probe.get("scene_updaters", 0) != base.get("scene_updaters", 0):
            reasons.append("an updater was added to the scene")
        if probe.get("updating", False) != base.get("updating", False):
            reasons.append("an updater is still running that was not part of the setup")
        if probe.get("entangled"):
            reasons.append("a hidden object's updater still reaches something on screen")
        if not reasons:
            reasons += _static_reasons(statements, first_animated, cut)
        if not reasons:
            reasons += _state_reasons(statements, first_animated, cut, base, probe)
        frame = probe.get("frame", 0)
        if not reasons and frame <= last_frame:
            continue  # nothing was drawn since the last cut: the same place, not a new one
        if not reasons and frame - last_frame < minimum:
            reasons.append(f"the chapter would be shorter than {MIN_CHAPTER_SECONDS:g} s")
        verdict = Cut(cut, frame, float(probe.get("t", 0.0)), not reasons, tuple(reasons))
        result.cuts.append(verdict)
        if verdict.ok:
            chosen.append(verdict)
            last_frame = frame
    bounds = [first_animated, *[c.stmt for c in chosen], len(statements)]
    frames = [base.get("frame", 0), *[c.frame for c in chosen]]
    times = [float(base.get("t", 0.0)), *[c.time for c in chosen]]
    for n in range(len(bounds) - 1):
        end_frame = frames[n + 1] if n + 1 < len(frames) else None
        result.chapters.append(Chapter(bounds[n], bounds[n + 1], frames[n], end_frame, times[n]))
    return result
