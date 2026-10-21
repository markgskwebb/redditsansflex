#!/usr/bin/env python3
"""Verify the Flex variable font against the upstream fonts it was derived from.

    python 30_verify.py <flex VF> <upstream Sans VF> <upstream Condensed VF>

Checks
  A. wdth=100 must reproduce upstream Reddit Sans at every tested weight (incl. the intermediate-layer weights).
  B. wdth=88  must reproduce upstream Reddit Sans Condensed at every tested weight.
  C. Expanded (wdth=112) sanity: advance ratios, vertical metrics unchanged, sidebearing problems.
"""
import statistics
import sys
from collections import Counter

from fontTools.pens.areaPen import AreaPen
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.ttLib import TTFont

flex_path, sans_path, cond_path = sys.argv[1:4]
flex, sans, cond = TTFont(flex_path), TTFont(sans_path), TTFont(cond_path)


def split_contours(ops):
    contours, cur = [], []
    for op, args in ops:
        if op == "moveTo" and cur:
            contours.append(cur)
            cur = []
        cur.append((op, args))
    if cur:
        contours.append(cur)
    return contours


def contour_sig(c):
    return [(op, len(args)) for op, args in c]


def contour_dev(c1, c2):
    return max([abs(x - y) for (_, a1), (_, a2) in zip(c1, c2) for p, q in zip(a1, a2) for x, y in zip(p, q)] or [0])


def match_dev(ops_a, ops_b):
    """Order-independent deviation: pair each contour of A with the closest same-shaped unused contour of B.
    Returns None if the contour multisets cannot be paired (structure really differs)."""
    ca, cb = split_contours(ops_a), split_contours(ops_b)
    if len(ca) != len(cb):
        return None
    unused, worst = list(range(len(cb))), 0
    for c in ca:
        cands = [(contour_dev(c, cb[j]), j) for j in unused if contour_sig(cb[j]) == contour_sig(c)]
        if not cands:
            return None
        d, j = min(cands)
        unused.remove(j)
        worst = max(worst, d)
    return worst


def glyph_info(font, loc, name, gs):
    g = gs[name]
    rec = DecomposingRecordingPen(gs)
    g.draw(rec)
    bp = BoundsPen(gs)
    g.draw(bp)
    ap = AreaPen(gs)
    g.draw(ap)
    return {"width": g.width, "ops": rec.value, "bounds": bp.bounds, "area": ap.value}


def flat(ops):
    out = []
    for op, args in ops:
        out.append(op)
        for a in args:
            out.extend(a if isinstance(a, tuple) else [a])
    return out


def compare(flex_font, ref_font, flex_loc, ref_loc, label, names):
    fgs = flex_font.getGlyphSet(location=flex_loc)
    rgs = ref_font.getGlyphSet(location=ref_loc)
    pt_dev, struct_diff, width_dev = {}, {}, {}
    for n in names:
        a, b = glyph_info(flex_font, flex_loc, n, fgs), glyph_info(ref_font, ref_loc, n, rgs)
        width_dev[n] = abs(a["width"] - b["width"])
        md = match_dev(a["ops"], b["ops"])
        if md is not None:
            pt_dev[n] = md
        else:
            bd = 0
            if a["bounds"] and b["bounds"]:
                bd = max(abs(x - y) for x, y in zip(a["bounds"], b["bounds"]))
            ar = abs(a["area"] - b["area"]) / max(1.0, abs(b["area"]))
            struct_diff[n] = (bd, ar)
    return pt_dev, struct_diff, width_dev


