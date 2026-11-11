#!/usr/bin/env bash
# Sealed settings: a value for api.env sent through the PUBLIC repository encrypted, so that only this server can read
# it — e.g. the Telegram proxy with its login and password (11.11.2026: api.telegram.org closed for the server).
#   sealed.sh key   <etc> <site dir>    the server's RSA key, made once in <etc>/sealed.key (600, never leaves the
#                                       server); its public half → <site dir>/dsh-sealed-key.txt (https://<site>/…)
#   sealed.sh apply <etc> <sealed dir>  <sealed dir>/<NAME>.enc → <etc>/sealed.env, which docker-compose.yml reads
#                                       after api.env (so it wins). Only the names in ALLOWED. Prints «changed» when
#                                       sealed.env changed.
# To seal a value (the developer, anywhere):
#   curl -s https://<site>/dsh-sealed-key.txt > k.pem
#   printf %s 'socks5://login:password@host:port' | openssl pkeyutl -encrypt -pubin -inkey k.pem \
#     -pkeyopt rsa_padding_mode:oaep -pkeyopt rsa_oaep_md:sha256 | base64 -w0 > backend/deploy/sealed/DSH_TELEGRAM_PROXY.enc
# To drop a value: delete its .enc file (the next deploy removes it from sealed.env; api.env applies again).
set -euo pipefail
ALLOWED="DSH_TELEGRAM_PROXY DSH_TELEGRAM_CHAT_ID"
cmd="${1:-}"
case "$cmd" in
  key)
    etc="${2:?etc}"; site="${3:?site dir}"
    key="$etc/sealed.key"
    if [ ! -s "$key" ]; then
      (umask 077; openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out "$key" 2>/dev/null)
    fi
    chmod 600 "$key"
    openssl pkey -in "$key" -pubout -out "$site/dsh-sealed-key.txt"
    chmod 644 "$site/dsh-sealed-key.txt"
    ;;
  apply)
    etc="${2:?etc}"; dir="${3:?sealed dir}"
    key="$etc/sealed.key" out="$etc/sealed.env"
    tmp="$(mktemp)"; chmod 600 "$tmp"
    for f in "$dir"/*.enc; do
      [ -e "$f" ] || continue
      name="$(basename "$f" .enc)"
      case " $ALLOWED " in *" $name "*) ;; *) echo "sealed: $name нет в списке разрешённых — пропущен" >&2; continue ;; esac
      if ! value="$(base64 -d "$f" 2>/dev/null | openssl pkeyutl -decrypt -inkey "$key" \
                      -pkeyopt rsa_padding_mode:oaep -pkeyopt rsa_oaep_md:sha256 2>/dev/null)"; then
        echo "sealed: $name не расшифровался ключом этого сервера — пропущен" >&2; continue
      fi
      case "$value" in
        ""|*$'\n'*|*$'\r'*|*"'"*) echo "sealed: $name — пустое, многострочное или с кавычкой — пропущен" >&2; continue ;;
      esac
      printf "%s='%s'\n" "$name" "$value" >> "$tmp"   # single quotes: compose takes the value as is, no ${…}
    done
    if [ -f "$out" ] && cmp -s "$tmp" "$out"; then
      rm -f "$tmp"
    else
      had=0; [ -s "$out" ] && had=1
      install -m 600 "$tmp" "$out"; rm -f "$tmp"
      { [ -s "$out" ] || [ "$had" = 1 ]; } && echo changed
    fi
    ;;
  *) sed -n '2,15p' "$0"; exit 2 ;;
esac
