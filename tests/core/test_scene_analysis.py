"""Where a scene can be cut (ADR 0061): the static reading of names and the verdict on the probes."""

from __future__ import annotations

from manim_studio.core.scene_analysis import analyse, read_statements

PHASES = """
class Main(Scene):
    def construct(self):
        self.add(Line(LEFT, RIGHT))
        gap = 0.5
        a = Dot()
        self.play(FadeIn(a))
        self.play(FadeOut(a))
        b = Square()
        self.play(FadeIn(b))
        self.play(FadeOut(b))
        c = Circle()
        self.play(FadeIn(c))
        self.play(FadeOut(c))
"""


def probes(rows):
    """rows: (frame, visible digest) before statement 0, 1, 2 ...; the rest of a probe is quiet."""
    return [
        {
            "stmt": i,
            "frame": frame,
            "t": frame / 10,
            "visible": visible,
            "all": visible,
            "camera": "",
            "visible_updaters": 0,
            "scene_updaters": 0,
            "updating": False,
            "names": {},
            "entangled": False,
        }
        for i, (frame, visible) in enumerate(rows)
    ]


# before: 0 add, 1 gap, 2 a, 3 play in, 4 play out, 5 b, 6 play in, 7 play out, 8 c, 9 play in, 10 play out
PHASE_ROWS = [
    (0, "E"),
    (0, "B"),
    (0, "B"),
    (0, "B"),
    (10, "BA"),
    (20, "B"),
    (20, "B"),
    (30, "BB"),
    (40, "B"),
    (40, "B"),
    (50, "BC"),
]


def test_a_scene_of_phases_is_cut_between_them() -> None:
    result = analyse(PHASES, probes(PHASE_ROWS), fps=10, total_frames=60)
    assert result.ok and result.first_animated == 3 and result.total_frames == 60
    assert [(c.first, c.end, c.start_frame, c.end_frame) for c in result.chapters] == [
        (3, 5, 0, 20),
        (5, 8, 20, 40),
        (8, 11, 40, None),
    ]
    assert [c.stmt for c in result.cuts if c.ok] == [5, 8]  # the first statement of each later phase
    assert "3 chapters" in result.report() and "33%" in result.report()


def test_something_left_on_screen_means_no_cut() -> None:
    rows = [(f, "B" if v == "B" else v) for f, v in PHASE_ROWS]
    rows[5] = (20, "BA")  # a is still there before phase 2
    rows[8] = (40, "BB")  # and b before phase 3
    result = analyse(PHASES, probes(rows), fps=10, total_frames=60)
    assert not result.splittable
    refused = {c.stmt: c.reasons for c in result.cuts}
    assert "still on screen" in refused[5][0] and "still on screen" in refused[8][0]


def test_a_name_made_in_one_phase_and_used_in_the_next_joins_them() -> None:
    code = PHASES.replace("b = Square()", "b = Square().next_to(a)")
    result = analyse(code, probes(PHASE_ROWS), fps=10, total_frames=60)
    assert [(c.first, c.end) for c in result.chapters] == [(3, 8), (8, 11)]  # a is needed by phase 2
    cut = next(c for c in result.cuts if c.stmt == 5)
    assert not cut.ok and "use a" in cut.reasons[0]  # a: made in the setup, changed by phase 1


def test_a_name_made_again_before_it_is_read_is_not_carried() -> None:
    code = (
        PHASES.replace("c = Circle()", "a = Circle()")
        .replace("FadeIn(c)", "FadeIn(a)")
        .replace("FadeOut(c)", "FadeOut(a)")
    )
    result = analyse(code, probes(PHASE_ROWS), fps=10, total_frames=60)
    assert len(result.chapters) == 3  # phase 3 redefines a before using it


