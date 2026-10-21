#!/usr/bin/env python3
"""For composites with attached marks: residual = (mark's _anchor x) - (base's anchor x) in the composite frame.
Expanded residual should equal Normal residual (accent stays where the designer put it relative to the base anchor)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import glyphsLib, flex_lib as fl
f = glyphsLib.GSFont(sys.argv[1]); m = {x.name: x.id for x in f.masters}
def anch(name, mid, an):
    for a in fl.snap(f.glyphs[name].layers[mid])["anchors"]:
        if a[0] == an: return a[1]
    return None
bad, checked = [], 0
for wn in ("ExtraLight", "Regular", "Black"):
    for g in f.glyphs:
        N = fl.snap(g.layers[m[wn]]); E = fl.snap(g.layers[m["Expanded " + wn]])
        comps = [(i, s) for i, s in enumerate(N["shapes"]) if s["k"] == "c"]
        if len(comps) < 2: continue
        for (i, s) in comps[1:]:
            mnames = [a[0][1:] for a in fl.snap(f.glyphs[s["name"]].layers[m[wn]])["anchors"] if a[0].startswith("_")]
            bnames = {a[0] for a in fl.snap(f.glyphs[N["shapes"][comps[0][0]]["name"]].layers[m[wn]])["anchors"]}
            cands = [x for x in mnames if x in bnames]
            if not cands: continue
            an = cands[0]
            res = []
            for D, mid in ((N, m[wn]), (E, m["Expanded " + wn])):
                base, mark = D["shapes"][comps[0][0]], D["shapes"][i]
                bx, mx = anch(base["name"], mid, an), anch(mark["name"], mid, "_" + an)
                if bx is None or mx is None: res = None; break
                res.append((mark["t"][4] + mark["t"][0] * mx) - (base["t"][4] + base["t"][0] * bx))
            if res is None: continue
            checked += 1
            if abs(res[1] - res[0]) > 12: bad.append((abs(res[1]-res[0]), g.name, wn, round(res[0]), round(res[1])))
bad.sort(reverse=True)
print(f"attached-mark pairs checked: {checked} | residual changed by >12u between Normal and Expanded: {len(bad)}")
for b in bad[:15]: print("  %s %s: normal residual %s expanded residual %s (d=%.0f)" % (b[1], b[2], b[3], b[4], b[0]))
