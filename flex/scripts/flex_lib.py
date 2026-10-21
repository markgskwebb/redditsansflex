"""Helpers for merging Reddit Sans + Reddit Sans Condensed (+ computed Expanded) into one wght x wdth source.

Layer geometry is handled as plain dicts ("layer data") so it can be fixed/extrapolated freely and then written
back into glyphsLib objects:

    {"width": float,
     "shapes": [ {"k": "p", "closed": bool, "nodes": [[x, y, type, smooth, name], ...]}
               | {"k": "c", "name": str, "t": [a, b, c, d, tx, ty], "alignment": int, "anchor": str} ],
     "anchors": [[name, x, y], ...]}
"""
import copy
import itertools

from fontTools.misc.vector import Vector
from fontTools.varLib.models import VariationModel
from glyphsLib.classes import GSAnchor, GSComponent, GSNode, GSPath

# --------------------------------------------------------------------------- snapshot / write-back


def _xy(pos):
    """glyphsLib positions are Point objects when parsed from a file but may be plain tuples when created in code."""
    return (pos.x, pos.y) if hasattr(pos, "x") else (pos[0], pos[1])


def snap(layer):
    shapes = []
    for s in layer.shapes:
        if isinstance(s, GSPath):
            shapes.append({
                "k": "p",
                "closed": bool(s.closed),
                "nodes": [[*_xy(n.position), n.type, bool(n.smooth), n.name] for n in s.nodes],
            })
        else:
            shapes.append({
                "k": "c",
                "name": s.componentName,
                "t": [float(v) for v in s.transform],
                "alignment": s.alignment,
                "anchor": s.anchor,
            })
    anchors = [[a.name, *_xy(a.position)] for a in layer.anchors]
    return {"width": layer.width, "shapes": shapes, "anchors": anchors}


def fill(layer, d):
    """Write layer data `d` into a glyphsLib layer (replacing its geometry/anchors/width)."""
    layer.width = d["width"]
    shapes = []
    for s in d["shapes"]:
        if s["k"] == "p":
            p = GSPath()
            p.closed = s["closed"]
            p.nodes = [
                GSNode(position=(x, y), type=t, smooth=sm, name=nm) for x, y, t, sm, nm in s["nodes"]
            ]
            shapes.append(p)
        else:
            c = GSComponent(s["name"])
            c.transform = tuple(s["t"])
            c.alignment = s["alignment"]
            c.anchor = s["anchor"]
            shapes.append(c)
    layer.shapes = shapes
    layer.anchors = [GSAnchor(n, (x, y)) for n, x, y in d["anchors"]]


def structure(d):
    """Hashable description of everything that must match between interpolation masters."""
    shp = []
    for s in d["shapes"]:
        if s["k"] == "p":
            shp.append(("p", s["closed"], tuple(n[2] for n in s["nodes"])))
        else:
            shp.append(("c", s["name"]))
    return tuple(shp), tuple(sorted(a[0] for a in d["anchors"]))


def describe_diff(a, b):
    sa, aa = structure(a)
    sb, ab = structure(b)
    out = []
    if sa != sb:
        out.append("shapes")
    if aa != ab:
        out.append(f"anchors(only-first={sorted(set(aa) - set(ab))}, only-second={sorted(set(ab) - set(aa))})")
    return out


# --------------------------------------------------------------------------- affine helpers


def apply_t(t, x, y):
    return t[0] * x + t[2] * y + t[4], t[1] * x + t[3] * y + t[5]


def compose(parent, child):
    """result(p) = parent(child(p)); tuples are (a, b, c, d, tx, ty) with x' = a x + c y + tx."""
    pa, pb, pc, pd, ptx, pty = parent
    ca, cb, cc, cd, ctx, cty = child
    return (
        pa * ca + pc * cb,
        pb * ca + pd * cb,
        pa * cc + pc * cd,
        pb * cc + pd * cd,
        pa * ctx + pc * cty + ptx,
        pb * ctx + pd * cty + pty,
    )


IDENT = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

# --------------------------------------------------------------------------- decompose


