from manim import *

from smart_transform import SmartScene, smart_transform


class SmartTransformAlphabetComparison(SmartScene):
    def construct(self):
        letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        smart_label = Text("Smart Transform").scale(0.65).to_edge(UP).shift(3 * LEFT)
        manim_label = Text("Manim Transform").scale(0.65).to_edge(UP).shift(3 * RIGHT)
        self.add(smart_label, manim_label)

        for before, after in zip(letters, letters[1:]):
            smart_source = Text(before).scale(3).set_fill(opacity=1).set_stroke(BLUE, width=3)
            smart_target = Text(after).scale(3).set_fill(opacity=1).set_stroke(BLUE, width=3)
            manim_source = Text(before).scale(3).set_fill(opacity=1).set_stroke(BLUE, width=3)
            manim_target = Text(after).scale(3).set_fill(opacity=1).set_stroke(BLUE, width=3)
            smart_source.move_to(3 * LEFT)
            smart_target.move_to(3 * LEFT)
            manim_source.move_to(3 * RIGHT)
            manim_target.move_to(3 * RIGHT)

            animation, smart_start, smart_end = smart_transform(
                smart_source, smart_target, run_time=3
            )
            if smart_start is not smart_source:
                self.remove(smart_source)
                self.add(smart_start)
            self.add(manim_source)
            self.play(animation, Transform(manim_source, manim_target), run_time=3)
            if smart_end is not smart_target:
                self.remove(smart_end)
                self.add(smart_target)
            self.wait()
            self.remove(smart_target, manim_source, manim_target)
