"""Code snippets (P13.3): small pieces of Manim to paste into the Code page - pure, no Qt, no Manim.

A snippet is a few lines of plain Manim Community code for a mathematician: a circle, a formula
written in parts, a graph with its area, a number that counts up. Each one is stored dedented, ready
to be pasted **inside** a Scene's ``construct(self)`` (the UI re-indents it to the cursor with
``indent``); the ones of the category ``"Python object"`` are module-level code for a Python object
(``PARAMS`` + ``build(p)``, ADR 0051) and are pasted at the left margin.

The text has **tab stops** in the editor's own notation: ``${1:default}`` is a place to type (it
shows ``default`` selected), ``${2}`` one with nothing in it, and ``$0`` where the cursor ends. A
default may hold balanced braces (``${1:\\frac{a}{b}}``). Numbers go 1, 2, 3 ... in the order they
appear, once each; ``$0`` may appear once. ``expand`` turns the text into plain code and tells where
each stop is; ``search`` finds snippets by words. A snippet never names a Manim object that does not
exist (the tests check every name against the installed Manim).
"""

from __future__ import annotations

from dataclasses import dataclass
from textwrap import dedent

CATEGORIES = (
    "Shapes",
    "Text and equations",
    "Axes and graphs",
    "Vectors and matrices",
    "Animations",
    "Camera and updaters",
    "Numbers and trackers",
    "Python object",
)
OBJECT_CATEGORY = "Python object"  # module-level code, not for a construct


@dataclass(frozen=True)
class Snippet:
    """One snippet. ``id`` is unique and stable; ``code`` is dedented, with ``${n:default}`` stops."""

    id: str
    title: str
    category: str
    description: str
    code: str

    @property
    def module_level(self) -> bool:
        """Whether the code goes at the left margin of the file (a Python object), not in a construct."""
        return self.category == OBJECT_CATEGORY


def _s(snippet_id: str, title: str, category: str, description: str, code: str) -> Snippet:
    return Snippet(snippet_id, title, category, description, dedent(code).strip("\n"))


# -- tab stops -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Stop:
    number: int  # 0 for ``$0``
    default: str
    start: int  # offset of the ``$`` in the raw text
    end: int  # offset just after the placeholder in the raw text


def _stops(code: str) -> list[_Stop]:
    """The placeholders of ``code`` in the order they appear; ``ValueError(reason)`` when malformed."""
    out: list[_Stop] = []
    i, size = 0, len(code)
    while i < size:
        if code[i] != "$":
            i += 1
            continue
        nxt = code[i + 1 : i + 2]
        if nxt == "{":
            j = i + 2
            while j < size and code[j].isdigit():
                j += 1
            digits = code[i + 2 : j]
            if not digits:
                raise ValueError(f"placeholder at offset {i} has no number")
            if j < size and code[j] == "}":
                out.append(_Stop(int(digits), "", i, j + 1))
                i = j + 1
                continue
            if j >= size or code[j] != ":":
                raise ValueError(f"placeholder at offset {i} must be ${{n}} or ${{n:default}}")
            k, depth = j + 1, 0
            while k < size:
                if code[k] == "{":
                    depth += 1
                elif code[k] == "}":
                    if depth == 0:
                        break
                    depth -= 1
                k += 1
            if k >= size:
                raise ValueError(f"placeholder at offset {i} is not closed")
            out.append(_Stop(int(digits), code[j + 1 : k], i, k + 1))
            i = k + 1
        elif nxt == "0":
            out.append(_Stop(0, "", i, i + 2))
            i += 2
        elif nxt.isdigit():
            raise ValueError(f"placeholder at offset {i}: write ${{{nxt}:default}}, not ${nxt}")
        else:
            i += 1  # a plain dollar sign
    return out


def template_problem(code: str) -> str | None:
    """Why the tab stops of ``code`` are not well formed, or None.

    They must be ``${n:default}`` / ``${n}`` / ``$0``, numbered 1, 2, 3 ... in the order they appear
    (each once), and ``$0`` at most once.
    """
    try:
        stops = _stops(code)
    except ValueError as exc:
        return str(exc)
    numbers = [s.number for s in stops if s.number != 0]
    if numbers != list(range(1, len(numbers) + 1)):
        return f"tab stops must be numbered 1, 2, 3 ... in order, once each; found {numbers}"
    if sum(1 for s in stops if s.number == 0) > 1:
        return "$0 may appear only once"
    return None


