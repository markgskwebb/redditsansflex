#!/usr/bin/env python3
"""For every glyph/weight: does a different start point (cyclic shift) or contour pairing fit Sans->Condensed much better?
A big improvement means the stored correspondence is a twist.   python 35_shift_check.py <merged .glyphs> [ratio]"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import glyphsLib
import flex_lib as fl

f = glyphsLib.GSFont(sys.argv[1]); ratio = float(sys.argv[2]) if len(sys.argv) > 2 else 3.0
mid = {m.name: m.id for m in f.masters}

def cost(a, b):  # a,b node lists; mean sq distance after removing nothing (same coordinate frame)
    return sum((p[0]-q[0])**2 + (p[1]-q[1])**2 for p, q in zip(a, b)) / max(1, len(a))

def types(n): return [p[2] for p in n]
out = []
for g in f.glyphs:
    for wn in ("ExtraLight", "Regular", "Black"):
        s, c = fl.snap(g.layers[mid[wn]]), fl.snap(g.layers[mid["Condensed " + wn]])
        sp = [sh["nodes"] for sh in s["shapes"] if sh["k"] == "p"]; cp = [sh["nodes"] for sh in c["shapes"] if sh["k"] == "p"]
        if len(sp) != len(cp): continue
        for i, (a, b) in enumerate(zip(sp, cp)):
            if len(a) != len(b): continue
            cur = cost(a, b); best = (cur, 0)
            for k in range(1, len(b)):
                bb = b[k:] + b[:k]
                if types(bb) != types(a): continue          # only shifts that keep node types aligned
                v = cost(a, bb)
                if v < best[0]: best = (v, k)
            if best[1] and cur > 400 and cur / max(best[0], 1) >= ratio:
                out.append((cur / max(best[0], 1), g.name, wn, i, best[1], len(a), cur, best[0]))
        # contour pairing swap check
        if len(sp) > 1 and all(len(a) == len(b) for a, b in zip(sp, cp)):
            cur = sum(cost(a, b) for a, b in zip(sp, cp))
            for i in range(len(sp)):
                for j in range(i+1, len(sp)):
                    if len(sp[i]) == len(sp[j]) and types(sp[i]) == types(sp[j]):
                        sw = sum(cost(a, b) for a, b in zip(sp, [cp[j] if k == i else cp[i] if k == j else x for k, x in enumerate(cp)]))
                        if cur > 400 and cur / max(sw, 1) >= ratio: out.append((cur/max(sw,1), g.name, wn, f"swap {i}<->{j}", 0, 0, cur, sw))
out.sort(key=lambda r: -r[0])
print(f"suspected twists (ratio>={ratio}): {len(out)} | glyphs: {sorted({r[1] for r in out})}")
for r in out[:40]: print(f"  {r[1]:16} {r[2]:10} contour {r[3]} shift={r[4]}/{r[5]}  cost {r[6]:.0f} -> {r[7]:.0f}  (x{r[0]:.1f})")
