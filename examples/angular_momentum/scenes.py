"""The animation of each section: one Manim scene per section, run as a Studio code layer.

Each scene starts with ``B = [...]`` (written by build.py): the second, within the section, at which
each sentence of the narration starts, plus the end of the section as the last entry. A scene waits for
a sentence with ``at(self, i)`` and stretches its long animations over ``span(i)``.
"""

PRE = '''
INK = "#e2e8f0"
MUTED = "#94a3b8"
BLUE = "#38bdf8"
ORANGE = "#fb923c"
GREEN = "#4ade80"
PINK = "#f472b6"
YELLOW = "#facc15"
PANEL = "#1e293b"
LL = 8.0  # the skater's angular momentum (kg m^2 / s)


def at(sc, i):
    d = B[i] - sc.time
    if d > 0.02:
        sc.wait(d)


def hold(sc, d):
    if d > 0.02:
        sc.wait(d)


def span(i, margin=0.25):
    return max(0.4, B[i + 1] - B[i] - margin)


def finish(sc):
    d = B[-1] - sc.time
    if d > 0.02:
        sc.wait(d)


def backdrop():
    return VGroup(*[Dot([x, y, 0], radius=0.025, color=GREY_B, fill_opacity=0.2) for x in np.arange(-7, 7.1, 1.0) for y in np.arange(-4, 4.1, 1.0)])


def nothing():
    return Dot(ORIGIN, radius=0.001, fill_opacity=0, stroke_width=0)


def lab(text, size=28, color=INK):
    return Text(text, font_size=size, color=color)


def inertia(r):
    return 1.0 + r * r


def omega_of(r):
    return LL / inertia(r)


def skater(r_tr, th_tr, center=ORIGIN, K=1.3):
    """Top view of a skater on the ice: rink rings, shoulders, head, arms, gloves with trails, spin arrow."""
    def hand(sign):
        th = th_tr.get_value()
        return center + sign * K * r_tr.get_value() * np.array([np.cos(th), np.sin(th), 0.0])

    def build():
        r = r_tr.get_value() * K
        th = th_tr.get_value()
        d = np.array([np.cos(th), np.sin(th), 0.0])
        n = np.array([-np.sin(th), np.cos(th), 0.0])
        arms = Line(center - d * r, center + d * r, color=INK, stroke_width=9, stroke_opacity=0.9)
        shoulders = Ellipse(width=0.95, height=0.55, color=BLUE, fill_color=BLUE_E, fill_opacity=1, stroke_width=3)
        shoulders.rotate(th).move_to(center)
        head = Circle(radius=0.2, color=BLUE_B, fill_color=BLUE_C, fill_opacity=1, stroke_width=2).move_to(center)
        nose = Dot(center + n * 0.16, radius=0.045, color=WHITE)
        glow1 = Circle(radius=0.27, stroke_width=0, fill_color=ORANGE, fill_opacity=0.25).move_to(hand(1))
        glow2 = Circle(radius=0.27, stroke_width=0, fill_color=PINK, fill_opacity=0.25).move_to(hand(-1))
        h1 = Dot(hand(1), radius=0.15, color=ORANGE)
        h2 = Dot(hand(-1), radius=0.15, color=PINK)
        w = omega_of(r_tr.get_value())
        spin = Arc(radius=0.78, start_angle=th + 0.9, angle=min(5.0, 0.7 * w), arc_center=center, color=GREEN, stroke_width=5)
        spin.add_tip(tip_length=0.2)
        return VGroup(arms, glow1, glow2, h1, h2, shoulders, head, nose, spin)

    rings = VGroup(*[Circle(radius=q * K, color=GREY_B, stroke_width=1.5, stroke_opacity=0.22).move_to(center) for q in (0.9, 1.45, 2.0)])
    t1 = TracedPath(lambda: hand(1), stroke_color=ORANGE, stroke_width=4, stroke_opacity=0.7, dissipating_time=0.8)
    t2 = TracedPath(lambda: hand(-1), stroke_color=PINK, stroke_width=4, stroke_opacity=0.7, dissipating_time=0.8)
    group = VGroup(rings, always_redraw(build))
    group.trails = [t1, t2]
    return group


def spin_it(th_tr, r_tr):
    th_tr.add_updater(lambda m, dt: m.increment_value(omega_of(r_tr.get_value()) * dt))


def readout(tex, fn, color, decimals=1, size=38):
    name = MathTex(tex + "=", font_size=size, color=color)
    num = DecimalNumber(fn(), num_decimal_places=decimals, font_size=size, color=color)
    num.next_to(name, RIGHT, buff=0.15)
    num.add_updater(lambda m: m.set_value(fn()))
    return VGroup(name, num)
'''

HOOK = '''
class Main(Scene):
    def construct(self):
        self.add(backdrop())
        r_tr = ValueTracker(3 ** 0.5)
        th_tr = ValueTracker(0.0)
        spin_it(th_tr, r_tr)
        sk = skater(r_tr, th_tr, center=DOWN * 0.1)
        caption = lab("arms out", 34, MUTED).move_to(UP * 2.4)

        at(self, 0)
        self.add(th_tr)
        self.add(*sk.trails)
        self.play(FadeIn(sk), FadeIn(caption), run_time=1.0)

        at(self, 1)
        self.play(
            r_tr.animate.set_value(1.0),
            Transform(caption, lab("arms in", 34, ORANGE).move_to(UP * 2.4)),
            run_time=1.6, rate_func=smooth,
        )
        fast = lab("much faster!", 34, ORANGE).move_to(UP * 1.8)
        self.play(FadeIn(fast, shift=UP * 0.2), run_time=0.6)

        at(self, 2)
        nopush = VGroup(
            lab("no push", 32, PINK), lab("no motor", 32, PINK)
        ).arrange(DOWN, buff=0.25).move_to(RIGHT * 4.6 + UP * 0.9)
        cross = VGroup(*[Cross(t, stroke_color=PINK, stroke_width=5, scale_factor=1.0) for t in nopush])
        self.play(FadeIn(nopush), run_time=0.6)
        self.play(Create(cross), run_time=0.8)

        at(self, 3)
        q = Text("?", font_size=140, color=YELLOW).move_to(RIGHT * 4.6 + DOWN * 1.0)
        self.play(FadeOut(nopush), FadeOut(cross), FadeIn(q, scale=0.5), run_time=0.7)
        self.play(Indicate(q, scale_factor=1.3, color=YELLOW), run_time=1.0)

        at(self, 4)
        self.remove(*sk.trails)
        self.play(FadeOut(sk), FadeOut(caption), FadeOut(fast), FadeOut(q), run_time=0.6)
        names = [("momentum", BLUE), ("torque", ORANGE), ("angular momentum", GREEN)]
        cards = VGroup(*[
            VGroup(
                RoundedRectangle(corner_radius=0.2, width=4.4, height=1.3, color=c, fill_color=PANEL, fill_opacity=1),
                lab(n, 30, c),
            )
            for n, c in names
        ]).arrange(RIGHT, buff=0.7).move_to(ORIGIN)
        arrows = VGroup(*[
            Arrow(cards[k].get_right(), cards[k + 1].get_left(), buff=0.1, color=MUTED, stroke_width=4)
            for k in range(2)
        ])
        gap = (span(4) - 0.6) / 3
        for k in range(3):
            anims = [FadeIn(cards[k], shift=UP * 0.3)]
            if k:
                anims.append(GrowArrow(arrows[k - 1]))
            self.play(*anims, run_time=min(0.8, gap))
            hold(self, gap - 0.8)

        at(self, 5)
        self.play(Indicate(cards[0], color=BLUE, scale_factor=1.12), run_time=1.0)
        self.wait(0.3)
        self.play(FadeOut(cards), FadeOut(arrows), run_time=0.5)
        finish(self)
'''