def summarize(label, pt_dev, struct_diff, width_dev):
    vals = list(pt_dev.values())
    hist = Counter()
    for v in vals:
        hist["<=1" if v <= 1 else "<=2" if v <= 2 else "<=3" if v <= 3 else "<=6" if v <= 6 else ">6"] += 1
    worst = sorted(pt_dev.items(), key=lambda kv: -kv[1])[:6]
    wbad = [(k, v) for k, v in width_dev.items() if v > 1]
    sbad = sorted([(k, v) for k, v in struct_diff.items() if v[0] > 3 or v[1] > 0.01], key=lambda kv: -kv[1][0])
    print(f"  {label:34s} point-compared={len(vals):4d} dev hist={dict(hist)} worst={[(k, round(v,1)) for k, v in worst]}")
    print(f"  {'':34s} structure-differs={len(struct_diff):3d} (of which geometry off: {len(sbad)} {[(k, round(v[0]), round(v[1],4)) for k, v in sbad[:6]]}) | width mismatches>1: {len(wbad)} {wbad[:6]}")
    return len(sbad) + len(wbad) + hist[">6"]


names_common = [n for n in flex.getGlyphOrder() if n in sans.getGlyphOrder() and n in cond.getGlyphOrder()]
print("fvar axes:", [(a.axisTag, a.minValue, a.defaultValue, a.maxValue) for a in flex["fvar"].axes])
print("named instances:", len(flex["fvar"].instances), "| glyphs flex/sans/cond:", len(flex.getGlyphOrder()), len(sans.getGlyphOrder()), len(cond.getGlyphOrder()), "| in common:", len(names_common))
missing = [n for n in sans.getGlyphOrder() if n not in flex.getGlyphOrder()]
extra = [n for n in flex.getGlyphOrder() if n not in sans.getGlyphOrder()]
print("glyphs in upstream Sans but missing in Flex:", missing, "| extra in Flex:", extra)
print("tables:", sorted(t for t in flex.keys() if t in ("GSUB", "GPOS", "GDEF", "gvar", "avar", "HVAR", "MVAR", "STAT", "fvar", "cmap")))
print("cmap identical to upstream Sans:", flex.getBestCmap() == sans.getBestCmap())

problems = 0
weights = [200, 300, 315, 400, 500, 600, 700, 800, 900]
print("\n=== A. wdth=100 vs upstream Reddit Sans")
for w in weights:
    pd, sd, wd = compare(flex, sans, {"wght": w, "wdth": 100}, {"wght": w}, f"A w={w}", names_common)
    problems += summarize(f"wght={w}", pd, sd, wd)
print("\n=== B. wdth=88 vs upstream Reddit Sans Condensed")
for w in weights:
    pd, sd, wd = compare(flex, cond, {"wght": w, "wdth": 88}, {"wght": w}, f"B w={w}", names_common)
    problems += summarize(f"wght={w}", pd, sd, wd)

print("\n=== C. Expanded sanity (wdth=112)")
for w in (200, 400, 700, 900):
    fn = flex.getGlyphSet(location={"wght": w, "wdth": 100})
    fe = flex.getGlyphSet(location={"wght": w, "wdth": 112})
    ratios, ymax_changes, neg_sb = [], [], []
    for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789":
        n = flex.getBestCmap()[ord(ch)]
        ratios.append(fe[n].width / fn[n].width)
        bn, be = BoundsPen(fn), BoundsPen(fe)
        fn[n].draw(bn)
        fe[n].draw(be)
        ymax_changes.append(abs(bn.bounds[3] - be.bounds[3]) + abs(bn.bounds[1] - be.bounds[1]))
        lsb, rsb = be.bounds[0], fe[n].width - be.bounds[2]
        if lsb < 0 or rsb < 0:
            neg_sb.append((ch, round(lsb), round(rsb)))
    print(f"  wght={w}: width ratio exp/normal mean={statistics.mean(ratios):.3f} min={min(ratios):.3f} max={max(ratios):.3f} | max vertical-extent change={max(ymax_changes):.0f} | negative sidebearings: {neg_sb}")
    # stem thickness
    bi_n, bi_e = BoundsPen(fn), BoundsPen(fe)
    fn["I"].draw(bi_n)
    fe["I"].draw(bi_e)
    print(f"           'I' stem width normal={bi_n.bounds[2]-bi_n.bounds[0]:.0f} expanded={bi_e.bounds[2]-bi_e.bounds[0]:.0f}")

print("\nTOTAL PROBLEM COUNT (A+B):", problems)
