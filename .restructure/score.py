import json, sys, collections
sys.path.insert(0, sys.argv[2])
import importlib, layout; importlib.reload(layout)
g = json.load(open(sys.argv[1]))
M = {"manim_studio." + k: "manim_studio." + v for k, v in layout.mapping().items()}
new = lambda m: M.get(m, m)
def node(m):
    m = new(m).replace("manim_studio.", "", 1) if new(m) != "manim_studio" else "(root)"
    parts = m.split(".")
    if len(parts) == 1: return parts[0]            # a root module or ui/main_window -> itself
    if parts[0] == "ui" and len(parts) == 2: return m   # ui root module
    return ".".join(parts[:-1]) if parts[0] in ("core","ui","render","processes") else parts[0]
def edges_of(kind):
    c = collections.Counter()
    for a, bs in g.get(kind, {}).items():
        for b in bs:
            na, nb = node(a), node(b)
            if na != nb: c[(na, nb)] += 1
    return c
S, L, T = edges_of("edges"), edges_of("lazy"), edges_of("typing")
def scc(adj, nodes):
    idx, low, st, on, out, c = {}, {}, [], set(), [], [0]
    sys.setrecursionlimit(10000)
    def go(v):
        idx[v]=low[v]=c[0]; c[0]+=1; st.append(v); on.add(v)
        for w in adj[v]:
            if w not in idx: go(w); low[v]=min(low[v],low[w])
            elif w in on: low[v]=min(low[v],idx[w])
        if low[v]==idx[v]:
            comp=[]
            while True:
                w=st.pop(); on.discard(w); comp.append(w)
                if w==v: break
            if len(comp)>1: out.append(sorted(comp))
    for v in nodes:
        if v not in idx: go(v)
    return out
def adj_of(*cs):
    a = collections.defaultdict(set)
    for c in cs:
        for (x, y) in c: a[x].add(y)
    return a
nodes = sorted({x for c in (S, L, T) for k in c for x in k})
print("static package cycles:", scc(adj_of(S), nodes))
print("static+lazy package cycles:", scc(adj_of(S, L), nodes))
print()
print("static edges between packages (n imports):")
by = collections.defaultdict(list)
for (a, b), n in sorted(S.items()): by[a].append(f"{b}({n})")
for a in sorted(by): print(f"  {a:<17}-> " + ", ".join(by[a]))
print("\nlazy-only edges (not already static):")
for (a, b), n in sorted(L.items()):
    if (a, b) not in S: print(f"  {a} -> {b} ({n})")
print("\ntyping-only edges (not already static/lazy):")
for (a, b), n in sorted(T.items()):
    if (a, b) not in S and (a, b) not in L: print(f"  {a} -> {b} ({n})")