MOMENTUM = '''
def cart(x_tr, y, w, h, color, tag):
    def build():
        x = x_tr.get_value()
        body = RoundedRectangle(corner_radius=0.14, width=w, height=h, color=color, fill_color=color, fill_opacity=0.45, stroke_width=4)
        body.move_to([x, y + h / 2 + 0.16, 0])
        top = RoundedRectangle(corner_radius=0.07, width=w * 0.8, height=0.09, stroke_width=0, fill_color=WHITE, fill_opacity=0.35)
        top.move_to([x, y + h + 0.06, 0])
        wheels = VGroup(*[
            VGroup(Circle(radius=0.16, color=INK, fill_color=GREY_E, fill_opacity=1, stroke_width=3), Dot(radius=0.04, color=INK)).move_to([x + s * w * 0.3, y + 0.16, 0])
            for s in (-1, 1)
        ])
        t = Text(tag, font_size=24, color=WHITE).move_to(body)
        return VGroup(body, top, wheels, t)
    return always_redraw(build)


def vec(x_tr, y, val_fn, scale, color, dy=0.0):
    """An arrow above a cart, long in proportion to a value that can change sign."""
    def build():
        v = val_fn() * scale
        x = x_tr.get_value()
        if abs(v) < 0.04:
            return nothing()
        return Arrow([x, y + dy, 0], [x + v, y + dy, 0], buff=0, color=color, stroke_width=7, max_tip_length_to_length_ratio=0.35)
    return always_redraw(build)


class Main(Scene):
    def construct(self):
        self.add(backdrop())
        ground = Line([-6.8, -1.5, 0], [6.8, -1.5, 0], color=MUTED, stroke_width=3)
        self.add(ground)

        # 1. one block, p = m v
        x = ValueTracker(-5.0)
        v = ValueTracker(0.0)
        x.add_updater(lambda m, dt: m.increment_value(v.get_value() * dt))
        self.add(x, v)
        blk = cart(x, -1.5, 1.4, 0.9, BLUE, "m")
        at(self, 0)
        self.play(FadeIn(blk), run_time=0.8)

        at(self, 1)
        eq = MathTex(r"\\vec p", "=", "m", r"\\vec v", font_size=64).move_to(UP * 2.3)
        eq[0].set_color(ORANGE)
        eq[2].set_color(BLUE)
        eq[3].set_color(GREEN)
        varrow = vec(x, -1.5, v.get_value, 1.0, GREEN, dy=1.7)
        self.add(varrow)
        self.play(Write(eq), v.animate.set_value(0.9), run_time=1.6)

        at(self, 2)
        parrow = vec(x, -1.5, lambda: v.get_value() * 2.0, 1.0, ORANGE, dy=1.5)
        vl = MathTex(r"\\vec v", color=GREEN, font_size=34)
        pl = MathTex(r"\\vec p", color=ORANGE, font_size=34)
        vl.add_updater(lambda m: m.move_to([x.get_value() + (0.9 if v.get_value() >= 0 else -0.9) * 0.5, -1.5 + 2.0, 0]))
        pl.add_updater(lambda m: m.move_to([x.get_value() + (1.8 if v.get_value() >= 0 else -1.8) * 0.5, -1.5 + 1.5, 0]))
        self.add(parrow)
        self.play(FadeIn(vl), FadeIn(pl), run_time=0.6)
        self.wait(1.2)
        self.play(v.animate.set_value(-0.9), run_time=1.2)
        self.wait(0.6)

        # 2. truck and bicycle at the same speed
        at(self, 3)
        v.set_value(0.0)
        self.play(*[FadeOut(m) for m in (blk, varrow, parrow, vl, pl, eq)], run_time=0.6)
        x.set_value(-5.0)
        x2 = ValueTracker(-5.0)
        x2.add_updater(lambda m, dt: m.increment_value(v.get_value() * dt))
        self.add(x2)
        ground2 = Line([-6.8, 1.0, 0], [6.8, 1.0, 0], color=MUTED, stroke_width=3)
        bike2 = cart(x2, 1.0, 1.9, 0.5, ORANGE, "bike m=1")
        bike_p = vec(x2, 1.0, lambda: v.get_value() * 1.0, 0.55, ORANGE, dy=0.95)
        v_b = vec(x2, 1.0, v.get_value, 1.0, GREEN, dy=1.35)
        truck = cart(x, -1.5, 2.4, 1.0, BLUE, "truck  m = 4")
        truck_p = vec(x, -1.5, lambda: v.get_value() * 4.0, 0.55, ORANGE, dy=1.5)
        v_t = vec(x, -1.5, v.get_value, 1.0, GREEN, dy=1.95)
        self.play(FadeIn(ground2), FadeIn(truck), FadeIn(bike2), run_time=0.6)
        self.add(truck_p, bike_p, v_t, v_b)
        key = VGroup(
            Arrow(ORIGIN, RIGHT * 0.6, buff=0, color=GREEN, stroke_width=6), lab("velocity (same)", 24, GREEN),
            Arrow(ORIGIN, RIGHT * 0.6, buff=0, color=ORANGE, stroke_width=6), lab("momentum", 24, ORANGE),
        )
        key[0:2].arrange(RIGHT, buff=0.2)
        key[2:4].arrange(RIGHT, buff=0.2)
        key.arrange(RIGHT, buff=0.7).move_to(UP * 2.75)
        self.play(FadeIn(key), v.animate.set_value(0.7), run_time=1.0)
        hold(self, span(3) - 2.4)
        self.play(v.animate.set_value(0.0), run_time=0.6)

        # 3. a collision
        at(self, 4)
        self.play(*[FadeOut(m) for m in (truck, bike2, truck_p, bike_p, v_t, v_b, ground2, key)], run_time=0.5)
        xa = ValueTracker(-4.0)
        xb = ValueTracker(1.5)
        va = ValueTracker(0.7)
        vb = ValueTracker(-0.35)
        wa, wb = 1.9, 1.5
        state = {"hit": False}

        def step(m, dt):
            xa.increment_value(va.get_value() * dt)
            xb.increment_value(vb.get_value() * dt)
            if not state["hit"] and xa.get_value() + wa / 2 >= xb.get_value() - wb / 2:
                state["hit"] = True
                va.set_value(0.0)
                vb.set_value(1.05)

        stepper = Mobject()
        stepper.add_updater(step)
        self.add(stepper)
        a = cart(xa, -1.5, wa, 0.9, BLUE, "A: m=2")
        b = cart(xb, -1.5, wb, 0.7, ORANGE, "B: m=1")
        pa = vec(xa, -1.5, lambda: va.get_value() * 2.0, 1.1, BLUE, dy=1.3)
        pb = vec(xb, -1.5, lambda: vb.get_value() * 1.0, 1.1, ORANGE, dy=1.3)
        before = MathTex(r"\\text{before: } p_A + p_B = 1.4 + (-0.35) = 1.05", font_size=34, color=INK)
        before.move_to(UP * 2.4 + LEFT * 0.5)
        self.play(FadeIn(a), FadeIn(b), FadeIn(pa), FadeIn(pb), FadeIn(before), run_time=0.6)

        at(self, 5)
        after = MathTex(r"\\text{after: } p_A + p_B = 0 + 1.05 = 1.05", font_size=34, color=INK)
        after.next_to(before, DOWN, buff=0.3, aligned_edge=LEFT)
        hold(self, 4.2 - (self.time - B[4]))
        self.play(FadeIn(after, shift=UP * 0.2), run_time=0.8)

        at(self, 6)
        eqs = MathTex(r"p_{\\text{before}} = p_{\\text{after}}", font_size=52, color=YELLOW).move_to(DOWN * 2.6)
        self.play(Write(eqs), run_time=1.0)
        self.play(Circumscribe(eqs, color=YELLOW), run_time=1.2)

        # 4. F = dp/dt
        at(self, 7)
        self.play(*[FadeOut(m) for m in (a, b, pa, pb, before, after, eqs, ground)], run_time=0.6)
        stepper.clear_updaters()
        xc = ValueTracker(-3.0)
        ground3 = Line([-6.8, -1.5, 0], [6.8, -1.5, 0], color=MUTED, stroke_width=3)
        blk3 = cart(xc, -1.5, 1.4, 0.9, BLUE, "m")
        push = always_redraw(lambda: Arrow([xc.get_value() - 2.1, -0.6, 0], [xc.get_value() - 0.8, -0.6, 0], buff=0, color=GREEN, stroke_width=9))
        ptr = ValueTracker(0.0)
        ptr.add_updater(lambda m, dt: m.increment_value(dt))
        self.add(ptr)
        xc.add_updater(lambda m, dt: m.set_value(-3.0 + 0.15 * ptr.get_value() ** 2))
        p_arrow = always_redraw(lambda: Arrow([xc.get_value(), 0.8, 0], [xc.get_value() + 0.45 * ptr.get_value(), 0.8, 0], buff=0, color=ORANGE, stroke_width=9) if ptr.get_value() > 0.15 else nothing())
        fl = MathTex(r"\\vec F", color=GREEN, font_size=38).add_updater(lambda m: m.move_to([xc.get_value() - 1.45, -0.05, 0]))
        pl3 = MathTex(r"\\vec p", color=ORANGE, font_size=38).add_updater(lambda m: m.move_to([xc.get_value() - 0.3, 1.3, 0]))
        law = MathTex(r"\\vec F", "=", r"\\frac{d\\vec p}{dt}", font_size=76).move_to(UP * 2.3 + RIGHT * 3.4)
        law[0].set_color(GREEN)
        law[2].set_color(ORANGE)
        self.play(FadeIn(ground3), FadeIn(blk3), FadeIn(push), FadeIn(fl), FadeIn(pl3), run_time=0.5)
        self.add(p_arrow)
        self.play(Write(law), run_time=1.2)
        self.play(Circumscribe(law, color=YELLOW), run_time=1.2)
        finish(self)
'''

