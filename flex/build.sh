#!/usr/bin/env bash
# Rebuild Reddit Sans Flex from the upstream Glyphs sources in ../sources.
#   ./build.sh          merge sources, write designspace, compile the variable font into build/out
#   ./build.sh verify   also build upstream Sans/Condensed from source and run the comparison + diagnostics
# Needs: pip install -r requirements.txt
set -euo pipefail
cd "$(dirname "$0")"
UP=../sources
OUT=build
rm -rf "$OUT/ds" "$OUT/out"; mkdir -p "$OUT"

python scripts/11_merge.py "$UP" "$OUT/RedditSansFlex.glyphs"
python scripts/20_write_designspace.py "$OUT/RedditSansFlex.glyphs" "$OUT/ds"
fontmake -m "$OUT/ds/RedditSansFlex.designspace" -o variable --output-dir "$OUT/out"
echo "built: $OUT/out/RedditSansFlex-VF.ttf"

if [ "${1:-}" = "verify" ]; then
  mkdir -p "$OUT/ref/sans" "$OUT/ref/cond"
  fontmake -g "$UP/RedditSans.glyphs"          -o variable --output-dir "$OUT/ref/sans"
  fontmake -g "$UP/RedditSansCondensed.glyphs" -o variable --output-dir "$OUT/ref/cond"
  # A: wdth=100 == upstream Sans, B: wdth=88 == upstream Condensed (built from the same sources), C: Expanded sanity
  python scripts/30_verify.py "$OUT/out/RedditSansFlex-VF.ttf" "$OUT/ref/sans/RedditSans-VF.ttf" "$OUT/ref/cond/RedditSansCondensed-VF.ttf"
  python scripts/34_correspondence.py "$OUT/RedditSansFlex.glyphs" 60 > "$OUT/correspondence.txt"   # info only: large Sans/Condensed point differences
  head -1 "$OUT/correspondence.txt"
  python scripts/35_shift_check.py "$OUT/RedditSansFlex.glyphs" 3                  # must report 0 twists
  python scripts/37_sidebearings.py "$OUT/out/RedditSansFlex-VF.ttf"               # must report 0 tighter-than-Normal sidebearings
  python scripts/38_mark_alignment.py "$OUT/RedditSansFlex.glyphs"                 # accent attachment (a few multi-mark glyphs expected)
fi
