#!/usr/bin/env python3
"""Point-correspondence check on the merged source: Normal vs Condensed master layers, per glyph/weight.
Y should barely change between widths; a large |dy| between corresponding points means start point / contour order
differ (bad interpolation, and wild Expanded extrapolation).   python 34_correspondence.py <merged .glyphs> [dy_threshold]"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import glyphsLib
import flex_lib as fl

f = glyphsLib.GSFont(sys.argv[1]); thr = float(sys.argv[2]) if len(sys.argv) > 2 else 60
mid = {m.name: m.id for m in f.masters}
rows = []
for g in f.glyphs:
    for wn in ("ExtraLight", "Regular", "Black"):
        s, c = fl.snap(g.layers[mid[wn]]), fl.snap(g.layers[mid["Condensed " + wn]])
        worst = (0, None)
        for si, (sh, ch) in enumerate(zip(s["shapes"], c["shapes"])):
            if sh["k"] != "p":
                continue
            for ni, (a, b) in enumerate(zip(sh["nodes"], ch["nodes"])):
                dy = abs(a[1] - b[1])
                if dy > worst[0]:
                    worst = (dy, (si, ni, (a[0], a[1]), (b[0], b[1])))
        if worst[0] > thr:
            rows.append((worst[0], g.name, wn, worst[1]))
rows.sort(reverse=True)
print(f"glyph/weight pairs with max |dy| > {thr}: {len(rows)} | glyphs: {len({r[1] for r in rows})}")
for dy, n, wn, info in rows[:40]:
    print(f"  {n:18} {wn:10} max|dy|={dy:6.0f}  at contour {info[0]} node {info[1]}: Sans{info[2]} vs Cond{info[3]}")