TORQUE = '''
PIV = np.array([-3.6, -0.7, 0.0])
FMAG = 2.0


def tau_of(r, th):
    return r * FMAG * np.sin(th)


class Main(Scene):
    def construct(self):
        self.add(backdrop())
        r_tr = ValueTracker(4.0)
        th_tr = ValueTracker(PI / 2)

        wrench = VGroup(
            RoundedRectangle(corner_radius=0.17, width=6.2, height=0.38, color=GREY_B, fill_color=GREY_D, fill_opacity=1, stroke_width=3),
        )
        wrench[0].move_to(PIV + RIGHT * 2.7)
        bolt = RegularPolygon(6, radius=0.5, color=YELLOW, fill_color=GREY_E, fill_opacity=1, stroke_width=5).move_to(PIV)
        hole = Circle(radius=0.17, color=GREY_B, stroke_width=3).move_to(PIV)

        def point():
            return PIV + RIGHT * r_tr.get_value()

        def fvec():
            th = th_tr.get_value()
            return np.array([np.cos(th), np.sin(th), 0.0]) * FMAG * 0.85

        r_arrow = always_redraw(lambda: Arrow(PIV + DOWN * 0.55, point() + DOWN * 0.55, buff=0, color=BLUE, stroke_width=6))
        r_lab = MathTex(r"r", color=BLUE, font_size=40)
        r_lab.add_updater(lambda m: m.move_to((PIV + point()) / 2 + DOWN * 0.95))
        f_arrow = always_redraw(lambda: Arrow(point(), point() + fvec(), buff=0, color=ORANGE, stroke_width=8, max_tip_length_to_length_ratio=0.3) if FMAG > 0 else nothing())
        f_lab = MathTex(r"\\vec F", color=ORANGE, font_size=40)
        f_lab.add_updater(lambda m: m.move_to(point() + fvec() * 1.0 + (UP * 0.35 if np.sin(th_tr.get_value()) > 0.3 else RIGHT * 0.45)))

        def arc():
            th = th_tr.get_value()
            if th < 0.04:
                return nothing()
            return Arc(radius=0.75, start_angle=0, angle=th, arc_center=point(), color=PINK, stroke_width=5)

        theta_arc = always_redraw(arc)
        theta_lab = MathTex(r"\\theta", color=PINK, font_size=38)
        theta_lab.add_updater(lambda m: m.move_to(point() + 1.1 * np.array([np.cos(th_tr.get_value() / 2), np.sin(th_tr.get_value() / 2), 0]) if th_tr.get_value() > 0.12 else point() + RIGHT * 5))

        def spin_hint():
            tau = tau_of(r_tr.get_value(), th_tr.get_value())
            o = min(1.0, abs(tau) / 8.0) * 0.95
            if o < 0.03:
                return nothing()
            return Arc(radius=0.95, start_angle=0.4, angle=2.4, arc_center=PIV, color=YELLOW, stroke_width=5, stroke_opacity=o).add_tip(tip_length=0.22)

        hint = always_redraw(spin_hint)

        at(self, 0)
        left = VGroup(lab("force", 34, ORANGE), lab("straight-line motion", 28, MUTED)).arrange(DOWN, buff=0.15)
        right = VGroup(lab("torque", 34, YELLOW), lab("rotation", 28, MUTED)).arrange(DOWN, buff=0.15)
        pair = VGroup(left, Text("→", font_size=1), right)
        pair = VGroup(left, right).arrange(RIGHT, buff=2.2).move_to(RIGHT * 3.6 + UP * 1.6)
        self.play(FadeIn(left, shift=RIGHT * 0.2), run_time=0.8)
        self.wait(1.2)
        self.play(FadeIn(right, shift=LEFT * 0.2), run_time=0.8)

        at(self, 1)
        self.play(FadeIn(wrench), FadeIn(bolt), FadeIn(hole), run_time=0.9)
        self.add(f_arrow, f_lab)
        self.play(FadeIn(f_arrow), FadeIn(f_lab), run_time=0.7)
        self.add(hint)

        at(self, 2)
        self.play(FadeOut(pair), run_time=0.4)
        eq1 = MathTex(r"\\vec\\tau", "=", r"\\vec r", r"\\times", r"\\vec F", font_size=62).move_to(RIGHT * 3.9 + UP * 2.4)
        eq1[0].set_color(YELLOW)
        eq1[2].set_color(BLUE)
        eq1[4].set_color(ORANGE)
        self.add(r_arrow, r_lab)
        self.play(FadeIn(r_arrow), FadeIn(r_lab), Write(eq1), run_time=1.4)

        at(self, 3)
        eq2 = MathTex(r"\\tau", "=", "r", "F", r"\\sin\\theta", font_size=62).next_to(eq1, DOWN, buff=0.45)
        eq2[0].set_color(YELLOW)
        eq2[2].set_color(BLUE)
        eq2[3].set_color(ORANGE)
        eq2[4].set_color(PINK)
        self.add(theta_arc, theta_lab)
        self.play(Write(eq2), FadeIn(theta_arc), FadeIn(theta_lab), run_time=1.4)
        tau_ro = readout(r"\\tau", lambda: tau_of(r_tr.get_value(), th_tr.get_value()), YELLOW, 1, 40)
        r_ro = readout(r"r", lambda: r_tr.get_value(), BLUE, 1, 34)
        th_ro = readout(r"\\theta", lambda: np.degrees(th_tr.get_value()), PINK, 0, 34)
        stack = VGroup(r_ro, th_ro, tau_ro).arrange(DOWN, buff=0.3, aligned_edge=LEFT).move_to(RIGHT * 4.3 + DOWN * 1.0)
        self.play(FadeIn(stack), run_time=0.6)

        at(self, 4)
        gap = span(4) / 2
        self.play(r_tr.animate.set_value(1.2), run_time=gap * 0.9, rate_func=smooth)
        self.wait(0.1)
        self.play(r_tr.animate.set_value(4.0), run_time=gap * 0.9, rate_func=smooth)

        at(self, 5)
        self.play(th_tr.animate.set_value(0.0), run_time=span(5) * 0.45, rate_func=smooth)
        zero = lab("no torque", 30, PINK).move_to(RIGHT * 4.3 + DOWN * 2.6)
        self.play(FadeIn(zero), run_time=0.4)
        self.wait(0.5)

        at(self, 6)
        self.play(FadeOut(zero), th_tr.animate.set_value(PI / 3), run_time=1.0, rate_func=smooth)
        fperp = always_redraw(lambda: DashedLine(point(), point() + UP * FMAG * 0.85 * np.sin(th_tr.get_value()), color=GREEN, stroke_width=6))
        fpar = always_redraw(lambda: DashedLine(point(), point() + RIGHT * FMAG * 0.85 * np.cos(th_tr.get_value()), color=GREY_B, stroke_width=5))
        fl_perp = MathTex(r"F\\sin\\theta", color=GREEN, font_size=34)
        fl_perp.add_updater(lambda m: m.move_to(point() + LEFT * 0.95 + UP * FMAG * 0.85 * np.sin(th_tr.get_value()) * 0.5))
        self.add(fperp, fpar, fl_perp)
        self.play(FadeIn(fperp), FadeIn(fpar), FadeIn(fl_perp), run_time=0.7)
        self.play(Indicate(fperp, color=GREEN, scale_factor=1.15), run_time=1.0)

        at(self, 7)
        sym = VGroup(Circle(radius=0.38, color=YELLOW, stroke_width=5), Dot(radius=0.1, color=YELLOW))
        sym.move_to(PIV + UP * 2.5 + RIGHT * 0.2)
        sl = VGroup(lab("τ points out of the screen", 26, YELLOW), lab("(right-hand rule)", 22, MUTED)).arrange(DOWN, buff=0.1)
        sl.next_to(sym, RIGHT, buff=0.35)
        self.play(FadeIn(sym, scale=0.5), FadeIn(sl), run_time=0.9)
        finish(self)
'''

