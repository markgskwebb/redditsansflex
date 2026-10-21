#!/usr/bin/env python3
"""Merge Reddit Sans + Reddit Sans Condensed into one wght x wdth Glyphs source, adding a computed Expanded width.

    python 11_merge.py <upstream sources dir> <output .glyphs>

Upstream files are only read, never modified.
"""
import collections
import copy
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import glyphsLib  # noqa: E402
from glyphsLib.classes import GSAxis, GSFontMaster, GSLayer, GSMetricValue  # noqa: E402

import flex_lib as fl  # noqa: E402

SRC, OUT = sys.argv[1], sys.argv[2]

K = 1.0  # extrapolation strength: Expanded = Sans + K * (Sans - Condensed), X only  (~112% of Normal width)
WDTH = {"Condensed": 88, "Normal": 100, "Expanded": 112}
WEIGHTS = {"ExtraLight": 32, "Regular": 88, "Black": 180}  # Glyphs design coordinates (mapped to 200/400/900)

# Glyphs that cannot interpolate between Sans and Condensed as shipped upstream (found by 01-08 analysis scripts).
FIX = (
    "M Q a.ss01 d d.ss01 eight.tosf five.tosf fl four four.tf four.tosf n ordfeminine "
    "seven.tosf six.tosf three.tosf two.tosf u.ss01 zero.tosf"
).split()
# Non-exporting, unused as components, not referenced by features -> dropped from the merged source.
DROP = ["a.ss08", "overline"]
# Condensed 'n' carries a legacy anchor name; Sans uses 'leghookretroflex' for the same hook position.
RENAME_COND_ANCHORS = {"n": {"leghookright": "leghookretroflex"}}


def new_id():
    return str(uuid.uuid4()).upper()


def num(v):
    return int(v) if float(v) == int(v) else v


S = glyphsLib.GSFont(os.path.join(SRC, "RedditSans.glyphs"))
C = glyphsLib.GSFont(os.path.join(SRC, "RedditSansCondensed.glyphs"))

report = collections.defaultdict(list)

# ----------------------------------------------------------------------------- masters / axes
s_by_name = {m.name: m for m in S.masters}
c_by_name = {m.name: m for m in C.masters}
assert list(s_by_name) == list(c_by_name) == list(WEIGHTS), (list(s_by_name), list(c_by_name))
s_id = {n: m.id for n, m in s_by_name.items()}
c_old_id = {n: m.id for n, m in c_by_name.items()}
c_name_of_old = {v: k for k, v in c_old_id.items()}
s_name_of_id = {v: k for k, v in s_id.items()}
c_id = {n: new_id() for n in WEIGHTS}
e_id = {n: new_id() for n in WEIGHTS}

S.axes.append(GSAxis(name="Width", tag="wdth"))
for m in S.masters:
    m.axes = [m.axes[0], WDTH["Normal"]]


def clone_master(src, master_id, name, wght, wdth):
    m = GSFontMaster()
    m.id = master_id
    m.axes = [wght, wdth]
    m.metrics = [GSMetricValue(position=v.position, overshoot=v.overshoot) for v in src.metrics]
    for cp in src.customParameters:
        if cp.name != "Master Name":
            m.customParameters[cp.name] = cp.value
    m.stems = list(src.stems)
    m.numbers = list(src.numbers)
    m.name = name
    return m


for wn, w in WEIGHTS.items():
    S.masters.append(clone_master(c_by_name[wn], c_id[wn], f"Condensed {wn}", w, WDTH["Condensed"]))
for wn, w in WEIGHTS.items():
    S.masters.append(clone_master(s_by_name[wn], e_id[wn], f"Expanded {wn}", w, WDTH["Expanded"]))

# ----------------------------------------------------------------------------- drop unused glyphs
for name in DROP:
    del S.glyphs[name]
    report["dropped glyphs"].append(name)

# ----------------------------------------------------------------------------- glyphs
sparse_cancel = 0
sparse_cond = 0
sparse_sans = 0
clamped = collections.Counter()
errors = []

