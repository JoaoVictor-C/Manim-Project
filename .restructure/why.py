import json, sys
sys.path.insert(0, sys.argv[2]); import layout
g = json.load(open(sys.argv[1]))
M = {"manim_studio." + k: "manim_studio." + v for k, v in layout.mapping().items()}
new = lambda m: M.get(m, m)
pk = lambda m: new(m).replace("manim_studio.","").rsplit(".",1)[0]
a, b = sys.argv[3], sys.argv[4]
for kind in ("edges", "lazy", "typing"):
    for x, ys in g.get(kind, {}).items():
        for y in ys:
            if pk(x) == a and pk(y) == b: print(kind, x.replace("manim_studio.",""), "->", y.replace("manim_studio.",""))