def decompose(font, glyph_name, master_id, xform=IDENT, anchors_out=None, top=True):
    """Return path-shape dicts of a glyph layer with components resolved (recursive). If `anchors_out` is a
    dict, non-mark anchors of the referenced base glyphs are collected into it (what ufo2ft would propagate)."""
    layer = font.glyphs[glyph_name].layers[master_id]
    out = []
    for s in layer.shapes:
        if isinstance(s, GSPath):
            out.append({
                "k": "p",
                "closed": bool(s.closed),
                "nodes": [[*apply_t(xform, *_xy(n.position)), n.type, bool(n.smooth), n.name] for n in s.nodes],
            })
        else:
            t = compose(xform, tuple(float(v) for v in s.transform))
            out += decompose(font, s.componentName, master_id, t, anchors_out, top=False)
    if anchors_out is not None and not top:
        for a in layer.anchors:
            if not a.name.startswith("_") and a.name not in anchors_out:
                anchors_out[a.name] = list(apply_t(xform, *_xy(a.position)))
    return out


def decomposed_layer_data(font, glyph_name, master_id):
    layer = font.glyphs[glyph_name].layers[master_id]
    d = snap(layer)
    if all(s["k"] == "p" for s in d["shapes"]):
        return d
    prop = {}
    shapes = decompose(font, glyph_name, master_id, IDENT, prop)
    have = {a[0] for a in d["anchors"]}
    anchors = d["anchors"] + [[n, x, y] for n, (x, y) in prop.items() if n not in have]
    return {"width": d["width"], "shapes": shapes, "anchors": anchors}


# --------------------------------------------------------------------------- contour alignment


def _bbox(nodes):
    xs = [n[0] for n in nodes]
    ys = [n[1] for n in nodes]
    return min(xs), min(ys), max(xs), max(ys)


def _norm_bbox_dist(sn, cn, ratio):
    sx0, sy0, sx1, sy1 = _bbox(sn)
    cx0, cy0, cx1, cy1 = _bbox(cn)
    return (
        ((sx0 + sx1) / 2 * ratio - (cx0 + cx1) / 2) ** 2
        + ((sy0 + sy1) / 2 - (cy0 + cy1) / 2) ** 2
        + ((sx1 - sx0) * ratio - (cx1 - cx0)) ** 2
        + ((sy1 - sy0) - (cy1 - cy0)) ** 2
    )


def _cost(sn_aligned, cn_rest, ratio):
    return sum((a[0] * ratio - b[0]) ** 2 + (a[1] - b[1]) ** 2 for a, b in zip(sn_aligned, cn_rest))


def align_contour(sn, cn, ratio, log=None):
    """Return a version of Sans contour nodes `sn` (rotated and, where needed, with extra on-line nodes inserted)
    whose node-type sequence equals that of Condensed contour `cn`. Geometry of `sn` is preserved exactly."""
    ns, nc = len(sn), len(cn)
    if ns > nc:
        raise ValueError(f"Sans contour has more nodes ({ns}) than Condensed ({nc}); not handled")
    types_s = [n[2] for n in sn]
    best = None
    line_idx = [i for i, n in enumerate(cn) if n[2] == "line"]
    for rem in itertools.combinations(line_idx, nc - ns):
        rest_idx = [i for i in range(nc) if i not in rem]
        rest = [cn[i] for i in rest_idx]
        for shift in range(ns):
            if all(types_s[(i + shift) % ns] == rest[i][2] for i in range(ns)):
                aligned = [sn[(i + shift) % ns] for i in range(ns)]
                # every removed node must sit on a straight run: the following kept node has to be a 'line'
                ok = True
                for r in rem:
                    j = (r + 1) % nc
                    while j in rem:
                        j = (j + 1) % nc
                    if cn[j][2] != "line":
                        ok = False
                        break
                if not ok:
                    continue
                c = _cost(aligned, rest, ratio)
                if best is None or c < best[0]:
                    best = (c, rem, rest_idx, aligned)
    if best is None:
        raise ValueError("no node-type-compatible alignment found")
    _, rem, rest_idx, aligned = best
    out = []
    pos_in_rest = {ci: k for k, ci in enumerate(rest_idx)}
    for i in range(nc):
        if i in rem:
            # previous / next kept nodes (cyclic) in Condensed and their Sans counterparts
            a = i - 1
            while a % nc in rem:
                a -= 1
            b = i + 1
            while b % nc in rem:
                b += 1
            ca, cb, cp = cn[a % nc], cn[b % nc], cn[i]
            ax, ay, bx, by = ca[0], ca[1], cb[0], cb[1]
            den = (bx - ax) ** 2 + (by - ay) ** 2
            t = 0.5 if den == 0 else max(0.0, min(1.0, ((cp[0] - ax) * (bx - ax) + (cp[1] - ay) * (by - ay)) / den))
            sa, sb = aligned[pos_in_rest[a % nc]], aligned[pos_in_rest[b % nc]]
            out.append([sa[0] + t * (sb[0] - sa[0]), sa[1] + t * (sb[1] - sa[1]), "line", False, None])
            if log is not None:
                log.append(f"inserted node at t={t:.3f} between Sans nodes ({sa[0]:.0f},{sa[1]:.0f})->({sb[0]:.0f},{sb[1]:.0f})")
        else:
            out.append(list(aligned[pos_in_rest[i]]))
    return out


