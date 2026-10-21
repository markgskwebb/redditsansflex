#!/usr/bin/env python3
"""Reload the merged Glyphs source, write UFO masters + designspace (with named fvar instances) for fontmake.

    python 20_write_designspace.py <merged .glyphs> <output dir>
"""
import os
import shutil
import sys

import glyphsLib
import ufoLib2
from fontTools.designspaceLib import InstanceDescriptor

SRC, OUT = sys.argv[1], sys.argv[2]
FAMILY = "Reddit Sans Flex"

if os.path.isdir(OUT):
    shutil.rmtree(OUT)
os.makedirs(OUT)

font = glyphsLib.GSFont(SRC)  # reload from disk: proves the saved .glyphs is self-sufficient
ds = glyphsLib.to_designspace(
    font,
    ufo_module=ufoLib2,
    minimize_glyphs_diffs=False,
    generate_GDEF=True,
    store_editor_state=False,
    write_skipexportglyphs=True,  # non-exporting helper glyphs (e.g. .lf, strokelongcomb) must not be compiled
)

print("axes:")
for a in ds.axes:
    print(f"  {a.name} ({a.tag}) user min/default/max = {a.minimum}/{a.default}/{a.maximum} | map = {a.map}")

# --- named instances (fvar). Weight: user -> design values come from the axis map built by glyphsLib.
weights = [("ExtraLight", 200), ("Light", 300), ("Regular", 400), ("Medium", 500),
           ("SemiBold", 600), ("Bold", 700), ("ExtraBold", 800), ("Black", 900)]
widths = [("Condensed", 88), ("", 100), ("Expanded", 112)]
wght_axis = next(a for a in ds.axes if a.tag == "wght")
wdth_axis = next(a for a in ds.axes if a.tag == "wdth")
to_design = dict(wght_axis.map)  # user -> design

# STAT axis-value labels (so font menus can name the stops). userValue is in user space (200..900 / 88..112).
from fontTools.designspaceLib import AxisLabelDescriptor  # noqa: E402

wght_axis.axisLabels = [
    AxisLabelDescriptor(name=n, userValue=float(v), elidable=(n == "Regular"),
                        linkedUserValue=700.0 if n == "Regular" else None)
    for n, v in weights
]
wdth_axis.axisLabels = [
    AxisLabelDescriptor(name=n, userValue=float(v), elidable=(n == "Normal"))
    for n, v in (("Condensed", 88), ("Normal", 100), ("Expanded", 112))
]

ds.instances = []
for wname, wuser in weights:
    for dname, duser in widths:
        style = " ".join(x for x in (dname, wname) if x)
        if style == "Regular":
            style_name = "Regular"
        elif dname and wname == "Regular":
            style_name = dname
        else:
            style_name = style
        inst = InstanceDescriptor()
        inst.familyName = FAMILY
        inst.styleName = style_name
        inst.name = f"{FAMILY} {style_name}"
        inst.location = {wght_axis.name: to_design[float(wuser)], wdth_axis.name: duser}
        ds.instances.append(inst)

# Each UFO is written once. Sparse (brace/intermediate) sources live in a layer of their associated master's UFO,
# so every source sharing the same font object must point at the same file.
ufo_paths = {}
for source in ds.sources:
    if source.layerName:
        continue
    path = os.path.join(OUT, f"{source.familyName}-{source.styleName}.ufo".replace(" ", ""))
    assert id(source.font) not in ufo_paths
    source.font.save(path, overwrite=True)
    ufo_paths[id(source.font)] = path
for source in ds.sources:
    path = ufo_paths[id(source.font)]  # KeyError here would mean a sparse source with no full-master UFO
    source.path = path
    source.filename = os.path.basename(path)

ds_path = os.path.join(OUT, "RedditSansFlex.designspace")
ds.write(ds_path)

full = [s for s in ds.sources if not s.layerName]
sparse = [s for s in ds.sources if s.layerName]
print(f"\nwrote {len(full)} full masters + {len(sparse)} sparse-layer sources + {len(ds.instances)} instances -> {ds_path}")
for s in full:
    print(f"  master {s.styleName!r:28} location={dict(s.location)}  file={os.path.basename(s.path)}")
print("sparse sources (layer, location):", sorted({(s.layerName, tuple(sorted(s.location.items()))) for s in sparse}, key=str)[:12])