for g in S.glyphs:
    name = g.name
    cg = C.glyphs[name]

    # remove backup/background layers (not masters, not intermediate layers)
    master_ids_now = {m.id for m in S.masters}
    for layer in list(g.layers):
        if layer.layerId not in master_ids_now and not layer._is_brace_layer():
            del g.layers[layer.layerId]

    sdata, cdata = {}, {}
    for wn in WEIGHTS:
        ls = g.layers[s_id[wn]]
        lc = cg.layers[c_old_id[wn]]
        if name in FIX:
            log = []
            # decompose components only when the shape kinds actually differ between the two fonts
            raw_s, raw_c = fl.snap(ls), fl.snap(lc)
            if [s["k"] for s in raw_s["shapes"]] == [s["k"] for s in raw_c["shapes"]]:
                sd, cd = raw_s, raw_c
            else:
                sd = fl.decomposed_layer_data(S, name, s_id[wn])
                cd = fl.decomposed_layer_data(C, name, c_old_id[wn])
                log.append("decomposed components")
            if fl.structure(sd)[0] != fl.structure(cd)[0]:
                sd = fl.align_shapes(sd, cd, log)
            sd, cd = fl.reconcile_anchors(sd, cd, RENAME_COND_ANCHORS.get(name), log)
            fl.fill(ls, sd)  # Sans master layer rewritten (geometry preserved; only structure changed)
            report["fixes"].append(f"{name} [{wn}]: " + ("; ".join(log) if log else "no change needed"))
        else:
            sd, cd = fl.snap(ls), fl.snap(lc)
        diff = fl.describe_diff(sd, cd)
        if diff:
            errors.append(f"{name} [{wn}] Sans vs Condensed still differ: {diff}")
        sdata[wn], cdata[wn] = sd, cd

    # contour pairing: reorder Condensed contours where they are stored in a different order than Sans (x, asterisk, ...)
    perms = {fl.contour_permutation(sdata[wn], cdata[wn]) is not None and tuple(fl.contour_permutation(sdata[wn], cdata[wn]))
             for wn in WEIGHTS}
    perms.discard(False)
    if perms:
        if len(perms) != 1:
            errors.append(f"{name}: inconsistent contour permutations across weights: {perms}")
        else:
            perm = list(next(iter(perms)))
            for wn in WEIGHTS:
                before = sum(fl._path_cost(a["nodes"], b["nodes"]) for a, b in zip(
                    [s for s in sdata[wn]["shapes"] if s["k"] == "p"], [s for s in cdata[wn]["shapes"] if s["k"] == "p"]))
                cdata[wn] = fl.apply_permutation(cdata[wn], perm)
                after = sum(fl._path_cost(a["nodes"], b["nodes"]) for a, b in zip(
                    [s for s in sdata[wn]["shapes"] if s["k"] == "p"], [s for s in cdata[wn]["shapes"] if s["k"] == "p"]))
                if after > before:
                    errors.append(f"{name} [{wn}] contour reorder made fit worse ({before:.0f} -> {after:.0f})")
            report["contour reorder"].append(f"{name}: Condensed contours re-paired with permutation {perm}")
            contour_perm = perm
    else:
        contour_perm = None

    for wn in WEIGHTS:
        # Condensed master layer
        lc_new = GSLayer()
        lc_new.layerId = c_id[wn]
        lc_new.associatedMasterId = c_id[wn]
        g.layers.append(lc_new)
        fl.fill(lc_new, cdata[wn])
        # Expanded master layer (computed)
        try:
            ed, was_clamped = fl.extrapolate_x(sdata[wn], cdata[wn], K)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name} [{wn}] extrapolation failed: {exc!r}")
            continue
        if was_clamped:
            clamped[name] += 1
        le_new = GSLayer()
        le_new.layerId = e_id[wn]
        le_new.associatedMasterId = e_id[wn]
        g.layers.append(le_new)
        fl.fill(le_new, ed)

    # ---- intermediate (brace) layers
    s_braces = [l for l in g.layers if l._is_brace_layer() and l.layerId not in master_ids_now]
    c_braces = [l for l in cg.layers if l._is_brace_layer()]
    for l in s_braces:
        wght = l._brace_coordinates()[0]
        l.attributes["coordinates"] = [num(wght), WDTH["Normal"]]
        sparse_sans += 1
    c_coords = set()
    if c_braces:
        c_layers_for_model = [(WEIGHTS[wn], cdata[wn]) for wn in WEIGHTS]
        for l in c_braces:
            wght = l._brace_coordinates()[0]
            c_coords.add(wght)
            data = fl.snap(l)
            if contour_perm:
                data = fl.apply_permutation(data, contour_perm)
            c_layers_for_model.append((wght, data))
            nl = GSLayer()
            nl.layerId = new_id()
            nl.associatedMasterId = c_id[c_name_of_old[l.associatedMasterId]]
            nl.attributes["coordinates"] = [num(wght), WDTH["Condensed"]]
            g.layers.append(nl)
            fl.fill(nl, data)
            sparse_cond += 1
    else:
        c_layers_for_model = [(WEIGHTS[wn], cdata[wn]) for wn in WEIGHTS]
    # cancellation layers: a Sans-only intermediate correction must not leak onto the Condensed side
    for l in s_braces:
        wght = l.attributes["coordinates"][0]
        if float(wght) in c_coords:
            continue
        data = fl.interpolate_weight(c_layers_for_model, float(wght))
        nl = GSLayer()
        nl.layerId = new_id()
        nl.associatedMasterId = c_id[s_name_of_id[l.associatedMasterId]]
        nl.attributes["coordinates"] = [num(wght), WDTH["Condensed"]]
        g.layers.append(nl)
        fl.fill(nl, data)
        sparse_cancel += 1

