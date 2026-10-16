#!/usr/bin/env bash
# Deploy домщенков.рф on the server (as root). Two ways to call it:
#   git checkout:      /opt/domshchenkov/src/backend/deploy/deploy.sh    — packs a release from the checkout first
#                      (tools/release.sh into /opt/domshchenkov/releases/) and deploys that
#   unpacked release:  /opt/domshchenkov/releases/<version>/deploy.sh
# Steps: checks → API image + database migrations (docker compose) → the API answers → site files → nginx →
# /opt/domshchenkov/current points to this release. If the new API does not come up, the previous release is
# started again and the site files are not touched.
# Options:
#   --allow-placeholders   deploy although the consent texts / privacy policy still contain [placeholders]
#                          (a test launch: do not take real requests and do not run ads on it)
# Needs server-setup.sh done once: docker, nginx, the certificate, /etc/domshchenkov/{db,api}.env.
set -euo pipefail

APP_ROOT="${DSH_APP_ROOT:-/opt/domshchenkov}"
DOCROOT="${DSH_DOCROOT:-/var/www/domshchenkov}"
ETC="${DSH_ETC:-/etc/domshchenkov}"
DOMAIN="xn--b1adduihee9g.xn--p1ai"
NGINX_SITE=/etc/nginx/sites-available/domshchenkov
KEEP_RELEASES=4
ALLOW_PLACEHOLDERS=0
ARGS=("$@")
for a in "$@"; do
  case "$a" in
    --allow-placeholders) ALLOW_PLACEHOLDERS=1 ;;
    -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
    *) echo "deploy: unknown option $a" >&2; exit 2 ;;
  esac
done