def test_something_made_in_the_setup_and_used_by_two_phases_joins_them() -> None:
    code = PHASES.replace("a = Dot()", "a = Dot()\n        t = ValueTracker(0)").replace(
        "b = Square()", "b = Square()\n        self.play(t.animate.set_value(1))"
    )
    rows = [
        (0, "E"),
        (0, "B"),
        (0, "B"),
        (0, "B"),
        (0, "B"),
        (10, "BA"),
        (20, "B"),
        (20, "B"),
        (30, "BB"),
        (40, "B"),
        (40, "B"),
        (50, "BC"),
    ]
    code = code.replace("c = Circle()", "c = Circle()\n        self.play(t.animate.set_value(2))")
    rows = [*rows[:10], (40, "B"), (40, "B"), (50, "BC")]
    result = analyse(code, probes(rows), fps=10, total_frames=70)
    carried = [c for c in result.cuts if not c.ok and any("changes" in r or "read t" in r for r in c.reasons)]
    assert carried  # t is changed in an earlier phase and used again in a later one


def test_a_container_changed_in_one_phase_and_read_in_a_later_one_joins_them() -> None:
    code = (
        PHASES.replace("gap = 0.5", "log = []")
        .replace("self.play(FadeOut(a))", "self.play(FadeOut(a))\n        log.append(1)")
        .replace("self.play(FadeIn(c))", "self.play(FadeIn(c))\n        print(log)")
    )
    rows = [
        (0, "E"),
        (0, "B"),
        (0, "B"),
        (0, "B"),
        (10, "BA"),
        (20, "B"),
        (20, "B"),
        (20, "B"),
        (30, "BB"),
        (40, "B"),
        (40, "B"),
        (40, "B"),
        (50, "BC"),
    ]
    result = analyse(code, probes(rows), fps=10, total_frames=60)
    assert any("log" in r for c in result.cuts for r in c.reasons)


def test_changing_the_scene_itself_blocks_the_cuts_after_it() -> None:
    code = PHASES.replace(
        "self.play(FadeOut(a))", "self.play(FadeOut(a))\n        self.camera.background_color = RED"
    )
    rows = [
        (0, "E"),
        (0, "B"),
        (0, "B"),
        (0, "B"),
        (10, "BA"),
        (20, "B"),
        (20, "B"),
        (20, "B"),
        (30, "BB"),
        (40, "B"),
        (40, "B"),
        (50, "BC"),
    ]
    result = analyse(code, probes(rows), fps=10, total_frames=60)
    # the change is made after phase 1, so a cut before it is fine; none after it is
    assert [(c.first, c.end) for c in result.chapters] == [(3, 5), (5, 12)]
    assert any("changes the scene itself" in r for c in result.cuts for r in c.reasons)


def test_a_scene_change_in_the_setup_is_part_of_every_chapter() -> None:
    code = PHASES.replace("gap = 0.5", "self.camera.background_color = RED")
    result = analyse(code, probes(PHASE_ROWS), fps=10, total_frames=60)
    assert len(result.chapters) == 3  # the setup runs again in each chapter, so it is the same everywhere


def test_updaters_and_camera_that_survive_a_phase_block_a_cut() -> None:
    quiet = probes(PHASE_ROWS)
    quiet[5]["visible_updaters"] = 1
    quiet[8]["entangled"] = True
    result = analyse(PHASES, quiet, fps=10, total_frames=60)
    reasons = {c.stmt: " ".join(c.reasons) for c in result.cuts}
    assert "updater still runs" in reasons[5] and "hidden object" in reasons[8]
    assert not result.splittable


def test_a_tracker_left_running_changes_how_waits_are_drawn_so_it_blocks_a_cut() -> None:
    running = probes(PHASE_ROWS)
    for p in running[5:]:
        p["updating"] = True  # something with a time-based updater survives from phase 1 on
    result = analyse(PHASES, running, fps=10, total_frames=60)
    assert not result.splittable
    assert any("not part of the setup" in r for c in result.cuts for r in c.reasons)


def test_a_phase_shorter_than_a_second_is_merged() -> None:
    rows = list(PHASE_ROWS)
    rows[5:8] = [(3, "B"), (3, "B"), (13, "BB")]
    rows[8:] = [(15, "B"), (15, "B"), (25, "BC")]
    result = analyse(PHASES, probes(rows), fps=10, total_frames=30)
    assert [c.stmt for c in result.cuts if c.ok] == [8]  # the cut after 3 frames is too early
    assert any("shorter than" in r for c in result.cuts if c.stmt == 5 for r in c.reasons)