def expand(code: str) -> tuple[str, list[tuple[int, int]]]:
    """``code`` with each placeholder replaced by its default, and the tab stops.

    Returns ``(text, stops)``: ``stops`` holds the ``(start, end)`` offsets in ``text`` of each stop in
    the order the user visits them (1, 2, 3 ...; ``$0`` last, as an empty range, when present). A
    snippet without ``$0`` has no final stop: the cursor ends after the text. A text with a malformed
    placeholder is returned as it is, with no stops.
    """
    try:
        found = _stops(code)
    except ValueError:
        return code, []
    pieces: list[str] = []
    ranges: list[tuple[int, int, int]] = []  # (number, start, end) in the new text
    last = length = 0
    for stop in found:
        before = code[last : stop.start]
        pieces.append(before)
        length += len(before)
        ranges.append((stop.number, length, length + len(stop.default)))
        pieces.append(stop.default)
        length += len(stop.default)
        last = stop.end
    pieces.append(code[last:])
    ordered = sorted(ranges, key=lambda r: (r[0] == 0, r[0]))  # stable: 0 goes last
    return "".join(pieces), [(start, end) for _, start, end in ordered]


def indent(code: str, prefix: str, *, skip_first: bool = False) -> str:
    """``code`` with ``prefix`` in front of every line that has something on it (blank lines stay empty).

    ``skip_first`` leaves the first line alone: it goes where the cursor already is, after its indent.
    """
    lines = code.split("\n")
    return "\n".join(
        line if (not line.strip() or (skip_first and n == 0)) else prefix + line
        for n, line in enumerate(lines)
    )


# -- search ----------------------------------------------------------------------------------------


def search(query: str, snippets: tuple[Snippet, ...] | list[Snippet] | None = None) -> list[Snippet]:
    """The snippets matching every word of ``query`` (case-insensitive), best first.

    A word matches when it is in the title, description, category or id. A title match counts most
    (more at the start of a word or of the title), then the id, the category and the description;
    snippets of equal rank keep their order. An empty query returns them all in order.
    """
    pool = SNIPPETS if snippets is None else tuple(snippets)
    words = query.lower().split()
    if not words:
        return list(pool)
    ranked: list[tuple[int, int, Snippet]] = []
    for index, snippet in enumerate(pool):
        total = 0
        for word in words:
            score = _word_score(word, snippet)
            if score == 0:
                break
            total += score
        else:
            ranked.append((-total, index, snippet))
    ranked.sort(key=lambda r: (r[0], r[1]))
    return [snippet for _, _, snippet in ranked]


def _word_score(word: str, snippet: Snippet) -> int:
    title = snippet.title.lower()
    if title.startswith(word):
        return 100
    if f" {word}" in title:
        return 80
    if word in title:
        return 60
    if word in snippet.id.lower():
        return 40
    if word in snippet.category.lower():
        return 30
    if word in snippet.description.lower():
        return 10
    return 0


# -- the snippets ----------------------------------------------------------------------------------

_SHAPES = "Shapes"
_TEXT = "Text and equations"
_AXES = "Axes and graphs"
_VECTORS = "Vectors and matrices"
_ANIM = "Animations"
_CAMERA = "Camera and updaters"
_NUMBERS = "Numbers and trackers"
_OBJECT = OBJECT_CATEGORY

