#!/usr/bin/env bash
# Pack a release of домщенков.рф — the built site + the API + the server scripts — into one folder (and archive):
#   tools/release.sh                      → dist/domshchenkov-<version>/ and dist/domshchenkov-<version>.tar.gz
#   tools/release.sh --out DIR --no-tar   (backend/deploy/deploy.sh calls this in a git checkout on the server)
# Version: <YYYYmmdd-HHMMSS>-<git sha>[-dirty]. Needs python3 + jinja2 (the site build); git is optional.
# Layout of a release:
#   site/        the docroot: published pages (src/data/publish.json), assets, 404.html, robots.txt, sitemap.xml,
#                site.webmanifest, favicon.ico (nothing else of the repo)
#   backend/     the API, its Dockerfile, docker-compose.yml, deploy/ (deploy.sh, server-setup.sh, nginx.conf, …)
#   src/data/    the catalog and the consent texts the API reads
#   tools/check_launch.py, .dockerignore, VERSION, LAUNCH-CHECKLIST.md, DEPLOY.md, deploy.sh → backend/deploy/deploy.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
OUT="$ROOT/dist"
TAR=1
while [ $# -gt 0 ]; do
  case "$1" in
    --out) OUT="$2"; shift 2 ;;
    --no-tar) TAR=0; shift ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "release: unknown option $1" >&2; exit 2 ;;
  esac
done
cd "$ROOT"

if git rev-parse --git-dir >/dev/null 2>&1; then
  sha="$(git rev-parse --short=8 HEAD)"
  dirty=""
  [ -n "$(git status --porcelain -- backend src tools assets 2>/dev/null)" ] && dirty="-dirty"
else
  sha="nogit"; dirty=""
fi
VERSION="$(date +%Y%m%d-%H%M%S)-$sha$dirty"
NAME="domshchenkov-$VERSION"
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"
DEST="$OUT/$NAME"
[ -e "$DEST" ] && { echo "release: $DEST already exists" >&2; exit 1; }
TMP="$(mktemp -d "$OUT/.$NAME.XXXX")"
trap 'rm -rf "$TMP"' EXIT

echo "== сайт: сборка"
python3 tools/build.py --clean   # exits non-zero on a broken page or template

echo "== сайт: папка для сервера"
python3 - "$TMP/site" <<'PY'
import json, shutil, sys
from pathlib import Path
stage = Path(sys.argv[1])
files = json.load(open(".build-manifest.json", encoding="utf-8"))["files"]
for rel in files:
    dst = stage / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(rel, dst)
shutil.copytree("assets", stage / "assets")
# written by tools/build.py (tools/seo.py) next to the pages: they are not in the manifest's page list
extras = ["404.html", "robots.txt", "sitemap.xml", "site.webmanifest", "favicon.ico"]
missing = [f for f in extras if not Path(f).is_file()]
if missing:
    sys.exit(f"release: the build did not write {missing} (tools/build.py → tools/seo.py)")
for f in extras:
    shutil.copy2(f, stage / f)
# 404.html in the repo writes <base> from a script ("/" here, "/puppyhouse/" on the GitHub Pages preview). The
# browser's preload scanner does not run it and first fetches every asset of a missing /a/b/ as /a/b/assets/… —
# a second round of 404s. The server's copy gets a plain <base href="/">.
import re
p = stage / "404.html"
s, n = re.subn(r"<script>document\.write\('<base href=.*?</script>", '<base href="/">', p.read_text(encoding="utf-8"), count=1)
if n != 1:
    sys.exit("release: 404.html has no <base> script to replace (src/templates/pages/404.html.j2)")
p.write_text(s, encoding="utf-8")
print(f"   {len(files)} pages + assets/ + {', '.join(extras)}")
PY

echo "== API и скрипты сервера"
if git rev-parse --git-dir >/dev/null 2>&1; then
  # tracked + new files, never what .gitignore hides (.env, caches); tests stay in the repo
  git ls-files -z -co --exclude-standard -- backend src/data tools/check_launch.py .dockerignore DEPLOY.md \
    | grep -zv '^backend/tests/' \
    | while IFS= read -r -d '' f; do [ -f "$f" ] && install -D -m "$( [ -x "$f" ] && echo 755 || echo 644 )" "$f" "$TMP/$f"; done
else
  for d in backend src/data; do
    rsync -a --exclude 'tests/' --exclude '__pycache__/' --exclude '.env' --exclude '.env.*' --include '.env.example' \
      --exclude '.pytest_cache/' --exclude '.venv/' "$d/" "$TMP/$d/"
  done
  install -D -m 644 tools/check_launch.py "$TMP/tools/check_launch.py"
  install -m 644 .dockerignore DEPLOY.md "$TMP/"
fi
for must in backend/Dockerfile backend/docker-compose.yml backend/deploy/deploy.sh backend/admin_ui/index.html \
            src/data/consent.json src/data/puppies.json .dockerignore; do
  [ -f "$TMP/$must" ] || { echo "release: $must is missing" >&2; exit 1; }
done
ln -s backend/deploy/deploy.sh "$TMP/deploy.sh"
echo "$VERSION" > "$TMP/VERSION"
python3 tools/check_launch.py --md "$TMP/LAUNCH-CHECKLIST.md" --quiet

chmod -R go-w "$TMP"
chmod 755 "$TMP"
mv "$TMP" "$DEST"
trap - EXIT
echo "== готово: $DEST ($(du -sh "$DEST" | cut -f1))"
if [ "$TAR" = 1 ]; then
  tar -C "$OUT" -czf "$OUT/$NAME.tar.gz" "$NAME"
  (cd "$OUT" && sha256sum "$NAME.tar.gz" > "$NAME.tar.gz.sha256")
  echo "   архив: $OUT/$NAME.tar.gz ($(du -h "$OUT/$NAME.tar.gz" | cut -f1)), контрольная сумма рядом (.sha256)"
fi
echo "RELEASE_DIR=$DEST"