# ----------------------------------------------------------------------------- Expanded mark re-attachment
# Extrapolating a mark's offset independently of its base letter's anchor can misplace accents (e.g. caron on d, i-family).
# For composites of exactly [base, mark]: set the Expanded mark offset so (mark anchor - base anchor) equals Normal's.
attach_stats = {"fixed": 0, "max_move": 0, "skipped_multi": set()}


def anchor_x(name, mid, an):
    for a in fl.snap(S.glyphs[name].layers[mid])["anchors"]:
        if a[0] == an:
            return a[1]
    return None


for g in S.glyphs:
    for wn in WEIGHTS:
        N = fl.snap(g.layers[s_id[wn]])
        comps = [s for s in N["shapes"] if s["k"] == "c"]
        if len(comps) < 2:
            continue
        if len(comps) > 2:
            attach_stats["skipped_multi"].add(g.name)
            continue
        base_n, mark_n = comps
        mnames = [a[0][1:] for a in fl.snap(S.glyphs[mark_n["name"]].layers[s_id[wn]])["anchors"] if a[0].startswith("_")]
        bnames = {a[0] for a in fl.snap(S.glyphs[base_n["name"]].layers[s_id[wn]])["anchors"]}
        cands = [x for x in mnames if x in bnames]
        if not cands:
            continue
        an = cands[0]
        bx_n, mx_n = anchor_x(base_n["name"], s_id[wn], an), anchor_x(mark_n["name"], s_id[wn], "_" + an)
        resid = (mark_n["t"][4] + mark_n["t"][0] * mx_n) - (base_n["t"][4] + base_n["t"][0] * bx_n)
        layer = g.layers[e_id[wn]]
        E = fl.snap(layer)
        ecomps = [s for s in E["shapes"] if s["k"] == "c"]
        if len(ecomps) != 2:
            continue
        base_e, mark_e = ecomps
        bx_e, mx_e = anchor_x(base_e["name"], e_id[wn], an), anchor_x(mark_e["name"], e_id[wn], "_" + an)
        if bx_e is None or mx_e is None:
            continue
        want = resid + base_e["t"][4] + base_e["t"][0] * bx_e - mark_e["t"][0] * mx_e
        move = want - mark_e["t"][4]
        if abs(move) > 1:
            mark_e["t"][4] = want
            fl.fill(layer, E)
            attach_stats["fixed"] += 1
            attach_stats["max_move"] = max(attach_stats["max_move"], abs(move))