INERTIA = '''
M = 1.0
TAU = 0.35


class Main(Scene):
    def construct(self):
        self.add(backdrop())
        rA, rB = 0.5, 1.5
        K = 0.95  # display scale
        cA = np.array([-4.4, 0.0, 0.0])
        cB = np.array([-0.4, 0.0, 0.0])
        thA = ValueTracker(0.0)
        thB = ValueTracker(0.0)
        wA = ValueTracker(0.0)
        wB = ValueTracker(0.0)
        IA = 2 * M * rA ** 2
        IB = 2 * M * rB ** 2
        torque_on = {"on": False}

        def stepA(m, dt):
            if torque_on["on"]:
                wA.increment_value(TAU / IA * dt)
                wB.increment_value(TAU / IB * dt)
            thA.increment_value(wA.get_value() * dt)
            thB.increment_value(wB.get_value() * dt)

        driver = Mobject()
        driver.add_updater(stepA)

        def dumbbell(c, r, th_tr, color):
            def build():
                th = th_tr.get_value()
                d = np.array([np.cos(th), np.sin(th), 0.0])
                rod = Line(c - d * 1.6 * K, c + d * 1.6 * K, color=GREY_B, stroke_width=6)
                m1 = Dot(c + d * r * K * 1.0, radius=0.2, color=color)
                m2 = Dot(c - d * r * K * 1.0, radius=0.2, color=color)
                hub = Dot(c, radius=0.07, color=WHITE)
                return VGroup(rod, m1, m2, hub)
            return always_redraw(build)

        dA = dumbbell(cA, rA, thA, ORANGE)
        dB = dumbbell(cB, rB, thB, BLUE)
        nameA = lab("masses near the axis", 24, ORANGE).move_to(cA + DOWN * 1.9)
        nameB = lab("masses far from the axis", 24, BLUE).move_to(cB + DOWN * 1.9)

        at(self, 0)
        self.add(driver)
        i_lab = MathTex("I", font_size=110, color=YELLOW).move_to(RIGHT * 4.4 + UP * 1.2)
        sub = lab("rotational mass", 30, MUTED).next_to(i_lab, DOWN, buff=0.2)
        self.play(FadeIn(dA), FadeIn(dB), FadeIn(nameA), FadeIn(nameB), run_time=0.9)
        self.play(Write(i_lab), FadeIn(sub), run_time=1.2)

        at(self, 1)
        self.play(FadeOut(sub), i_lab.animate.scale(0.5).move_to(RIGHT * 4.4 + UP * 2.6), run_time=0.5)
        eq = MathTex("I", "=", r"\\sum", "m_i", "r_i", "^2", font_size=62).move_to(RIGHT * 4.4 + UP * 1.2)
        eq[0].set_color(YELLOW)
        eq[3].set_color(ORANGE)
        eq[4].set_color(BLUE)
        self.play(Write(eq), FadeOut(i_lab), run_time=1.3)
        # radius braces
        ra = Line(cA, cA + RIGHT * rA * K, color=WHITE, stroke_width=4).shift(UP * 0.55)
        rb = Line(cB, cB + RIGHT * rB * K, color=WHITE, stroke_width=4).shift(UP * 0.55)
        ra_l = MathTex(r"r", font_size=30).next_to(ra, UP, buff=0.08)
        rb_l = MathTex(r"r", font_size=30).next_to(rb, UP, buff=0.08)
        self.play(Create(ra), Create(rb), FadeIn(ra_l), FadeIn(rb_l), run_time=0.8)

        at(self, 2)
        ia = MathTex(r"I_A=2\\cdot 1\\cdot 0.5^2 = 0.5", font_size=34, color=ORANGE).move_to(RIGHT * 4.4 + UP * -0.1)
        ib = MathTex(r"I_B=2\\cdot 1\\cdot 1.5^2 = 4.5", font_size=34, color=BLUE).next_to(ia, DOWN, buff=0.25, aligned_edge=LEFT)
        nine = lab("3× farther  →  9× harder to spin", 26, YELLOW).next_to(ib, DOWN, buff=0.4)
        self.play(FadeIn(ia, shift=UP * 0.15), run_time=0.7)
        self.play(FadeIn(ib, shift=UP * 0.15), run_time=0.7)
        self.play(FadeIn(nine), run_time=0.7)

        at(self, 3)
        self.play(*[FadeOut(m) for m in (ra, rb, ra_l, rb_l, ia, ib, nine, eq)], run_time=0.5)
        law = MathTex(r"\\tau", "=", "I", r"\\alpha", font_size=76).move_to(RIGHT * 4.4 + UP * 1.3)
        law[0].set_color(YELLOW)
        law[2].set_color(GREEN)
        law[3].set_color(PINK)
        note = lab("same torque on both", 28, YELLOW).next_to(law, DOWN, buff=0.4)
        note2 = lab("α = angular acceleration", 24, PINK).next_to(note, DOWN, buff=0.3)
        self.play(Write(law), FadeIn(note), run_time=1.2)
        torque_on["on"] = True
        self.play(FadeIn(note2), run_time=0.6)
        hold(self, B[4] - self.time - 0.9)
        torque_on["on"] = False
        wA.set_value(0.0)
        wB.set_value(0.0)

        at(self, 4)
        driver.clear_updaters()
        self.play(*[FadeOut(m) for m in (dA, dB, nameA, nameB, law, note, note2)], run_time=0.6)
        head_l = lab("Linear", 34, BLUE).move_to(LEFT * 3.6 + UP * 2.45)
        head_r = lab("Rotational", 34, GREEN).move_to(RIGHT * 3.6 + UP * 2.45)
        rows = [
            ("position", "x", "angle", r"\\theta"),
            ("velocity", "v", "angular velocity", r"\\omega"),
            ("mass", "m", "moment of inertia", "I"),
            ("force", r"F", "torque", r"\\tau"),
            ("momentum", "p", "angular momentum", "L"),
        ]
        self.play(FadeIn(head_l), FadeIn(head_r), run_time=0.5)
        step = (span(4) - 0.9) / 5
        group = VGroup()
        for k, (n1, s1, n2, s2) in enumerate(rows):
            y = 1.45 - k * 0.8
            left = VGroup(lab(n1, 26, INK), MathTex(s1, font_size=48, color=BLUE)).arrange(RIGHT, buff=0.3).move_to(LEFT * 3.6 + UP * y)
            rght = VGroup(lab(n2, 26, INK), MathTex(s2, font_size=48, color=GREEN)).arrange(RIGHT, buff=0.3).move_to(RIGHT * 3.6 + UP * y)
            ar = MathTex(r"\\longleftrightarrow", font_size=44, color=MUTED).move_to(UP * y)
            row = VGroup(left, ar, rght)
            group.add(row)
            self.play(FadeIn(row, shift=UP * 0.15), run_time=min(0.6, step))
            hold(self, step - 0.6)
        self.play(Indicate(group[4], color=YELLOW, scale_factor=1.08), run_time=0.9)
        finish(self)
'''

