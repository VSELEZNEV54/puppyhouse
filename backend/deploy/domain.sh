#!/usr/bin/env bash
# Addresses of the site — one place for deploy.sh and dsh (02.11.2026: the move from домщенков.рф to дом-щенков.рф).
#   domain.sh canon          the host the site is served on: дом-щенков.рф once its certificate exists, the first
#                            address домщенков.рф until then (so nothing breaks while the new DNS is not ready)
#   domain.sh cert           certificate of дом-щенков.рф for those of its names whose DNS points to this server
#                            (www.дом-щенков.рф, dom-shchenkov.ru, www.dom-shchenkov.ru join when they point here);
#                            after a failed attempt the next one waits 20 minutes (Let's Encrypt allows 5 failed
#                            checks per name an hour); DSH_FORCE=1 tries at once (dsh domain)
#   domain.sh nginx IN OUT   the release's nginx.conf (@CANON@, @CERT@, @REDIRECTS@) → the server's config: the site
#                            on the canonical host, one 301 to it from every other name that has a certificate
#   domain.sh stamp          one line: the canonical host and the names of the certificates in use
#   domain.sh due            cert, then exit 0 if the stamp differs from the last deploy (dsh autoupdate → deploy again)
#   domain.sh status         what points where, which certificates exist
# Tests: DSH_LE_LIVE, DSH_STATE, DSH_ACME_ROOT, DSH_MY_IPS («ip ip»), DSH_FAKE_DNS («name=ip,ip name=ip»), DSH_CERTBOT.
set -euo pipefail

NEW=xn----dtbefzjjef0i.xn--p1ai            # дом-щенков.рф — the site's address since 02.11.2026
OLD=xn--b1adduihee9g.xn--p1ai              # домщенков.рф — the first address: one 301 to the new one
ALIASES=("www.$NEW" dom-shchenkov.ru www.dom-shchenkov.ru)   # one 301 to the new address once their DNS points here
LIVE="${DSH_LE_LIVE:-/etc/letsencrypt/live}"
STATE="${DSH_STATE:-/opt/domshchenkov/state}"
ACME_ROOT="${DSH_ACME_ROOT:-/var/www/letsencrypt}"

human() { case "$1" in "$NEW") echo "дом-щенков.рф" ;; "$OLD") echo "домщенков.рф" ;; *) echo "$1" ;; esac; }
my_ips() {
  if [ -n "${DSH_MY_IPS:-}" ]; then tr ' ' '\n' <<<"$DSH_MY_IPS"; return; fi
  ip -o addr show scope global | awk '{split($4, a, "/"); print a[1]}'
}
resolve() {  # every address of a name, one per line; nothing if it does not resolve
  if [ -n "${DSH_FAKE_DNS+x}" ]; then
    tr ' ' '\n' <<<"$DSH_FAKE_DNS" | sed -n "s/^$1=//p" | tr ',' '\n' | sed '/^$/d'
    return 0
  fi
  getent ahosts "$1" 2>/dev/null | awk '{print $1}' | sort -u || true
}
points_here() {  # every address of the name is this server's: an AAAA elsewhere would fail the Let's Encrypt check
  local ips; ips="$(resolve "$1")"
  [ -n "$ips" ] || return 1
  ! grep -qvxFf <(my_ips) <<<"$ips"
}
sans() {  # names of the certificate in folder $1, one per line
  [ -s "$1/fullchain.pem" ] || return 0
  openssl x509 -noout -ext subjectAltName -in "$1/fullchain.pem" 2>/dev/null | grep -o 'DNS:[^, ]*' | cut -c5- | sort -u || true
}
canon() { if [ -s "$LIVE/$NEW/fullchain.pem" ]; then echo "$NEW"; else echo "$OLD"; fi; }