say() { printf '\n== %s\n' "$*"; }
die() { printf '\nОШИБКА: %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" = 0 ] || die "запустите от root (sudo)"
HERE="$(cd "$(dirname "$(readlink -f "$0")")/../.." && pwd)"

# ---- a git checkout: pack a release from it and run that release's deploy.sh
if [ ! -f "$HERE/VERSION" ]; then
  [ -f "$HERE/tools/release.sh" ] || die "$HERE — не релиз и не репозиторий"
  python3 -c 'import jinja2' 2>/dev/null || die "для сборки сайта нужен jinja2: apt install python3-jinja2"
  say "Собираю релиз из $HERE"
  mkdir -p "$APP_ROOT/releases"
  out="$(bash "$HERE/tools/release.sh" --out "$APP_ROOT/releases" --no-tar | tee /dev/stderr | sed -n 's/^RELEASE_DIR=//p')"
  [ -n "$out" ] && [ -f "$out/VERSION" ] || die "релиз не собрался"
  exec bash "$out/backend/deploy/deploy.sh" "${ARGS[@]}"
fi

VERSION="$(cat "$HERE/VERSION")"
say "Релиз $VERSION ($HERE)"

# ---- checks before anything changes
for f in "$ETC/db.env" "$ETC/api.env"; do
  [ -f "$f" ] || die "нет $f — сначала backend/deploy/server-setup.sh"
done
grep -q '^DSH_ENV=prod' "$ETC/api.env" || echo "ВНИМАНИЕ: в $ETC/api.env не стоит DSH_ENV=prod"
if grep -q 'change-me' "$ETC/db.env" "$ETC/api.env"; then die "в $ETC/*.env остались значения change-me"; fi
command -v docker >/dev/null && docker compose version >/dev/null 2>&1 || die "нет docker compose — server-setup.sh"
command -v nginx >/dev/null || die "нет nginx — server-setup.sh"
[ -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" ] || die "нет сертификата для $DOMAIN — server-setup.sh"
[ -f "$HERE/site/index.html" ] && [ -f "$HERE/site/404.html" ] || die "в релизе нет собранного сайта (site/)"
if ! python3 "$HERE/tools/check_launch.py" --strict --quiet; then
  if [ "$ALLOW_PLACEHOLDERS" = 1 ]; then
    echo "ВНИМАНИЕ: в согласиях / политике / подвале остались [заглушки] — тестовый запуск, реальные заявки не принимать"
  else
    die "в согласиях, политике или подвале остались [заглушки] (см. $HERE/LAUNCH-CHECKLIST.md).
Заполните их в src/data и соберите новый релиз, или для тестового запуска добавьте --allow-placeholders"
  fi
fi

COMPOSE=(docker compose -f "$HERE/backend/docker-compose.yml" --env-file "$ETC/db.env")
STATE="$APP_ROOT/state"
mkdir -p "$STATE"
PREV_VERSION="$(cat "$STATE/version" 2>/dev/null || true)"
PREV_ROOT="$(cat "$STATE/root" 2>/dev/null || true)"

api_code() { curl -s --noproxy "*" -o /tmp/dsh-health.json -w '%{http_code}' http://127.0.0.1:8000/api/v1/health || true; }
rollback() {
  if [ -n "$PREV_VERSION" ] && [ -f "$PREV_ROOT/backend/docker-compose.yml" ]; then
    echo "Откат: запускаю прошлый релиз $PREV_VERSION" >&2
    DSH_VERSION="$PREV_VERSION" DSH_INITDB_DIR="$APP_ROOT/initdb" docker compose -f "$PREV_ROOT/backend/docker-compose.yml" --env-file "$ETC/db.env" \
      up -d --remove-orphans api worker >&2 || { echo "откат не удался — смотрите: dsh logs" >&2; return; }
    for _ in $(seq 1 30); do
      case "$(api_code)" in 200|503) echo "Прошлый релиз $PREV_VERSION снова работает, сайт не менялся" >&2; return ;; esac
      sleep 2
    done
    echo "прошлый релиз не ответил — смотрите: dsh logs api" >&2
  else
    echo "прошлого релиза нет — откатывать некуда" >&2
  fi
}

# ---- API: image, migrations, start
export DSH_VERSION="$VERSION"
export DSH_INITDB_DIR="$APP_ROOT/initdb"   # the same path for every release → the database container is kept
install -d -m 755 "$DSH_INITDB_DIR"
install -m 755 "$HERE"/backend/deploy/initdb/* "$DSH_INITDB_DIR"/
say "Образ API"
"${COMPOSE[@]}" build api
say "База и API (миграции идут первыми)"
if ! "${COMPOSE[@]}" up -d --remove-orphans; then
  "${COMPOSE[@]}" logs --tail 40 migrate api >&2 || true
  rollback
  die "контейнеры не запустились (выше — последние строки логов)"
fi

say "Проверяю, что API отвечает"
code=000
api_id="$("${COMPOSE[@]}" ps -q api)"
for i in $(seq 1 45); do
  code="$(api_code)"
  [ "$code" = 200 ] || [ "$code" = 503 ] && break
  # a crash on start — no need to wait the full 90 seconds: the container restarts in a loop, or (uvicorn with
  # several workers keeps its master alive and restarts the workers) the log fills with tracebacks
  if [ -n "$api_id" ]; then
    if [ "$(docker inspect -f '{{.RestartCount}}' "$api_id" 2>/dev/null || echo 0)" -ge 2 ] \
       || { [ "$i" -ge 8 ] && [ "$(docker logs "$api_id" 2>&1 | grep -c '^Traceback' || true)" -gt 0 ]; }; then
      code=crash; break
    fi
  fi
  sleep 2
done
case "$code" in
  200) echo "API: ok" ;;
  503) echo "ВНИМАНИЕ: API работает, но сообщает о проблеме: $(cat /tmp/dsh-health.json)"
       echo "          подробности: dsh logs api / dsh logs worker" ;;
  *)   "${COMPOSE[@]}" logs --tail 60 api >&2 || true
       rollback
       die "новый API не запустился (код $code) — выше последние строки его лога" ;;
esac
docker tag "domshchenkov-api:$VERSION" domshchenkov-api:latest   # `dsh` and backup.sh use the current image

# ---- site files
say "Сайт → $DOCROOT"
mkdir -p "$DOCROOT"
rsync -a --delete --delay-updates --chmod=D755,F644 "$HERE/site/" "$DOCROOT/"

# ---- nginx: this release's config; the old one comes back if the new one does not pass `nginx -t`
say "nginx"
install -D -m 644 "$HERE/backend/deploy/nginx-snippets/dsh-proxy.conf" /etc/nginx/snippets/dsh-proxy.conf
NEW_CONF="$(mktemp)"
cp "$HERE/backend/deploy/nginx.conf" "$NEW_CONF"
[ -f /proc/net/if_inet6 ] || sed -i '/listen \[::\]/d' "$NEW_CONF"   # a server without IPv6
BACKUP_CONF=""
if [ -f "$NGINX_SITE" ]; then BACKUP_CONF="$(mktemp)"; cp "$NGINX_SITE" "$BACKUP_CONF"; fi
install -m 644 "$NEW_CONF" "$NGINX_SITE"
rm -f "$NEW_CONF"
ln -sfn "$NGINX_SITE" /etc/nginx/sites-enabled/domshchenkov
rm -f /etc/nginx/sites-enabled/domshchenkov-bootstrap /etc/nginx/sites-enabled/default
if ! nginx -t 2>/tmp/dsh-nginx.txt; then
  cat /tmp/dsh-nginx.txt >&2
  if [ -n "$BACKUP_CONF" ]; then install -m 644 "$BACKUP_CONF" "$NGINX_SITE"; fi
  die "новая конфигурация nginx с ошибкой — оставлена прежняя"
fi
systemctl reload nginx
rm -f "$BACKUP_CONF"

# ---- this release is the current one
ln -sfn "$HERE" "$APP_ROOT/current"
if [ -n "$PREV_VERSION" ] && [ "$PREV_VERSION" != "$VERSION" ]; then   # for `dsh rollback`
  echo "$PREV_VERSION" > "$STATE/prev_version"
  echo "$PREV_ROOT" > "$STATE/prev_root"
fi
echo "$VERSION" > "$STATE/version"
echo "$HERE" > "$STATE/root"
install -m 755 "$HERE/backend/deploy/dsh" /usr/local/bin/dsh

say "Проверка снаружи (через nginx)"
fail=0
check() {  # url, expected code, [text that must be in the page]
  local body code
  body="$(mktemp)"
  code="$(curl -s --noproxy "*" -o "$body" -w '%{http_code}' --resolve "$DOMAIN:443:127.0.0.1" "https://$DOMAIN$1" || true)"
  if [ "$code" = "$2" ] && { [ -z "${3:-}" ] || grep -q "$3" "$body"; }; then
    echo "  ok   $1 → $code"
  else
    echo "  FAIL $1 → $code (ожидали $2${3:+, текст «$3»})"; fail=1
  fi
  rm -f "$body"
}
check / 200 'dsh-api'
check /maltipu/ 200
check /admin/ 200 'admin.js'
check /robots.txt 200 'Sitemap'
check /sitemap.xml 200 '<urlset'
check /net-takoj-stranicy/ 404 'Такой страницы нет'
check /backend/docker-compose.yml 404
code="$(curl -s --noproxy "*" -o /dev/null -w '%{http_code}' --resolve "$DOMAIN:443:127.0.0.1" "https://$DOMAIN/api/v1/health" || true)"
if [ "$code" = 200 ] || [ "$code" = 503 ]; then echo "  ok   /api/v1/health → $code"; else echo "  FAIL /api/v1/health → $code"; fail=1; fi

# ---- old releases and images
say "Уборка"
mapfile -t old < <(ls -1dt "$APP_ROOT"/releases/domshchenkov-* 2>/dev/null | tail -n +"$((KEEP_RELEASES + 1))")
for d in "${old[@]}"; do
  [ "$d" = "$HERE" ] || [ "$d" = "$PREV_ROOT" ] || { rm -rf "$d"; echo "  удалён $d"; }
done
keep=" $VERSION $PREV_VERSION latest "
for t in $(docker image ls domshchenkov-api --format '{{.Tag}}'); do
  case "$keep" in *" $t "*) ;; *) docker image rm "domshchenkov-api:$t" >/dev/null 2>&1 || true ;; esac
done
docker image prune -f >/dev/null 2>&1 || true

echo
python3 "$HERE/tools/check_launch.py" --quiet || true
if [ "$fail" = 0 ]; then
  echo "Готово: https://домщенков.рф — релиз $VERSION. Админ-панель: https://домщенков.рф/admin/"
else
  echo "Релиз $VERSION выложен, но часть проверок не прошла — см. FAIL выше"; exit 1
fi