ANGULAR = '''
class Main(Scene):
    def construct(self):
        self.add(backdrop())
        C = np.array([-3.3, -0.1, 0.0])
        R = 1.9
        phi = ValueTracker(0.0)
        phi.add_updater(lambda m, dt: m.increment_value(0.75 * dt))
        self.add(phi)

        def pos():
            return C + R * np.array([np.cos(phi.get_value()), np.sin(phi.get_value()), 0.0])

        def tang():
            return np.array([-np.sin(phi.get_value()), np.cos(phi.get_value()), 0.0])

        circle = Circle(radius=R, color=GREY_C, stroke_width=2).move_to(C)
        centre = Dot(C, radius=0.08, color=WHITE)
        planet = always_redraw(lambda: Dot(pos(), radius=0.2, color=ORANGE))
        r_arrow = always_redraw(lambda: Arrow(C, pos(), buff=0.0, color=BLUE, stroke_width=6, max_tip_length_to_length_ratio=0.15))
        p_arrow = always_redraw(lambda: Arrow(pos(), pos() + tang() * 1.3, buff=0.0, color=ORANGE, stroke_width=7, max_tip_length_to_length_ratio=0.3))
        r_l = MathTex(r"\\vec r", color=BLUE, font_size=38)
        r_l.add_updater(lambda m: m.move_to(C + (pos() - C) * 0.5 + (pos() - C) / R * -0.4 + tang() * 0.3))
        p_l = MathTex(r"\\vec p", color=ORANGE, font_size=38)
        p_l.add_updater(lambda m: m.move_to(pos() + tang() * 1.65))

        at(self, 0)
        self.play(FadeIn(circle), FadeIn(centre), FadeIn(planet), run_time=0.8)
        self.add(r_arrow, p_arrow)
        self.play(FadeIn(r_arrow), FadeIn(p_arrow), FadeIn(r_l), FadeIn(p_l), run_time=0.8)

        at(self, 1)
        eq = MathTex(r"\\vec L", "=", r"\\vec r", r"\\times", r"\\vec p", font_size=70).move_to(RIGHT * 3.9 + UP * 2.2)
        eq[0].set_color(YELLOW)
        eq[2].set_color(BLUE)
        eq[4].set_color(ORANGE)
        sym = VGroup(Circle(radius=0.3, color=YELLOW, stroke_width=5), Dot(radius=0.08, color=YELLOW))
        sym.move_to(C + UP * 0.0)
        sym_l = MathTex(r"\\vec L", color=YELLOW, font_size=34).move_to(C + DOWN * 2.55 + LEFT * 0.9)
        sym_n = lab("= out of the screen", 22, YELLOW).next_to(sym_l, RIGHT, buff=0.15)
        self.play(Write(eq), run_time=1.4)
        self.play(FadeIn(sym), FadeIn(sym_l), FadeIn(sym_n), run_time=0.8)

        at(self, 2)
        steps = MathTex(
            r"L = m\\,r\\,(r\\omega)", r"= m r^2\\omega", r"= I\\omega", font_size=40, color=INK
        )
        steps = VGroup(
            MathTex(r"p = m v = m\\,(r\\omega)", font_size=40),
            MathTex(r"L = r\\,p = m r^2\\,\\omega", font_size=40),
        ).arrange(DOWN, buff=0.3, aligned_edge=LEFT).next_to(eq, DOWN, buff=0.5)
        final = MathTex(r"L", "=", "I", r"\\omega", font_size=84).next_to(steps, DOWN, buff=0.5)
        final[0].set_color(YELLOW)
        final[2].set_color(GREEN)
        final[3].set_color(PINK)
        self.play(FadeIn(steps[0], shift=UP * 0.15), run_time=0.8)
        self.play(FadeIn(steps[1], shift=UP * 0.15), run_time=0.8)
        self.play(Write(final), run_time=1.0)
        self.play(Circumscribe(final, color=YELLOW), run_time=1.0)

        at(self, 3)
        self.play(*[FadeOut(m) for m in (circle, centre, planet, r_arrow, p_arrow, r_l, p_l, sym, sym_l, sym_n, eq, steps, final)], run_time=0.6)
        phi.clear_updaters()
        spin = ValueTracker(0.0)
        spin.add_updater(lambda m, dt: m.increment_value(dt))
        self.add(spin)
        xs = [-4.4, 0.0, 4.4]
        sun = Dot(radius=0.28, color=YELLOW).move_to(RIGHT * xs[0])
        orbit = Circle(radius=1.3, color=GREY_C, stroke_width=2).move_to(RIGHT * xs[0])
        planet2 = always_redraw(lambda: Dot(RIGHT * xs[0] + 1.3 * np.array([np.cos(0.9 * spin.get_value()), np.sin(0.9 * spin.get_value()), 0]), radius=0.15, color=BLUE))
        wheel_c = RIGHT * xs[1]
        wheel = always_redraw(lambda: VGroup(
            Circle(radius=1.2, color=INK, stroke_width=6).move_to(wheel_c),
            *[Line(wheel_c, wheel_c + 1.2 * np.array([np.cos(2 * spin.get_value() + k * PI / 3), np.sin(2 * spin.get_value() + k * PI / 3), 0]), color=GREY_B, stroke_width=4) for k in range(6)],
            Dot(wheel_c, radius=0.1, color=INK),
        ))
        top_c = RIGHT * xs[2]
        top = always_redraw(lambda: Star(n=5, outer_radius=1.2, inner_radius=0.55, color=PINK, fill_color=PINK, fill_opacity=0.35, stroke_width=5).rotate(3 * spin.get_value()).move_to(top_c))
        names = [lab("planet", 28, MUTED).move_to(RIGHT * xs[0] + DOWN * 2.1), lab("wheel", 28, MUTED).move_to(RIGHT * xs[1] + DOWN * 2.1), lab("spinning top", 28, MUTED).move_to(RIGHT * xs[2] + DOWN * 2.1)]
        self.add(planet2, wheel, top)
        self.play(FadeIn(sun), FadeIn(orbit), FadeIn(planet2), run_time=0.7)
        self.play(FadeIn(wheel), FadeIn(names[0]), FadeIn(names[1]), run_time=0.7)
        self.play(FadeIn(top), FadeIn(names[2]), run_time=0.7)
        self.wait(1.0)

        at(self, 4)
        self.play(*[FadeOut(m) for m in (sun, orbit, planet2, wheel, top, *names)], run_time=0.6)
        spin.clear_updaters()
        D = np.array([-2.6, -0.9, 0.0])
        ph = ValueTracker(0.0)
        ph.add_updater(lambda m, dt: m.increment_value(1.6 * dt))
        self.add(ph)
        disk = Ellipse(width=3.6, height=1.3, color=INK, fill_color=GREY_E, fill_opacity=0.8, stroke_width=5).move_to(D)
        marks = always_redraw(lambda: VGroup(*[
            Dot(D + np.array([1.8 * np.cos(ph.get_value() + k * PI / 2), 0.65 * np.sin(ph.get_value() + k * PI / 2), 0.0]), radius=0.1, color=[ORANGE, PINK, BLUE, GREEN][k])
            for k in range(4)
        ]))
        arrow_L = Arrow(D, D + UP * 3.0, buff=0.0, color=YELLOW, stroke_width=9)
        l_l = MathTex(r"\\vec L", color=YELLOW, font_size=48).next_to(arrow_L, RIGHT, buff=0.2)
        curl = CurvedArrow(D + np.array([1.9, -0.1, 0]), D + np.array([1.4, 0.75, 0]), angle=-PI / 2.4, color=GREEN, stroke_width=5)
        t1 = lab("curl your fingers the way it spins", 26, GREEN).move_to(RIGHT * 3.7 + UP * 1.0)
        t2 = lab("your thumb points along L", 26, YELLOW).next_to(t1, DOWN, buff=0.35)
        self.add(marks)
        self.play(FadeIn(disk), FadeIn(marks), run_time=0.7)
        self.play(FadeIn(t1), FadeIn(curl), run_time=0.9)
        hold(self, span(4) * 0.4 - 1.6)
        self.play(GrowArrow(arrow_L), FadeIn(l_l), FadeIn(t2), run_time=1.0)
        self.wait(0.4)

        at(self, 5)
        self.play(*[FadeOut(m) for m in (disk, marks, arrow_L, l_l, curl, t1, t2)], run_time=0.6)
        ph.clear_updaters()
        top_eq = MathTex(r"\\vec F", "=", r"\\frac{d\\vec p}{dt}", font_size=76).move_to(UP * 1.4)
        top_eq[0].set_color(GREEN)
        top_eq[2].set_color(ORANGE)
        bot_eq = MathTex(r"\\vec\\tau", "=", r"\\frac{d\\vec L}{dt}", font_size=76).move_to(DOWN * 1.2)
        bot_eq[0].set_color(YELLOW)
        bot_eq[2].set_color(YELLOW)
        arr = MathTex(r"\\Downarrow", font_size=60, color=MUTED).move_to(UP * 0.1)
        self.play(Write(top_eq), run_time=0.8)
        self.play(FadeIn(arr), Write(bot_eq), run_time=1.2)
        self.play(Circumscribe(bot_eq, color=YELLOW), run_time=1.0)
        finish(self)
'''

