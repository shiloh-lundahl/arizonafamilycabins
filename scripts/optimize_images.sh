#!/bin/bash
# Optimize photos for the web: sharp but small, so they never slow the site.
#
# Usage:
#   scripts/optimize_images.sh <output_dir> <file1> [file2 ...]
#   scripts/optimize_images.sh <output_dir> "<source_folder>"/*.jpg
#
# What it does per image:
#   - Resizes the long edge down to 1600px (plenty sharp for full-screen; never upsizes)
#   - Re-encodes as JPEG at quality 80 (crisp, but a fraction of the original size)
#   - Reports the before/after file size
#
# Target: most photos land around 150-400 KB. Phone photos of 5-12 MB shrink ~95%.

set -e
MAXPX=1600
QUALITY=80

OUT="$1"; shift
if [ -z "$OUT" ] || [ "$#" -eq 0 ]; then
  echo "Usage: $0 <output_dir> <image files...>"
  exit 1
fi
mkdir -p "$OUT"

for src in "$@"; do
  [ -f "$src" ] || continue
  base=$(basename "$src")
  name="${base%.*}"
  dest="$OUT/${name}.jpg"
  before=$(stat -f%z "$src" 2>/dev/null || echo 0)
  cp "$src" "$dest"
  sips --resampleHeightWidthMax "$MAXPX" "$dest" >/dev/null 2>&1 || true
  sips -s format jpeg -s formatOptions "$QUALITY" "$dest" >/dev/null 2>&1 || true
  after=$(stat -f%z "$dest" 2>/dev/null || echo 0)
  bkb=$(( before / 1024 )); akb=$(( after / 1024 ))
  echo "✓ ${base}  ${bkb}KB → ${akb}KB  ($dest)"
done
echo "Done. Optimized $# image(s) into $OUT/"
