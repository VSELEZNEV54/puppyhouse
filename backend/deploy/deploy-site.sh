#!/usr/bin/env bash
# Copy ONLY the built site (pages listed in .build-manifest.json + assets/) into the nginx docroot.
# Never serve the git checkout itself: it contains backend/, src/, tools/, docs/.
# The site is assembled in a clean staging folder first, so pages removed from the site disappear from the docroot.
#   backend/deploy/deploy-site.sh /path/to/checkout /var/www/domshchenkov
set -euo pipefail
SRC="${1:?checkout path}"
DST="${2:-/var/www/domshchenkov}"
cd "$SRC"
python3 tools/build.py
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
python3 - "$STAGE" <<'PY'
import json, shutil, sys
from pathlib import Path
stage = Path(sys.argv[1])
for rel in json.load(open(".build-manifest.json", encoding="utf-8"))["files"]:
    dst = stage / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(rel, dst)
shutil.copytree("assets", stage / "assets")
PY
mkdir -p "$DST"
rsync -a --delete "$STAGE"/ "$DST"/
echo "site → $DST"