CONSERVATION = '''
class Main(Scene):
    def construct(self):
        self.add(backdrop())
        r_tr = ValueTracker(3 ** 0.5)
        th_tr = ValueTracker(0.0)
        spin_it(th_tr, r_tr)
        C = LEFT * 3.3 + UP * 0.3
        sk = skater(r_tr, th_tr, center=C, K=1.0)

        law = MathTex(r"\\vec\\tau_{\\text{ext}} = 0", r"\\;\\Longrightarrow\\;", r"\\vec L = \\text{constant}", font_size=50).move_to(UP * 2.5)
        law[0].set_color(PINK)
        law[2].set_color(YELLOW)

        I_ro = readout("I", lambda: inertia(r_tr.get_value()), GREEN, 1, 44)
        w_ro = readout(r"\\omega", lambda: omega_of(r_tr.get_value()), PINK, 1, 44)
        L_ro = readout("L", lambda: inertia(r_tr.get_value()) * omega_of(r_tr.get_value()), YELLOW, 1, 44)
        stack = VGroup(I_ro, w_ro, L_ro).arrange(DOWN, buff=0.45, aligned_edge=LEFT).move_to(RIGHT * 4.3 + DOWN * 0.1)
        box = SurroundingRectangle(stack, color=MUTED, buff=0.35, corner_radius=0.15, stroke_width=2, fill_color=PANEL, fill_opacity=0.9)
        units = lab("I in kg·m²,  ω in rad/s", 20, MUTED).next_to(box, DOWN, buff=0.15)

        at(self, 0)
        self.play(Write(law), run_time=1.6)
        self.play(Circumscribe(law[2], color=YELLOW), run_time=1.0)

        at(self, 1)
        self.add(th_tr)
        self.add(*sk.trails)
        self.play(FadeIn(sk), run_time=0.7)
        self.add(I_ro, w_ro, L_ro)
        self.play(FadeIn(stack), FadeIn(box), FadeIn(units), run_time=0.8)
        note1 = lab("arms out: big I, slow spin", 26, MUTED).move_to(C + DOWN * 2.2)
        self.play(FadeIn(note1), run_time=0.5)

        at(self, 2)
        note2 = lab("arms in: small I", 26, GREEN).move_to(C + DOWN * 2.2)
        self.play(r_tr.animate.set_value(1.0), Transform(note1, note2), run_time=span(2) * 0.9, rate_func=smooth)

        at(self, 3)
        self.play(Indicate(w_ro, color=PINK, scale_factor=1.15), Indicate(L_ro, color=YELLOW, scale_factor=1.1), run_time=1.4)
        self.play(Circumscribe(L_ro, color=YELLOW), run_time=1.1)

        at(self, 4)
        half = MathTex(r"I \\to \\tfrac12 I", r"\\;\\Rightarrow\\;", r"\\omega \\to 2\\omega", font_size=46).move_to(C + DOWN * 2.8)
        half[0].set_color(GREEN)
        half[2].set_color(PINK)
        self.play(Write(half), run_time=1.1)
        self.play(r_tr.animate.set_value(3 ** 0.5), run_time=1.2, rate_func=smooth)
        self.play(r_tr.animate.set_value(1.0), run_time=1.2, rate_func=smooth)

        # a planet on an eccentric orbit
        at(self, 5)
        self.remove(*sk.trails)
        self.play(*[FadeOut(m) for m in (sk, stack, box, units, law, note1, half)], run_time=0.6)
        th_tr.clear_updaters()
        S = np.array([-1.0, 0.0, 0.0])
        e, pp = 0.6, 2.0
        a_ = pp / (1 - e * e)
        h = 2 * PI * a_ * a_ * (1 - e * e) ** 0.5 / 8.0  # a period of 8 s
        ang = ValueTracker(0.0)

        def rr(t):
            return pp / (1 + e * np.cos(t))

        def stepper(m, dt):
            t = ang.get_value()
            ang.increment_value(h / rr(t) ** 2 * dt)

        ang.add_updater(stepper)
        self.add(ang)
        sun = Dot(S, radius=0.3, color=YELLOW)
        orbit = ParametricFunction(lambda t: S + rr(t) * np.array([np.cos(t), np.sin(t), 0.0]), t_range=[0, TAU], color=GREY_C, stroke_width=2)
        planet = always_redraw(lambda: Dot(S + rr(ang.get_value()) * np.array([np.cos(ang.get_value()), np.sin(ang.get_value()), 0.0]), radius=0.16, color=BLUE))
        trail = TracedPath(lambda: planet.get_center(), stroke_color=BLUE, stroke_width=4, dissipating_time=1.2)
        d_ro = readout("r", lambda: rr(ang.get_value()), GREEN, 2, 38)
        w2_ro = readout(r"\\dot\\theta", lambda: h / rr(ang.get_value()) ** 2, PINK, 2, 38)
        c_ro = readout(r"r^2\\dot\\theta", lambda: h, YELLOW, 2, 38)
        stack2 = VGroup(d_ro, w2_ro, c_ro).arrange(DOWN, buff=0.4, aligned_edge=LEFT).move_to(RIGHT * 4.6 + UP * 0.5)
        tuck = lab("a diver tucks: smaller I, faster spin", 24, MUTED).move_to(RIGHT * 3.8 + DOWN * 2.3)
        self.add(trail, planet, d_ro, w2_ro, c_ro)
        self.play(FadeIn(sun), FadeIn(orbit), FadeIn(planet), FadeIn(stack2), run_time=0.8)
        hold(self, span(5) - 3.5)
        self.play(FadeIn(tuck), run_time=0.7)
        finish(self)
'''