def test_code_that_cannot_be_read_says_why() -> None:
    assert "does not parse" in analyse("def (:", None).problem
    assert "exactly one Scene" in analyse("x = 1\n", None).problem
    assert (
        "share a line"
        in analyse("class A(Scene):\n    def construct(self):\n        a = 1; b = 2\n", None).problem
    )
    assert not analyse("x = 1\n", None).ok


def test_without_probes_it_asks_for_a_render() -> None:
    result = analyse(PHASES, None)
    assert result.ok and not result.splittable and "Render the scene" in result.report()


def test_the_names_of_a_statement_are_read_with_their_scopes() -> None:
    _name, statements, problem = read_statements(
        "class A(Scene):\n    def construct(self):\n"
        "        r = ValueTracker(0)\n"
        "        d = Dot().add_updater(lambda m, dt: m.move_to(r.get_value() * RIGHT))\n"
        "        self.play(*[FadeOut(x) for x in (d, r)])\n"
        "        self.time_note = 3\n"
    )
    assert problem == ""
    assert statements[1].reads >= {"r"} and "m" not in statements[1].reads  # the lambda's own parameter
    assert {"d", "r"} <= statements[2].reads and "x" not in statements[2].reads  # the comprehension's own x
    assert "self.time_note" in statements[3].defines and statements[3].scene_state


def test_something_the_setup_built_that_has_moved_on_blocks_a_cut_even_if_unnamed_later() -> None:
    """The setup makes a tracker and a dot that follows it; phase 1 only waits, phase 2 shows the dot.
    Nothing later names the tracker, but the dot depends on it, and its updater moved it during phase 1."""
    code = """
class Main(Scene):
    def construct(self):
        t = ValueTracker(0)
        dot = always_redraw(lambda: Dot(RIGHT * t.get_value()))
        self.add(t)
        self.wait(1)
        self.play(FadeIn(dot))
        self.play(FadeOut(dot))
"""
    rows = [(0, "E"), (0, "E"), (0, "E"), (0, "E"), (10, "E"), (15, "E"), (20, "E")]
    moved = probes(rows)
    for p in moved:
        p["names"] = {"t": "t0", "dot": "d0"}
    for p in moved[4:]:
        p["names"] = {"t": "t1", "dot": "d1"}  # the tracker has advanced after the wait
    result = analyse(code, moved, fps=10, total_frames=30)
    assert any("t moved on" in r or "t, " in r for c in result.cuts for r in c.reasons)
    assert not result.splittable
    still = probes(rows)
    for p in still:
        p["names"] = {"t": "t0", "dot": "d0"}
    assert analyse(code, still, fps=10, total_frames=30).cuts  # unmoved: no objection of this kind
    assert not any(
        "moved on" in r for c in analyse(code, still, fps=10, total_frames=30).cuts for r in c.reasons
    )


def test_probes_without_variable_states_are_asked_to_be_rendered_again() -> None:
    old = probes(PHASE_ROWS)
    for p in old:
        del p["names"]
    result = analyse(PHASES, old, fps=10, total_frames=60)
    assert not result.splittable
    assert any("render the scene again" in r for c in result.cuts for r in c.reasons)


def test_the_report_says_when_a_split_saves_little() -> None:
    rows = [
        (0, "E"),
        (0, "B"),
        (0, "B"),
        (0, "B"),
        (10, "BA"),
        (20, "B"),
        (20, "B"),
        (30, "BB"),
        (40, "B"),
        (40, "B"),
        (50, "BC"),
    ]
    big = analyse(PHASES, probes(rows), fps=10, total_frames=600)  # the last chapter is nearly everything
    assert "saves little" in big.report()
    assert "saves little" not in analyse(PHASES, probes(PHASE_ROWS), fps=10, total_frames=60).report()