SNIPPETS: tuple[Snippet, ...] = (
    # -- Shapes ------------------------------------------------------------------------------------
    _s(
        "circle",
        "Circle",
        _SHAPES,
        "A filled circle that is drawn on screen.",
        """
        circle = Circle(radius=${1:1.5}, color=${2:BLUE})
        circle.set_fill(${3:BLUE}, opacity=${4:0.4})
        self.play(Create(circle))
        $0
        """,
    ),
    _s(
        "square",
        "Square",
        _SHAPES,
        "A square turned by an angle, with a thick outline.",
        """
        square = Square(side_length=${1:2}, color=${2:YELLOW})
        square.set_stroke(width=${3:6})
        square.rotate(${4:PI / 6})
        self.add(square)
        $0
        """,
    ),
    _s(
        "polygon",
        "Polygon from points",
        _SHAPES,
        "A triangle (or any polygon) through the points you give.",
        """
        triangle = Polygon(${1:LEFT * 2}, ${2:RIGHT * 2}, ${3:UP * 2}, color=${4:GREEN})
        triangle.set_fill(opacity=0.3)
        self.play(Create(triangle))
        $0
        """,
    ),
    _s(
        "arc",
        "Arc",
        _SHAPES,
        "A piece of a circle, given its start angle and its sweep.",
        """
        arc = Arc(radius=${1:2}, start_angle=${2:0}, angle=${3:PI / 2}, color=${4:RED})
        arc.set_stroke(width=6)
        self.play(Create(arc))
        $0
        """,
    ),
    _s(
        "angle-marks",
        "Angle and right angle marks",
        _SHAPES,
        "Two lines from a corner with an angle arc and a right-angle square.",
        """
        base = Line(ORIGIN, RIGHT * 3)
        side = Line(ORIGIN, UP * 2)
        slanted = Line(ORIGIN, (RIGHT + UP) * 2)
        corner = RightAngle(base, side, length=${1:0.4}, quadrant=(1, 1))
        opening = Angle(base, slanted, radius=${2:0.8}, color=YELLOW)
        self.add(base, side, slanted, corner, opening)
        $0
        """,
    ),
    _s(
        "brace",
        "Brace with a label",
        _SHAPES,
        "A curly brace under an object, with a text on it.",
        """
        shape = Rectangle(width=${1:4}, height=${2:1.5})
        brace = Brace(shape, direction=DOWN)
        label = brace.get_text(${3:"width"})
        self.play(Create(shape), GrowFromCenter(brace), Write(label))
        $0
        """,
    ),
    _s(
        "surrounding-rectangle",
        "Box around an object",
        _SHAPES,
        "A rectangle that surrounds another object, to point at it.",
        """
        formula = MathTex(${1:r"x^2 + y^2 = r^2"})
        box = SurroundingRectangle(formula, color=${2:YELLOW}, buff=0.25)
        self.play(Write(formula))
        self.play(Create(box))
        $0
        """,
    ),
    _s(
        "vgroup-arrange",
        "Group in a row",
        _SHAPES,
        "Put objects in a VGroup and arrange them with a gap between.",
        """
        group = VGroup(Square(), Circle(), Triangle())
        group.arrange(${1:RIGHT}, buff=${2:0.8})
        group.move_to(ORIGIN)
        self.play(FadeIn(group))
        $0
        """,
    ),
    _s(
        "position",
        "Place relative to another object",
        _SHAPES,
        "next_to, shift, to_edge, scale and rotate on a few objects.",
        """
        square = Square()
        circle = Circle().next_to(square, ${1:RIGHT}, buff=0.5)
        caption = Text("label", font_size=28).next_to(square, UP)
        corner = Dot().to_corner(UL)
        square.shift(DOWN * 0.5).rotate(PI / 4).scale(${2:1.2})
        self.add(square, circle, caption, corner)
        $0
        """,
    ),
    # -- Text and equations ------------------------------------------------------------------------
    _s(
        "text",
        "Text",
        _TEXT,
        "A plain text (not a formula) with a size and a colour.",
        """
        title = Text(${1:"Hello, Manim"}, font_size=${2:48}, color=${3:WHITE})
        title.to_edge(UP)
        self.play(Write(title))
        $0
        """,
    ),
    _s(
        "mathtex",
        "Formula (MathTex)",
        _TEXT,
        "A LaTeX formula written on screen.",
        r"""
        formula = MathTex(r"${1:e^{i\pi} + 1 = 0}")
        formula.scale(${2:1.5})
        self.play(Write(formula))
        $0
        """,
    ),
    _s(
        "mathtex-parts",
        "Formula in coloured parts",
        _TEXT,
        "Each string of MathTex is a part you can colour or animate on its own.",
        """
        eq = MathTex("a^2", "+", "b^2", "=", "c^2")
        eq[0].set_color(${1:RED})
        eq[2].set_color(${2:BLUE})
        eq[4].set_color(${3:GREEN})
        self.play(Write(eq))
        $0
        """,
    ),
    _s(
        "mathtex-isolate",
        "Colour a letter in a formula",
        _TEXT,
        "Isolate a substring of one formula and colour it.",
        r"""
        eq = MathTex(r"f(x) = x^2 + 2x + 1", substrings_to_isolate=["x"])
        eq.set_color_by_tex("x", ${1:YELLOW})
        self.play(Write(eq))
        $0
        """,
    ),
    _s(
        "aligned-equations",
        "Aligned equations",
        _TEXT,
        "Several lines of algebra aligned on the equals sign.",
        r"""
        steps = MathTex(
            r"x^2 - 5x + 6 &= 0 \\",
            r"(x - 2)(x - 3) &= 0 \\",
            r"x &= 2 \quad \text{or} \quad x = 3",
        )
        self.play(Write(steps))
        $0
        """,
    ),
    # -- Axes and graphs ---------------------------------------------------------------------------
    _s(
        "axes-plot",
        "Axes and a function graph",
        _AXES,
        "Axes with numbers, the graph of a function and its label.",
        """
        axes = Axes(x_range=[-3, 3, 1], y_range=[-1, 9, 2], x_length=7, y_length=4,
                    axis_config={"include_numbers": True})
        graph = axes.plot(lambda x: ${1:x**2}, color=${2:YELLOW})
        label = axes.get_graph_label(graph, "x^2")
        self.play(Create(axes), Create(graph), Write(label))
        $0
        """,
    ),
    _s(
        "riemann",
        "Riemann rectangles",
        _AXES,
        "The area under a curve approximated by rectangles.",
        """
        axes = Axes(x_range=[0, 4, 1], y_range=[0, 9, 3], x_length=6, y_length=4)
        graph = axes.plot(lambda x: ${1:x**2 / 2}, color=BLUE)
        rects = axes.get_riemann_rectangles(
            graph, x_range=[0, 3], dx=${2:0.25}, input_sample_type="left", fill_opacity=0.6
        )
        self.play(Create(axes), Create(graph))
        self.play(Create(rects))
        $0
        """,
    ),
    _s(
        "area-under",
        "Area under a graph",
        _AXES,
        "Shade the region between a graph and the x axis.",
        """
        axes = Axes(x_range=[0, 4, 1], y_range=[0, 5, 1], x_length=6, y_length=4)
        graph = axes.plot(lambda x: ${1:np.sqrt(x) + 1}, x_range=[0, 4], color=GREEN)
        area = axes.get_area(graph, x_range=(${2:1}, ${3:3}), color=GREEN, opacity=0.4)
        self.add(axes, graph)
        self.play(FadeIn(area))
        $0
        """,
    ),
    _s(
        "parametric",
        "Parametric curve",
        _AXES,
        "A curve (x(t), y(t)) drawn as t goes over a range.",
        """
        curve = ParametricFunction(
            lambda t: np.array([${1:np.cos(t)}, ${2:np.sin(2 * t)}, 0]) * 2,
            t_range=[0, TAU],
            color=${3:PURPLE},
        )
        self.play(Create(curve), run_time=3)
        $0
        """,
    ),
    _s(
        "number-line",
        "Number line with a point",
        _AXES,
        "A number line with numbers and a dot at a value.",
        """
        line = NumberLine(x_range=[-5, 5, 1], length=10, include_numbers=True)
        dot = Dot(line.n2p(${1:2.5}), color=YELLOW)
        self.add(line)
        self.play(FadeIn(dot, shift=DOWN))
        $0
        """,
    ),
    _s(
        "number-plane",
        "Number plane with a point",
        _AXES,
        "A coordinate grid and a dot placed with coordinates.",
        """
        plane = NumberPlane(x_range=[-6, 6, 1], y_range=[-4, 4, 1])
        dot = Dot(plane.c2p(${1:2}, ${2:1}), color=RED)
        self.add(plane)
        self.play(FadeIn(dot))
        $0
        """,
    ),
    _s(
        "complex-plane",
        "Complex plane",
        _AXES,
        "The complex plane with a point at a complex number.",
        """
        plane = ComplexPlane()
        z = ${1:2 + 1j}
        point = Dot(plane.n2p(z), color=YELLOW)
        arrow = Arrow(plane.n2p(0), plane.n2p(z), buff=0, color=YELLOW)
        self.add(plane)
        self.play(FadeIn(point), Create(arrow))
        $0
        """,
    ),
    # -- Vectors and matrices ----------------------------------------------------------------------
    _s(
        "vector",
        "Vector with a label",
        _VECTORS,
        "An arrow from the origin on a grid, named at its tip.",
        r"""
        plane = NumberPlane()
        vec = Vector([${1:2}, ${2:1}], color=YELLOW)
        label = MathTex(r"\vec{v}").next_to(vec.get_end(), UR)
        self.add(plane)
        self.play(GrowArrow(vec), Write(label))
        $0
        """,
    ),
    _s(
        "vector-sum",
        "Adding vectors tip to tail",
        _VECTORS,
        "Two vectors placed one after the other and their sum.",
        """
        u = Vector([2, 0], color=BLUE)
        v = Vector([1, 2], color=RED).shift(u.get_end())
        total = Vector([3, 2], color=GREEN)
        self.play(GrowArrow(u))
        self.play(GrowArrow(v))
        self.play(GrowArrow(total))
        $0
        """,
    ),
    _s(
        "matrix",
        "Matrix",
        _VECTORS,
        "A matrix with its columns coloured.",
        """
        m = Matrix([[${1:1}, ${2:2}], [${3:3}, ${4:4}]])
        m.set_column_colors(RED, BLUE)
        self.play(Write(m))
        $0
        """,
    ),
    _s(
        "integer-matrix",
        "Integer matrix",
        _VECTORS,
        "A matrix of whole numbers with square brackets.",
        """
        identity = IntegerMatrix([[1, 0, 0], [0, 1, 0], [0, 0, 1]], left_bracket="[", right_bracket="]")
        identity.get_rows()[${1:0}].set_color(YELLOW)
        self.play(FadeIn(identity))
        $0
        """,
    ),
    _s(
        "apply-matrix",
        "Linear transformation of the plane",
        _VECTORS,
        "Apply a 2 by 2 matrix to the grid and to the basis vectors.",
        """
        m = ${1:[[1, 1], [0, 1]]}
        plane = NumberPlane()
        i_hat = Vector([1, 0], color=GREEN)
        j_hat = Vector([0, 1], color=RED)
        self.add(plane, i_hat, j_hat)
        self.play(ApplyMatrix(m, plane), ApplyMatrix(m, i_hat), ApplyMatrix(m, j_hat), run_time=2)
        $0
        """,
    ),
    # -- Animations --------------------------------------------------------------------------------
    _s(
        "write-fadeout",
        "Write, wait, fade out",
        _ANIM,
        "Write a text, hold it for a moment, then fade it away.",
        """
        message = Text(${1:"Let's begin"})
        self.play(Write(message))
        self.wait(${2:1})
        self.play(FadeOut(message))
        $0
        """,
    ),
    _s(
        "transform",
        "Transform one shape into another",
        _ANIM,
        "Transform keeps the first object on screen, now shaped like the second.",
        """
        start = Square(color=BLUE)
        end = Circle(color=RED)
        self.add(start)
        self.play(Transform(start, end))
        $0
        """,
    ),
    _s(
        "replacement-transform",
        "Replace an object by another",
        _ANIM,
        "ReplacementTransform leaves the second object on screen, not the first.",
        """
        start = Square(color=BLUE)
        end = Triangle(color=GREEN)
        self.add(start)
        self.play(ReplacementTransform(start, end))
        self.play(end.animate.shift(UP).scale(1.5))
        $0
        """,
    ),
    _s(
        "transform-matching-tex",
        "Rearrange a formula",
        _ANIM,
        "Parts with the same text move to their new place; the others fade.",
        """
        before = MathTex("a", "^2", "+", "b", "^2", "=", "c", "^2")
        after = MathTex("c", "^2", "=", "a", "^2", "+", "b", "^2")
        self.add(before)
        self.play(TransformMatchingTex(before, after), run_time=2)
        $0
        """,
    ),
    _s(
        "animate-chain",
        "Animate several changes at once",
        _ANIM,
        "The animate property turns a chain of changes into one animation.",
        """
        square = Square(color=BLUE)
        self.add(square)
        self.play(square.animate.rotate(PI / 2).shift(RIGHT * ${1:2}).set_color(RED), run_time=2)
        self.play(square.animate.scale(0.5), rate_func=there_and_back)
        $0
        """,
    ),
    _s(
        "lagged-start",
        "Animations one after another, overlapping",
        _ANIM,
        "LaggedStart starts each animation a little after the one before.",
        """
        dots = VGroup(*[Dot(radius=0.15) for _ in range(${1:8})]).arrange(RIGHT, buff=0.4)
        self.play(LaggedStart(*[FadeIn(dot, shift=UP) for dot in dots], lag_ratio=${2:0.2}))
        self.play(LaggedStart(*[Indicate(dot) for dot in dots], lag_ratio=0.2))
        $0
        """,
    ),
    _s(
        "emphasis",
        "Draw attention",
        _ANIM,
        "Indicate, Flash and Wiggle call the eye to an object.",
        r"""
        formula = MathTex(r"a^2 + b^2 = c^2")
        self.add(formula)
        self.play(Indicate(formula))
        self.play(Flash(formula, color=YELLOW))
        self.play(Wiggle(formula))
        $0
        """,
    ),
    _s(
        "circumscribe",
        "Circle or box around a part",
        _ANIM,
        "Circumscribe draws a rectangle (or a circle) around an object, then removes it.",
        r"""
        formula = MathTex("a^2", "+", "b^2", "=", "c^2")
        self.add(formula)
        self.play(Circumscribe(formula[${1:4}], color=YELLOW))
        self.play(Circumscribe(formula[0], shape=Circle))
        $0
        """,
    ),
    # -- Camera and updaters -----------------------------------------------------------------------
    _s(
        "add-updater",
        "Label that follows a dot",
        _CAMERA,
        "An updater runs on every frame: here it keeps a label above a moving dot.",
        """
        dot = Dot(color=YELLOW)
        label = Text("P", font_size=30)
        label.add_updater(lambda m: m.next_to(dot, UP))
        self.add(dot, label)
        self.play(dot.animate.shift(RIGHT * ${1:3}), run_time=2)
        $0
        """,
    ),
    _s(
        "updater-dt",
        "Updater that uses time (dt)",
        _CAMERA,
        "An object that spins by an amount proportional to the time that passed.",
        """
        def spin(mob, dt):
            mob.rotate(dt * ${1:90} * DEGREES)

        square = Square()
        square.add_updater(spin)
        self.add(square)
        self.wait(${2:3})
        square.remove_updater(spin)
        $0
        """,
    ),
    _s(
        "always-redraw",
        "Line that stays between two dots",
        _CAMERA,
        "always_redraw builds the object again on every frame.",
        """
        a = Dot(LEFT * 2, color=BLUE)
        b = Dot(RIGHT * 2, color=RED)
        link = always_redraw(lambda: Line(a.get_center(), b.get_center(), color=YELLOW))
        self.add(link, a, b)
        self.play(b.animate.shift(UP * 2), a.animate.shift(DOWN))
        $0
        """,
    ),
    _s(
        "move-along-path",
        "Move a dot along a path",
        _CAMERA,
        "A dot follows the outline of another object.",
        """
        path = Circle(radius=${1:2})
        dot = Dot(path.point_from_proportion(0), color=YELLOW)
        self.add(path, dot)
        self.play(MoveAlongPath(dot, path), run_time=${2:4}, rate_func=linear)
        $0
        """,
    ),
    _s(
        "camera-zoom",
        "Zoom the camera onto an object",
        _CAMERA,
        "Move and scale the camera frame. The scene class must be a MovingCameraScene.",
        """
        # the class must be: class MyScene(MovingCameraScene)
        dot = Dot(UR * 2, color=YELLOW)
        self.add(Square(), dot)
        self.camera.frame.save_state()
        self.play(self.camera.frame.animate.scale(${1:0.4}).move_to(dot), run_time=2)
        self.play(Restore(self.camera.frame))
        $0
        """,
    ),
    # -- Numbers and trackers ----------------------------------------------------------------------
    _s(
        "value-tracker-number",
        "A number that counts",
        _NUMBERS,
        "A ValueTracker holds a value; a DecimalNumber shows it as it changes.",
        """
        tracker = ValueTracker(0)
        number = DecimalNumber(0, num_decimal_places=${1:2})
        number.add_updater(lambda m: m.set_value(tracker.get_value()))
        self.add(number)
        self.play(tracker.animate.set_value(${2:10}), run_time=3)
        $0
        """,
    ),
    _s(
        "variable",
        "Variable with its name",
        _NUMBERS,
        "A name and its value together, ready to animate.",
        """
        var = Variable(${1:5}, MathTex("x"), num_decimal_places=2)
        self.add(var)
        self.play(var.tracker.animate.set_value(${2:10}), run_time=2)
        $0
        """,
    ),
    _s(
        "point-on-graph",
        "A point moving along a graph",
        _NUMBERS,
        "A tracker holds x; the dot is redrawn on the graph at that x.",
        """
        axes = Axes(x_range=[0, 4, 1], y_range=[0, 9, 3], x_length=6, y_length=4)
        graph = axes.plot(lambda x: x**2 / 2, color=BLUE)
        x = ValueTracker(${1:0.5})
        dot = always_redraw(lambda: Dot(axes.i2gp(x.get_value(), graph), color=YELLOW))
        self.add(axes, graph, dot)
        self.play(x.animate.set_value(${2:3.5}), run_time=3)
        $0
        """,
    ),
    _s(
        "angle-readout",
        "A turning line and its angle",
        _NUMBERS,
        "A line that turns around the origin, with its angle in degrees.",
        r"""
        angle = ValueTracker(0)
        ray = always_redraw(lambda: Line(ORIGIN, RIGHT * 3).rotate(angle.get_value(), about_point=ORIGIN))
        readout = always_redraw(
            lambda: DecimalNumber(
                angle.get_value() / DEGREES, num_decimal_places=0, unit=r"^\circ"
            ).to_corner(UL)
        )
        self.add(ray, readout)
        self.play(angle.animate.set_value(${1:PI / 2}), run_time=3)
        $0
        """,
    ),
    # -- Python object -----------------------------------------------------------------------------
    _s(
        "object-skeleton",
        "Python object: PARAMS and build",
        _OBJECT,
        "The smallest Python object: one number parameter with limits and a build function.",
        """
        PARAMS = {
            "size": (${1:2.0}, 0.5, 5.0),
            "color": "#58c4dd",
        }


        def build(p):
            return Square(side_length=p["size"], color=p["color"])
        """,
    ),
    _s(
        "object-param-types",
        "Python object: every kind of parameter",
        _OBJECT,
        "A number with limits, a whole number, True/False, text and a colour.",
        """
        PARAMS = {
            "radius": (1.5, 0.2, 4.0),   # a number from 0.2 to 4
            "count": (6, 1, 12),         # a whole number from 1 to 12
            "filled": True,
            "name": "A",
            "color": "#ffd166",
        }


        def build(p):
            circle = Circle(radius=p["radius"], color=p["color"])
            if p["filled"]:
                circle.set_fill(p["color"], opacity=0.4)
            return VGroup(circle, Text(p["name"]))
        """,
    ),
    _s(
        "object-repeat",
        "Python object: many copies",
        _OBJECT,
        "A row of dots whose count and gap are parameters.",
        """
        PARAMS = {
            "count": (5, 1, 20),
            "gap": (0.6, 0.1, 2.0),
            "color": "#ff6b6b",
        }


        def build(p):
            dots = VGroup(*[Dot(color=p["color"]) for _ in range(int(p["count"]))])
            return dots.arrange(RIGHT, buff=p["gap"])
        """,
    ),
    _s(
        "object-formula",
        "Python object: a formula from text",
        _OBJECT,
        "A parameter holds LaTeX text and the object is the formula.",
        """
        PARAMS = {
            "tex": r"\\frac{a}{b}",
            "size": (48, 20, 120),
            "color": "#ffffff",
        }


        def build(p):
            formula = MathTex(p["tex"], font_size=p["size"])
            return formula.set_color(p["color"])
        """,
    ),
    _s(
        "object-graph",
        "Python object: a parabola on axes",
        _OBJECT,
        "Axes and the graph of a x^2 + b, with a and b as parameters.",
        """
        PARAMS = {
            "a": (1.0, -2.0, 2.0),
            "b": (0.0, -3.0, 3.0),
        }


        def build(p):
            axes = Axes(x_range=[-3, 3, 1], y_range=[-4, 6, 2], x_length=6, y_length=4)
            graph = axes.plot(lambda x: p["a"] * x**2 + p["b"], color=YELLOW)
            return VGroup(axes, graph)
        """,
    ),
)