RECAP = '''
class Main(Scene):
    def construct(self):
        self.add(backdrop())
        specs = [
            ("Momentum", BLUE, r"\\vec p = m\\vec v", "motion in a straight line"),
            ("Torque", ORANGE, r"\\vec\\tau = \\vec r \\times \\vec F", "what makes things twist"),
            ("Angular momentum", GREEN, r"\\vec L = I\\vec\\omega", "spinning motion"),
        ]
        cards = []
        for k, (name, c, tex, sub) in enumerate(specs):
            frame = RoundedRectangle(corner_radius=0.25, width=4.0, height=3.6, color=c, fill_color=PANEL, fill_opacity=1, stroke_width=4)
            t = lab(name, 30, c).move_to(frame.get_top() + DOWN * 0.55)
            eq = MathTex(tex, font_size=50, color=INK).move_to(frame.get_center() + DOWN * 0.1)
            s = lab(sub, 22, MUTED).move_to(frame.get_bottom() + UP * 0.6)
            card = VGroup(frame, t, eq, s).move_to(RIGHT * (k - 1) * 4.5 + UP * 0.6)
            cards.append(card)

        at(self, 0)
        self.play(LaggedStart(*[FadeIn(c, shift=UP * 0.3) for c in cards], lag_ratio=0.35), run_time=1.6)

        at(self, 1)
        self.play(Indicate(cards[0][2], color=BLUE, scale_factor=1.25), run_time=1.4)

        at(self, 2)
        self.play(Indicate(cards[1][2], color=ORANGE, scale_factor=1.25), run_time=1.4)

        at(self, 3)
        self.play(Indicate(cards[2][2], color=GREEN, scale_factor=1.25), run_time=1.4)
        keep = lab("no torque  →  L never changes", 30, YELLOW).move_to(DOWN * 2.1)
        self.play(FadeIn(keep, shift=UP * 0.2), run_time=0.8)
        self.play(Circumscribe(keep, color=YELLOW), run_time=1.1)

        at(self, 4)
        self.play(*[FadeOut(c) for c in cards], FadeOut(keep), run_time=0.7)
        r_tr = ValueTracker(3 ** 0.5)
        th_tr = ValueTracker(0.0)
        spin_it(th_tr, r_tr)
        sk = skater(r_tr, th_tr, center=ORIGIN)
        self.add(th_tr)
        self.add(*sk.trails)
        self.play(FadeIn(sk), run_time=0.6)
        self.play(r_tr.animate.set_value(1.0), run_time=1.6, rate_func=smooth)
        self.wait(1.0)
        self.play(r_tr.animate.set_value(3 ** 0.5), run_time=1.6, rate_func=smooth)
        finish(self)
'''

CODE = {
    "hook": PRE + HOOK,
    "momentum": PRE + MOMENTUM,
    "torque": PRE + TORQUE,
    "inertia": PRE + INERTIA,
    "angular": PRE + ANGULAR,
    "conservation": PRE + CONSERVATION,
    "recap": PRE + RECAP,
}
