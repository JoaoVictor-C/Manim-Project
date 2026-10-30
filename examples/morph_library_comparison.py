"""Compare Manim, SmartMorph, Polymorph, and Flubber on text and SVG silhouettes."""

from manim import *
from flubber.manim import FlubberTransform
from manim_polymorph import Polymorph, svg_path_mobject

from smart_transform import smart_transform


SVG_PATHS = {
    "leaf": "M50,4 C74,17 95,37 89,59 C83,82 60,96 34,89 C11,83 3,60 12,39 C20,21 37,9 50,4 Z",
    "heart": "M50,91 C41,81 8,55 8,31 C8,7 39,1 50,23 C61,1 92,7 92,31 C92,55 59,81 50,91 Z",
    "bolt": "M57,4 L17,54 L43,54 L35,96 L84,37 L56,39 Z",
    "flower": "M50,4 C60,4 63,19 65,27 C72,17 83,10 90,17 C97,24 90,36 83,43 C94,42 98,53 92,61 C86,69 73,64 66,60 C72,70 73,84 63,89 C53,94 46,82 44,72 C39,84 28,93 19,87 C10,81 17,68 23,61 C10,64 1,57 6,47 C11,37 24,39 34,42 C26,33 23,20 32,14 C41,8 48,19 50,29 C53,18 56,4 50,4 Z",
}
LANE_X = [-5.25, -1.75, 1.75, 5.25]


def silhouette(name: str, center=ORIGIN) -> VMobject:
    return svg_path_mobject(
        SVG_PATHS[name],
        height=2.0,
        fill_color=BLUE,
        fill_opacity=0.75,
        stroke_color=WHITE,
        stroke_width=2,
    ).move_to(center)


def headings() -> VGroup:
    labels = ["Manim Transform", "SmartMorph", "Polymorph", "Flubber"]
    group = VGroup(*(Text(label, font_size=20) for label in labels))
    for label, x in zip(group, LANE_X):
        label.move_to([x, 2.35, 0])
    return group


class MorphLibraryComparison(Scene):
    def construct(self):
        self.phrase_comparison()
        self.clear()
        self.object_comparison()

    def phrase_comparison(self):
        title = Text("PHRASE MORPHS", font_size=28).to_edge(UP)
        labels = headings().shift(DOWN * 0.25)
        self.add(title, labels)

        for before, after in [
            ("SMART MORPH", "SHAPE SHIFT"),
            ("HELLO WORLD", "MORPHING TEXT"),
        ]:
            sources = [Text(before, font_size=20).move_to([x, -0.4, 0]) for x in LANE_X]
            targets = [Text(after, font_size=20).move_to([x, -0.4, 0]) for x in LANE_X]
            self.add(*sources)

            smart_animation, smart_start, smart_end = smart_transform(sources[1], targets[1])
            if smart_start is not sources[1]:
                self.remove(sources[1])
                self.add(smart_start)

            self.play(
                Transform(sources[0], targets[0]),
                smart_animation,
                Polymorph(sources[2], targets[2], fill_mode="share"),
                FlubberTransform(sources[3], targets[3], match_center=True),
                run_time=2,
            )
            if smart_end is not targets[1]:
                self.remove(smart_end)
                self.add(targets[1])
            self.wait(0.35)
            self.remove(*sources, *targets, smart_start, smart_end)

    def object_comparison(self):
        title = Text("COMPLEX OBJECT SILHOUETTES", font_size=27).to_edge(UP)
        self.add(title, headings())

        # These closed paths include curves and uneven point counts to exercise
        # each library's shape alignment and split/merge handling.
        for before, after in [("leaf", "heart"), ("heart", "bolt"), ("bolt", "flower"), ("flower", "leaf")]:
            sources = [silhouette(before, [x, -0.3, 0]) for x in LANE_X]
            targets = [silhouette(after, [x, -0.3, 0]) for x in LANE_X]
            source_group = VGroup(*sources)
            self.add(source_group)

            smart_animation, smart_start, smart_end = smart_transform(sources[1], targets[1])
            if smart_start is not sources[1]:
                self.remove(sources[1])
                self.add(smart_start)

            self.play(
                Transform(sources[0], targets[0]),
                smart_animation,
                Polymorph(sources[2], targets[2], fill_mode="share"),
                FlubberTransform(sources[3], targets[3], match_center=True),
                run_time=2,
            )
            if smart_end is not targets[1]:
                self.remove(smart_end)
                self.add(targets[1])
            self.wait(0.35)
            self.remove(source_group, *sources, *targets, smart_start, smart_end)
