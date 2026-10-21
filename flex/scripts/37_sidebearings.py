import sys
from fontTools.ttLib import TTFont
from fontTools.pens.boundsPen import BoundsPen
f=TTFont(sys.argv[1]); cm=f.getBestCmap()
def sb(loc,n):
    gs=f.getGlyphSet(location=loc); bp=BoundsPen(gs); gs[n].draw(bp); b=bp.bounds
    return (round(b[0]),round(gs[n].width-b[2]))
worse=[]
for w in (200,400,700,900):
    for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789":
        n=cm[ord(ch)]; N=sb({"wght":w,"wdth":100},n); E=sb({"wght":w,"wdth":112},n)
        # Expanded side bearing should not be tighter than Normal's (it is a wider setting)
        for side,(nv,ev) in zip(("L","R"),zip(N,E)):
            if ev < nv-2: worse.append((w,ch,side,nv,ev))
print("sidebearings where Expanded is TIGHTER than Normal by >2u:",len(worse))
for r in worse[:40]: print("  wght=%d %s %s: normal=%d expanded=%d"%r)