def align_shapes(sd, cd, log=None):
    """Make Sans layer data `sd` structurally match Condensed layer data `cd` (paths only). Returns new Sans data."""
    sp = [s for s in sd["shapes"] if s["k"] == "p"]
    cp = [s for s in cd["shapes"] if s["k"] == "p"]
    if len(sp) != len(cp):
        raise ValueError(f"path count differs {len(sp)} vs {len(cp)}")
    ratio = (cd["width"] / sd["width"]) if sd["width"] else 1.0
    best = None
    for perm in itertools.permutations(range(len(sp))):
        if any(len(sp[perm[i]]["nodes"]) > len(cp[i]["nodes"]) for i in range(len(cp))):
            continue
        c = sum(_norm_bbox_dist(sp[perm[i]]["nodes"], cp[i]["nodes"], ratio) for i in range(len(cp)))
        if best is None or c < best[0]:
            best = (c, perm)
    if best is None:
        raise ValueError("no contour assignment possible")
    perm = best[1]
    new_shapes = []
    for i, cpath in enumerate(cp):
        spath = sp[perm[i]]
        nodes = align_contour(spath["nodes"], cpath["nodes"], ratio, log)
        new_shapes.append({"k": "p", "closed": spath["closed"], "nodes": nodes})
    if log is not None and perm != tuple(range(len(sp))):
        log.append(f"reordered Sans contours {perm}")
    return {"width": sd["width"], "shapes": new_shapes, "anchors": sd["anchors"]}


def reconcile_anchors(sd, cd, rename_cond=None, log=None):
    """Give Sans and Condensed data identical anchor name sets; anchors missing on one side are synthesised from the
    other (x scaled by the advance-width ratio, y unchanged)."""
    rename_cond = rename_cond or {}
    cd["anchors"] = [[rename_cond.get(n, n), x, y] for n, x, y in cd["anchors"]]
    ratio = (cd["width"] / sd["width"]) if sd["width"] else 1.0
    sa = {n: (x, y) for n, x, y in sd["anchors"]}
    ca = {n: (x, y) for n, x, y in cd["anchors"]}
    for n in sorted(set(sa) - set(ca)):
        cd["anchors"].append([n, sa[n][0] * ratio, sa[n][1]])
        if log is not None:
            log.append(f"synthesised Condensed anchor '{n}'")
    for n in sorted(set(ca) - set(sa)):
        sd["anchors"].append([n, ca[n][0] / ratio, ca[n][1]])
        if log is not None:
            log.append(f"synthesised Sans anchor '{n}'")
    order = [n for n, _, _ in sd["anchors"]]
    cd["anchors"].sort(key=lambda a: order.index(a[0]))
    return sd, cd


# --------------------------------------------------------------------------- extrapolation (Expanded)