# ----------------------------------------------------------------------------- Expanded spacing floor
# Extrapolation can leave Expanded sidebearings slightly tighter than Normal's. Enforce: Expanded LSB/RSB >= Normal LSB/RSB.
# Works on absolute outlines (resolving components) so paths, composites and mixed glyphs are all handled the same way.
spacing_stats = {"adjusted": 0, "max_shift": 0, "skipped_skew": []}


def abs_x_extent(name, which, wn, memo):
    """(min_x, max_x) of the glyph's real outline in its own coordinate frame, or None if it has no outline."""
    key = (name, which, wn)
    if key in memo:
        return memo[key]
    layer = S.glyphs[name].layers[(s_id if which == "N" else e_id)[wn]]
    d = fl.snap(layer)
    lo, hi = None, None

    def add(a, b):
        nonlocal lo, hi
        lo = a if lo is None else min(lo, a)
        hi = b if hi is None else max(hi, b)

    for s in d["shapes"]:
        if s["k"] == "p":
            xs = [n[0] for n in s["nodes"] if n[2] != "offcurve"]
            if xs:
                add(min(xs), max(xs))
        else:
            sub = abs_x_extent(s["name"], which, wn, memo)
            if sub is None:
                continue
            a_, b_, c_, d_, tx, ty = s["t"]
            if abs(c_) > 1e-9:  # skew would need y; not present in this font, but never guess
                spacing_stats["skipped_skew"].append(name)
                memo[key] = None
                return None
            e = sorted((a_ * sub[0] + tx, a_ * sub[1] + tx))
            add(e[0], e[1])
    memo[key] = (lo, hi) if lo is not None else None
    return memo[key]


def is_mark(g, master_id):
    """Combining mark: Unicode category M*, or carries a mark-attachment anchor (_top, _bottom, ...). Category is not
    stored in these sources, so it is derived here."""
    import unicodedata
    if g.unicode:
        try:
            if unicodedata.category(chr(int(g.unicode.split(",")[0], 16))).startswith("M"):
                return True
        except ValueError:
            pass
    return any(a[0].startswith("_") for a in fl.snap(g.layers[master_id])["anchors"])


spacing_delta = {}  # (glyph, wn) -> (dl, dr)
for wn in WEIGHTS:
    memo = {}
    for g in S.glyphs:
        n_w = fl.snap(g.layers[s_id[wn]])["width"]
        e_w = fl.snap(g.layers[e_id[wn]])["width"]
        ne, ee = abs_x_extent(g.name, "N", wn, memo), abs_x_extent(g.name, "E", wn, memo)
        if n_w <= 0 or ne is None or ee is None or is_mark(g, s_id[wn]):  # marks (incl. spanning ones) overhang by design
            spacing_delta[(g.name, wn)] = (0, 0)
            continue
        dl = max(0, round(ne[0] - ee[0]))
        dr = max(0, round((n_w - ne[1]) - (e_w - ee[1])))
        spacing_delta[(g.name, wn)] = (dl, dr)

if os.environ.get("FLEX_NO_SPACING"):  # diagnostic switch: build without the spacing floor
    spacing_delta = {k: (0, 0) for k in spacing_delta}

for g in S.glyphs:
    for wn in WEIGHTS:
        dl, dr = spacing_delta[(g.name, wn)]
        if not (dl or dr):
            continue
        layer = g.layers[e_id[wn]]
        d = fl.snap(layer)
        d["width"] = d["width"] + dl + dr
        for s in d["shapes"]:
            if s["k"] == "p":
                for n in s["nodes"]:
                    n[0] += dl
            else:
                dlc, _ = spacing_delta.get((s["name"], wn), (0, 0))
                s["t"][4] += dl - s["t"][0] * dlc  # a*dlc: the component moved itself by dlc along its own (possibly mirrored) x
        for a in d["anchors"]:
            a[1] += dl
        fl.fill(layer, d)
        spacing_stats["adjusted"] += 1
        spacing_stats["max_shift"] = max(spacing_stats["max_shift"], dl, dr)
        spacing_stats.setdefault("all", []).append((max(dl, dr), g.name, wn, dl, dr))

# ----------------------------------------------------------------------------- kerning
def pairs(font, mid):
    return {(a, b): v for a, d in font.kerning[mid].items() for b, v in d.items()}