cert() {
  if ! points_here "$NEW"; then
    [ -n "${DSH_QUIET:-}" ] || echo "дом-щенков.рф ещё не указывает на этот сервер ($(resolve "$NEW" | tr '\n' ' ')) — сайт работает на $(human "$(canon)")"
    return 0
  fi
  local want=("$NEW") have missing=() n
  for n in "${ALIASES[@]}"; do points_here "$n" && want+=("$n"); done
  have="$(sans "$LIVE/$NEW")"
  for n in "${want[@]}"; do grep -qxF "$n" <<<"$have" || missing+=("$n"); done
  [ "${#missing[@]}" -gt 0 ] || return 0
  local fail="$STATE/cert-failed" args=()
  if [ -z "${DSH_FORCE:-}" ] && [ -f "$fail" ] && [ $(( $(date +%s) - $(stat -c %Y "$fail") )) -lt 1200 ]; then
    [ -n "${DSH_QUIET:-}" ] || echo "сертификат для ${missing[*]}: прошлая попытка не удалась, следующая — через 20 минут после неё (сразу: dsh domain)"
    return 0
  fi
  for n in "${want[@]}"; do args+=(-d "$n"); done
  echo "сертификат дом-щенков.рф: ${want[*]}"
  if "${DSH_CERTBOT:-certbot}" certonly --webroot -w "$ACME_ROOT" --cert-name "$NEW" "${args[@]}" --expand -n \
       --agree-tos --deploy-hook "systemctl reload nginx"; then
    rm -f "$fail"
  else
    mkdir -p "$STATE"; touch "$fail"
    echo "certbot не получил сертификат — сайт остаётся на $(human "$(canon)"); новая попытка через 20 минут" >&2
  fi
  return 0
}

redirect_block() {  # "names" certificate-folder target-host
  cat <<EOF

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name $1;
    ssl_certificate     $2/fullchain.pem;
    ssl_certificate_key $2/privkey.pem;
    server_tokens off;
    return 301 https://$3\$request_uri;
}
EOF
}

nginx_conf() {  # IN OUT
  local in="$1" out="$2" c cdir names blocks
  c="$(canon)"; cdir="$LIVE/$c"
  blocks="$(mktemp)"
  names="$(sans "$cdir" | grep -vxF "$c" | tr '\n' ' ' || true)"
  [ -z "${names// /}" ] || redirect_block "$names" "$cdir" "$c" >> "$blocks"
  if [ "$c" != "$OLD" ] && [ -s "$LIVE/$OLD/fullchain.pem" ]; then
    names="$(sans "$LIVE/$OLD" | tr '\n' ' ')"
    [ -n "${names// /}" ] || names="$OLD"
    redirect_block "$names" "$LIVE/$OLD" "$c" >> "$blocks"
  fi
  sed -e "s|@CANON@|$c|g" -e "s|@CERT@|$cdir|g" -e "/^# @REDIRECTS@\$/{r $blocks" -e 'd}' "$in" > "$out"
  rm -f "$blocks"
}

stamp() {
  local c; c="$(canon)"
  printf '%s|%s|%s\n' "$c" "$(sans "$LIVE/$c" | tr '\n' ',')" \
    "$( [ "$c" = "$OLD" ] || sans "$LIVE/$OLD" | tr '\n' ',')"
}

due() {
  DSH_QUIET=1 cert
  local now; now="$(stamp)"
  [ "$now" != "$(cat "$STATE/domain-stamp" 2>/dev/null || true)" ] || return 1
  [ "$now" != "$(cat "$STATE/domain-failed" 2>/dev/null || true)" ] || return 1   # that state failed to deploy
  return 0
}

status() {
  local n ips
  echo "сайт работает на: $(human "$(canon)") ($(canon))"
  echo "адреса сервера: $(my_ips | tr '\n' ' ')"
  for n in "$NEW" "${ALIASES[@]}" "$OLD" "www.$OLD"; do
    ips="$(resolve "$n" | tr '\n' ' ')"
    if points_here "$n"; then printf '  %-40s → %s (этот сервер)\n' "$n" "$ips"
    else printf '  %-40s → %s\n' "$n" "${ips:-не найден в DNS}"; fi
  done
  for n in "$NEW" "$OLD"; do
    if [ -s "$LIVE/$n/fullchain.pem" ]; then
      echo "сертификат $(human "$n"): $(sans "$LIVE/$n" | tr '\n' ' ')— до $(openssl x509 -enddate -noout -in "$LIVE/$n/fullchain.pem" | cut -d= -f2)"
    else
      echo "сертификат $(human "$n"): нет"
    fi
  done
}

case "${1:-status}" in
  canon) canon ;;
  cert) cert ;;
  nginx) [ $# -eq 3 ] || { echo "domain.sh nginx IN OUT" >&2; exit 2; }; nginx_conf "$2" "$3" ;;
  stamp) stamp ;;
  due) due ;;
  status) status ;;
  *) sed -n '2,13p' "$0"; exit 2 ;;
esac