def extrapolate_x(sd, cd, k=1.0):
    """Expanded = Sans + k * (Sans - Condensed) applied to X only; Y values stay exactly Sans'. If Condensed is not
    narrower than Sans for this layer, Expanded is simply Sans (never narrower than Normal)."""
    ed = copy.deepcopy(sd)
    if cd["width"] >= sd["width"]:
        return ed, True
    ed["width"] = round(sd["width"] + k * (sd["width"] - cd["width"]))
    for es, ss, cs in zip(ed["shapes"], sd["shapes"], cd["shapes"]):
        if ss["k"] == "p":
            for en, sn_, cn_ in zip(es["nodes"], ss["nodes"], cs["nodes"]):
                en[0] = sn_[0] + k * (sn_[0] - cn_[0])
        else:
            es["t"][4] = ss["t"][4] + k * (ss["t"][4] - cs["t"][4])
    cmap = {n: (x, y) for n, x, y in cd["anchors"]}
    for ea, sa in zip(ed["anchors"], sd["anchors"]):
        cx = cmap[sa[0]][0]
        ea[1] = sa[1] + k * (sa[1] - cx)
    return ed, False


# --------------------------------------------------------------------------- 1-D interpolation (cancellation layers)


def flatten(d):
    v = [d["width"]]
    for s in d["shapes"]:
        if s["k"] == "p":
            for n in s["nodes"]:
                v += [n[0], n[1]]
        else:
            v += list(s["t"])
    for _, x, y in d["anchors"]:
        v += [x, y]
    return v


def unflatten(template, v):
    d = copy.deepcopy(template)
    i = 0
    d["width"] = v[i]
    i += 1
    for s in d["shapes"]:
        if s["k"] == "p":
            for n in s["nodes"]:
                n[0], n[1] = v[i], v[i + 1]
                i += 2
        else:
            s["t"] = list(v[i:i + 6])
            i += 6
    for a in d["anchors"]:
        a[1], a[2] = v[i], v[i + 1]
        i += 2
    assert i == len(v)
    return d


def interpolate_weight(layers, at, axis=(32.0, 88.0, 180.0)):
    """`layers`: list of (design_weight, layer_data) all structurally identical (default = axis[1]).
    Returns layer data interpolated at design weight `at` exactly as varLib would."""
    mn, df, mx = axis

    def norm(w):
        if w < df:
            return (w - df) / (df - mn)
        if w > df:
            return (w - df) / (mx - df)
        return 0.0

    locs = [{"wght": norm(w)} for w, _ in layers]
    model = VariationModel(locs)
    vecs = [Vector(flatten(d)) for _, d in layers]
    out = model.interpolateFromMasters({"wght": norm(at)}, vecs)
    template = next(d for w, d in layers if w == df)
    return unflatten(template, list(out))


# ----------------------------------------------------------------------------- contour pairing (Sans <-> Condensed)
def _path_cost(a, b):
    return sum((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 for p, q in zip(a, b)) / max(1, len(a))


def contour_permutation(sd, cd, ratio=3.0, min_cost=400.0):
    """If re-pairing Condensed's contours with Sans's fits >= `ratio` times better, return perm (perm[i] = index into
    cd's path list to place in Sans path i's slot); else None. Only pairs with equal node counts and node types qualify."""
    import itertools
    sp = [s["nodes"] for s in sd["shapes"] if s["k"] == "p"]
    cp = [s["nodes"] for s in cd["shapes"] if s["k"] == "p"]
    if len(sp) != len(cp) or len(sp) < 2 or len(sp) > 7:
        return None
    inf = float("inf")
    cost = [[(_path_cost(a, b) if [n[2] for n in a] == [n[2] for n in b] else inf) for b in cp] for a in sp]
    ident = sum(cost[i][i] for i in range(len(sp)))
    best, best_perm = ident, tuple(range(len(sp)))
    for perm in itertools.permutations(range(len(sp))):
        c = sum(cost[i][perm[i]] for i in range(len(sp)))
        if c < best:
            best, best_perm = c, perm
    if best_perm != tuple(range(len(sp))) and ident > min_cost and ident / max(best, 1.0) >= ratio:
        return list(best_perm)
    return None


def apply_permutation(data, perm):
    """Return layer data with its path shapes re-ordered by perm (components keep their slots)."""
    paths = [s for s in data["shapes"] if s["k"] == "p"]
    it = iter(perm)
    shapes = [paths[next(it)] if s["k"] == "p" else s for s in data["shapes"]]
    return {**data, "shapes": shapes}
