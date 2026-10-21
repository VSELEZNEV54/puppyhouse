#!/bin/sh
# Fonts the logo generators need (all OFL, from github.com/google/fonts) -> docs/logo/fonts/ (git-ignored).
#   sh docs/logo/tools/get_fonts.sh
set -e
DIR="$(cd "$(dirname "$0")/.." && pwd)/fonts"
mkdir -p "$DIR"
B=https://raw.githubusercontent.com/google/fonts/main/ofl
for p in "nunito/Nunito%5Bwght%5D.ttf" "rubik/Rubik%5Bwght%5D.ttf" "literata/Literata%5Bopsz,wght%5D.ttf" \
         "geist/Geist%5Bwght%5D.ttf" "mplusrounded1c/MPLUSRounded1c-Medium.ttf" "caveat/Caveat%5Bwght%5D.ttf"; do
  f=$(basename "$p" | sed 's/%5B/[/g; s/%5D/]/g')
  [ -f "$DIR/$f" ] || curl -sSfL -o "$DIR/$f" "$B/$p"
  echo "$DIR/$f"
done
