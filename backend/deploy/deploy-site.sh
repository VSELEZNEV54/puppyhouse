#!/bin/sh
# Copy ONLY the built site (pages listed in .build-manifest.json + assets/) into the nginx docroot.
# Never serve the git checkout itself: it contains backend/, src/, tools/, docs/.
#   backend/deploy/deploy-site.sh /path/to/checkout /var/www/domshchenkov
set -eu
SRC="${1:?checkout path}"
DST="${2:-/var/www/domshchenkov}"
cd "$SRC"
python3 tools/build.py
TMP="$(mktemp)"
python3 - "$TMP" <<'PY'
import json, sys
m = json.load(open(".build-manifest.json", encoding="utf-8"))
with open(sys.argv[1], "w", encoding="utf-8") as f:
    for p in m["files"]:
        f.write(p + "\n")
    f.write("assets/\n")
PY
mkdir -p "$DST"
rsync -a --delete --files-from="$TMP" --recursive ./ "$DST"/
rm -f "$TMP"
echo "site → $DST"