def to_nested(flat):
    out = collections.OrderedDict()
    for (a, b), v in sorted(flat.items()):
        out.setdefault(a, collections.OrderedDict())[b] = v
    return out


kern_stats = {}
for wn in WEIGHTS:
    ks, kc = pairs(S, s_id[wn]), pairs(C, c_old_id[wn])
    union = set(ks) | set(kc)
    ks_full = {p: ks.get(p, 0) for p in union}
    kc_full = {p: kc.get(p, 0) for p in union}
    ke_full = {}
    flipped = 0
    for p in union:
        a, b = ks_full[p], kc_full[p]
        if a and b and (a > 0) == (b > 0):
            ke_full[p] = round(a + K * (a - b))
        else:
            ke_full[p] = a
            flipped += 1 if (a and b) else 0
    S.kerning[s_id[wn]] = to_nested(ks_full)
    S.kerning[c_id[wn]] = to_nested(kc_full)
    S.kerning[e_id[wn]] = to_nested(ke_full)
    kern_stats[wn] = (len(ks), len(kc), len(union), flipped)

# ----------------------------------------------------------------------------- font-level bits
S.instances = []  # named instances are generated by the build script
# glyphsLib skips any axis that is missing from an existing "Axis Mappings" parameter -> add wdth (identity map).
mappings = dict(S.customParameters["Axis Mappings"])
mappings["wdth"] = {str(v): v for v in WDTH.values()}
S.customParameters["Axis Mappings"] = mappings
S.familyName = "Reddit Sans Flex"
S.versionMajor, S.versionMinor = 1, 100  # Reddit Sans Flex 1.100

# ----------------------------------------------------------------------------- global structural verification
bad = []
ref_layer = lambda g: fl.snap(g.layers[s_id["Regular"]])  # noqa: E731
for g in S.glyphs:
    ref = ref_layer(g)
    for layer in g.layers:
        if layer.layerId in {m.id for m in S.masters} or layer._is_brace_layer():
            d = fl.snap(layer)
            diff = fl.describe_diff(ref, d)
            # anchors on intermediate layers are not used for interpolation; only flag shape differences there
            if layer._is_brace_layer() and layer.layerId not in {m.id for m in S.masters}:
                diff = [x for x in diff if not x.startswith("anchors")]
            if diff:
                bad.append(f"{g.name} layer {layer.layerId[:8]} {layer.attributes.get('coordinates','master')}: {diff}")

S.save(OUT)

print("=" * 70)
print("MERGE REPORT")
print("=" * 70)
print("masters:", [(m.name, list(m.axes)) for m in S.masters])
print("glyphs:", len(S.glyphs), "| dropped:", report["dropped glyphs"])
print(f"sparse layers: Sans={sparse_sans}  Condensed(explicit)={sparse_cond}  Condensed(cancellation)={sparse_cancel}")
print("kerning (Sans pairs, Cond pairs, union, sign-conflicts) per weight:", kern_stats)
print(f"Expanded glyph layers clamped to Sans (Condensed not narrower): {sum(clamped.values())} layers over {len(clamped)} glyphs")
print("   e.g.", sorted(clamped)[:25])
print("mark re-attachment: layers fixed =", attach_stats["fixed"], "| max move =", round(attach_stats["max_move"]), "| multi-mark composites left alone =", len(attach_stats["skipped_multi"]))
print("spacing floor: glyph-layers adjusted =", spacing_stats["adjusted"], "| max shift =", spacing_stats["max_shift"], "| skipped(skew) =", sorted(set(spacing_stats["skipped_skew"])))
print("largest spacing shifts (max, glyph, weight, dl, dr):", sorted(spacing_stats.get("all", []), reverse=True)[:6])
print("\nCONTOUR RE-PAIRING:", report["contour reorder"])
print("\nFIXES APPLIED:")
for line in report["fixes"]:
    print("  ", line)
print(f"\nERRORS during merge: {len(errors)}")
for e in errors[:40]:
    print("  ", e)
print(f"\nSTRUCTURAL MISMATCHES after merge (all layers vs Sans Regular): {len(bad)}")
for b in bad[:40]:
    print("  ", b)
print("\nsaved:", OUT)
