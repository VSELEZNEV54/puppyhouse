#!/usr/bin/env bash
# One-time preparation of a fresh server for домщенков.рф (Ubuntu 22.04 / 24.04 or Debian 12, as root).
# Safe to run again: it never overwrites the secrets, the backup key or a working certificate.
#   server-setup.sh --email you@example.ru [--no-cert] [--skip-dns-check]
#     --email           address for Let's Encrypt (expiry warnings), required for the certificate
#     --no-cert         skip HTTPS for now (e.g. DNS is not switched yet); run again later without it
#     --skip-dns-check  get the certificate even if the domain does not seem to point to this server
# What it does: packages (docker, nginx, certbot, ufw, fail2ban, age, python3-jinja2), Docker log rotation and
# Docker Hub mirrors, swap on small servers, firewall (ssh, 80, 443), Moscow time, automatic security updates,
# folders, secrets in /etc/domshchenkov (db.env, api.env, backup.env), a backup key, the nightly backup in cron,
# the Let's Encrypt certificate (webroot, auto-renewal). The site itself goes up with deploy.sh afterwards.
set -euo pipefail

DOMAIN="xn--b1adduihee9g.xn--p1ai"        # домщенков.рф
APP_ROOT=/opt/domshchenkov
ETC=/etc/domshchenkov
ACME_ROOT=/var/www/letsencrypt
MIRRORS="${DSH_DOCKER_MIRRORS:-https://mirror.gcr.io https://dockerhub.timeweb.cloud}"
EMAIL=""; CERT=1; DNS_CHECK=1
while [ $# -gt 0 ]; do
  case "$1" in
    --email) EMAIL="$2"; shift 2 ;;
    --no-cert) CERT=0; shift ;;
    --skip-dns-check) DNS_CHECK=0; shift ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "server-setup: unknown option $1" >&2; exit 2 ;;
  esac
done
say() { printf '\n== %s\n' "$*"; }
die() { printf '\nОШИБКА: %s\n' "$*" >&2; exit 1; }
[ "$(id -u)" = 0 ] || die "запустите от root (sudo)"
SRC="$(cd "$(dirname "$(readlink -f "$0")")/../.." && pwd)"
[ -f "$SRC/backend/.env.example" ] || die "запускайте из репозитория или релиза: backend/deploy/server-setup.sh"
[ "$CERT" = 0 ] || [ -n "$EMAIL" ] || die "укажите почту для сертификата: --email you@example.ru (или --no-cert)"
# Let's Encrypt registers the address: a real one, in Latin letters (not the «ваша@почта.ru» sample from the guide);
# a .рф domain in its Latin form passes: info@xn--b1adduihee9g.xn--p1ai
if [ "$CERT" = 1 ] && ! LC_ALL=C grep -Eq '^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.([A-Za-z]{2,}|xn--[A-Za-z0-9-]{2,})$' <<<"$EMAIL"; then
  die "почта «$EMAIL» не подходит для сертификата: нужна ваша настоящая почта латиницей, например name@yandex.ru"
fi
. /etc/os-release
case "$ID" in ubuntu|debian) ;; *) echo "ВНИМАНИЕ: проверено на Ubuntu и Debian, у вас $PRETTY_NAME" ;; esac
export DEBIAN_FRONTEND=noninteractive

say "Пакеты"
# A provider's mirror (Timeweb: mirror.timeweb.ru) can serve the package lists and still refuse the downloads.
# Then: retry, then IPv4 only, then the official archive of the distribution — for this run only, the system's apt
# sources stay as they are (security updates keep using them).
APT_OPTS=(-o Acquire::Retries=3 -o Acquire::http::Timeout=30)
apt_get() { apt-get "${APT_OPTS[@]}" "$@"; }
PKGS=(ca-certificates curl git rsync nginx certbot ufw fail2ban python3-systemd unattended-upgrades cron age
      python3 python3-jinja2)
# Docker from the system's repositories (docker.io + docker-compose-v2: Ubuntu 22.04+) goes in the same download, so
# it gets the same fallback, also on a re-run where everything else is installed. Where there is no
# docker-compose-v2 (Debian 12), the Docker step below takes it from download.docker.com.
apt_all() {
  apt_get update -q || return 1
  local extra=()
  if ! docker compose version >/dev/null 2>&1 && apt-cache "${APT_OPTS[@]}" show docker-compose-v2 >/dev/null 2>&1; then
    extra=(docker.io docker-compose-v2)
  fi
  apt_get install -y -q "${PKGS[@]}" "${extra[@]}" >/dev/null
}
official_sources() {  # a sources dir with only the official archive of this release
  local d; d="$(mktemp -d)"
  case "$ID" in
    ubuntu) printf '%s\n' "Types: deb" "URIs: http://archive.ubuntu.com/ubuntu" \
              "Suites: $VERSION_CODENAME $VERSION_CODENAME-updates $VERSION_CODENAME-security" \
              "Components: main restricted universe multiverse" \
              "Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg" > "$d/official.sources" ;;
    debian) printf '%s\n' "Types: deb" "URIs: http://deb.debian.org/debian" \
              "Suites: $VERSION_CODENAME $VERSION_CODENAME-updates" "Components: main" \
              "Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg" "" \
              "Types: deb" "URIs: http://security.debian.org/debian-security" "Suites: $VERSION_CODENAME-security" \
              "Components: main" "Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg" > "$d/official.sources" ;;
    *) rm -rf "$d"; return 1 ;;
  esac
  echo "$d"
}
if ! apt_all; then
  echo "  зеркало пакетов не отдало файлы — повторяю только по IPv4"
  APT_OPTS+=(-o Acquire::ForceIPv4=true)
  if ! apt_all; then
    src_dir="$(official_sources)" || die "не удалось скачать пакеты (см. ошибки apt выше)"
    echo "  зеркало провайдера недоступно — беру пакеты с официального зеркала (${ID}) для этой установки"
    APT_OPTS+=(-o "Dir::Etc::SourceList=/dev/null" -o "Dir::Etc::SourceParts=$src_dir")
    apt_all || die "не удалось скачать пакеты ни с зеркала провайдера, ни с официального (см. ошибки apt выше)"
  fi
fi
echo "  ok"

say "Docker"
if ! docker compose version >/dev/null 2>&1; then
  apt_get install -y -q docker.io docker-compose-v2 >/dev/null 2>&1 \
    || apt_get install -y -q docker.io docker-compose-plugin >/dev/null 2>&1 \
    || { echo "  пакетов compose v2 нет в репозиториях системы — ставлю с download.docker.com"; curl -fsSL https://get.docker.com | sh; }
fi
docker compose version >/dev/null 2>&1 || die "docker compose v2 не установился"
if [ ! -f /etc/docker/daemon.json ]; then
  mkdir -p /etc/docker
  python3 - "$MIRRORS" > /etc/docker/daemon.json <<'PY'
import json, sys
print(json.dumps({"log-driver": "json-file", "log-opts": {"max-size": "10m", "max-file": "5"},
                  "registry-mirrors": sys.argv[1].split()}, indent=2))
PY
  systemctl restart docker
  echo "  логи контейнеров ограничены 50 МБ; зеркала Docker Hub: $MIRRORS"
else
  echo "  /etc/docker/daemon.json уже есть — не трогаю"
fi
systemctl enable --now docker >/dev/null 2>&1 || true
docker compose version

say "Память"
mem_mb=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
if [ "$mem_mb" -lt 2000 ] && [ -z "$(swapon --noheadings 2>/dev/null || true)" ]; then
  created=0
  if [ ! -f /swapfile ]; then
    fallocate -l 2G /swapfile 2>/dev/null && chmod 600 /swapfile && mkswap /swapfile >/dev/null 2>&1 && created=1
  fi
  if [ -f /swapfile ] && swapon /swapfile 2>/dev/null; then
    grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
    echo "  ОЗУ $mem_mb МБ — добавлен swap 2 ГБ (сборка образа и PostgreSQL не упрутся в память)"
  else
    if [ "$created" = 1 ]; then rm -f /swapfile; fi
    echo "  ВНИМАНИЕ: ОЗУ $mem_mb МБ, а swap включить нельзя (так бывает на OpenVZ/LXC) — продолжаю без него"
  fi
else
  echo "  ОЗУ $mem_mb МБ — ok"
fi

say "Система: время, обновления безопасности"
timedatectl set-timezone Europe/Moscow 2>/dev/null || ln -sf /usr/share/zoneinfo/Europe/Moscow /etc/localtime
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF
# sshd jail from the journal: Debian 12 has no /var/log/auth.log (no rsyslog), fail2ban would not start there
mkdir -p /etc/fail2ban/jail.d
printf '[sshd]\nenabled = true\nbackend = systemd\n' > /etc/fail2ban/jail.d/domshchenkov.local
systemctl enable fail2ban >/dev/null 2>&1 || true
systemctl restart fail2ban >/dev/null 2>&1 || true
if systemctl is-active --quiet fail2ban; then f2b="fail2ban защищает ssh"; else f2b="fail2ban НЕ запустился (systemctl status fail2ban)"; fi
echo "  часовой пояс Europe/Moscow, автообновления безопасности; $f2b"

say "Файрвол"
# Every port SSH may listen on, from all sources — a wrong guess here locks you out of the server:
#   sshd -T (Port and ListenAddress host:port; needs /run/sshd), the sshd / systemd sockets actually listening
#   (Ubuntu 24.04 starts ssh through ssh.socket), and the port of this very session.
mkdir -p /run/sshd
ssh_ports="$( {
  (sshd -T 2>/dev/null || true) | awk '$1=="port"{print $2} $1=="listenaddress"{n=split($2,a,":"); print a[n]}'
  (ss -Hltnp 2>/dev/null || true) | awk '/"sshd"/ {n=split($4,a,":"); print a[n]}'
  (systemctl show -p Listen ssh.socket 2>/dev/null || true) | grep -oE ':[0-9]+ \(Stream' | tr -dc '0-9\n'
  if [ -n "${SSH_CONNECTION:-}" ]; then echo "${SSH_CONNECTION##* }"; fi
} | grep -E '^[0-9]+$' | sort -un | tr '\n' ' ' || true)"
if [ -z "${ssh_ports// /}" ]; then
  echo "  ВНИМАНИЕ: не удалось определить порт SSH — файрвол НЕ включаю, чтобы не потерять доступ к серверу."
  echo "  Включите вручную: ufw allow <порт ssh>/tcp && ufw allow 80/tcp && ufw allow 443/tcp && ufw enable"
else
  for p in $ssh_ports; do ufw allow "$p/tcp" >/dev/null; done
  ufw allow 80/tcp >/dev/null
  ufw allow 443/tcp >/dev/null
  ufw --force enable >/dev/null
  echo "  открыты: ssh (${ssh_ports% }), 80, 443. API и база снаружи недоступны"
fi

say "Папки"
install -d -m 755 "$APP_ROOT" "$APP_ROOT/releases" /var/www/domshchenkov "$ACME_ROOT"
install -d -m 700 "$ETC" /var/backups/domshchenkov
echo "  $APP_ROOT, /var/www/domshchenkov, $ETC, /var/backups/domshchenkov"

say "Секреты ($ETC)"
gen() { python3 -c 'import secrets; print(secrets.token_hex(24))'; }
if [ ! -f "$ETC/db.env" ]; then
  sed -e "s/^DSH_OWNER_DB_PASSWORD=.*/DSH_OWNER_DB_PASSWORD=$(gen)/" \
      -e "s/^DSH_APP_DB_PASSWORD=.*/DSH_APP_DB_PASSWORD=$(gen)/" \
      -e "s/^DSH_READONLY_DB_PASSWORD=.*/DSH_READONLY_DB_PASSWORD=$(gen)/" \
      "$SRC/backend/db.env.example" > "$ETC/db.env"
  echo "  db.env: пароли базы созданы"
else
  echo "  db.env уже есть — не трогаю"
fi
if [ ! -f "$ETC/api.env" ]; then
  sed -e "s/^DSH_ERASURE_SECRET=.*/DSH_ERASURE_SECRET=$(gen)/" \
      -e "s|^DSH_ADMIN_BASE_URL=.*|DSH_ADMIN_BASE_URL=https://$DOMAIN/admin/#/leads?lead={id}|" \
      -e "s/^DSH_ENV=.*/DSH_ENV=prod/" \
      "$SRC/backend/.env.example" > "$ETC/api.env"
  echo "  api.env: создан (уведомления в Telegram / на почту настраиваются в нём позже)"
else
  echo "  api.env уже есть — не трогаю"
fi
chmod 600 "$ETC"/*.env

say "Ключ бэкапов"
KEY=/root/domshchenkov-backup-key.txt
if [ ! -f "$ETC/backup.env" ]; then
  if [ ! -f "$KEY" ]; then age-keygen -o "$KEY" 2>/dev/null; chmod 600 "$KEY"; fi
  printf 'AGE_RECIPIENT=%s\nBACKUP_DIR=/var/backups/domshchenkov\nKEEP_DAYS=20\n' "$(age-keygen -y "$KEY")" > "$ETC/backup.env"
  chmod 600 "$ETC/backup.env"
  echo "  ЗАКРЫТЫЙ КЛЮЧ: $KEY — скачайте его к себе (без него бэкап не расшифровать) и удалите с сервера:"
  echo "    scp root@<сервер>:$KEY .   затем на сервере: shred -u $KEY"
else
  echo "  backup.env уже есть — не трогаю"
fi
cat > /etc/cron.d/domshchenkov <<'EOF'
# домщенков.рф: nightly encrypted database backup (Moscow time)
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
30 2 * * * root /usr/local/bin/dsh backup >> /var/log/domshchenkov-backup.log 2>&1 || logger -t domshchenkov-backup FAILED
EOF
cat > /etc/logrotate.d/domshchenkov <<'EOF'
/var/log/domshchenkov-backup.log {
  monthly
  rotate 6
  compress
  missingok
  notifempty
}
EOF
echo "  бэкап каждую ночь в 02:30, хранится 20 дней в /var/backups/domshchenkov"

say "nginx и сертификат"
rm -f /etc/nginx/sites-enabled/default
if [ -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" ]; then
  echo "  сертификат уже есть: $(openssl x509 -enddate -noout -in "/etc/letsencrypt/live/$DOMAIN/fullchain.pem")"
elif [ "$CERT" = 0 ]; then
  echo "  пропускаю (--no-cert). Когда домен будет смотреть на сервер: server-setup.sh --email …"
else
  # an HTTP-only server for the Let's Encrypt check until deploy.sh installs the real config
  cat > /etc/nginx/sites-available/domshchenkov-bootstrap <<EOF
server {
    listen 80 default_server;
    $( [ -f /proc/net/if_inet6 ] && echo 'listen [::]:80 default_server;' )
    server_name _;
    location ^~ /.well-known/acme-challenge/ { root $ACME_ROOT; }
    location / { return 503; }
}
EOF
  [ -e /etc/nginx/sites-enabled/domshchenkov ] || ln -sfn /etc/nginx/sites-available/domshchenkov-bootstrap /etc/nginx/sites-enabled/domshchenkov-bootstrap
  nginx -t -q && systemctl reload nginx
  names=("$DOMAIN")
  my_ips="$(ip -o addr show scope global | awk '{split($4, a, "/"); print a[1]}')"
  points_here() { local ips; ips="$(getent ahosts "$1" | awk '{print $1}' | sort -u)"; [ -n "$ips" ] && grep -qxFf <(echo "$ips") <(echo "$my_ips"); }
  if [ "$DNS_CHECK" = 1 ] && ! points_here "$DOMAIN"; then
    die "домен домщенков.рф не указывает на этот сервер.
  Сейчас: $(getent ahosts "$DOMAIN" | awk '{print $1}' | sort -u | tr '\n' ' ')
  Адреса сервера: $(echo $my_ips)
Пропишите у регистратора A-запись (@ и www) на адрес сервера, подождите обновления DNS и запустите снова.
Если сервер за NAT провайдера и адрес верный: --skip-dns-check"
  fi
  if [ "$DNS_CHECK" = 0 ] || points_here "www.$DOMAIN"; then names+=("www.$DOMAIN"); else echo "  www.домщенков.рф не указывает сюда — сертификат без www"; fi
  args=(); for n in "${names[@]}"; do args+=(-d "$n"); done
  certbot certonly --webroot -w "$ACME_ROOT" "${args[@]}" --email "$EMAIL" --agree-tos --no-eff-email -n \
    --deploy-hook "systemctl reload nginx"
  echo "  сертификат получен; продлевается сам (certbot.timer)"
fi

say "Готово"
cat <<EOF
Дальше:
  1. Выложить сайт и API:      $SRC/backend/deploy/deploy.sh
  2. Создать вход в админку:   dsh app create-admin --login anna --name "Анна" --role admin
  3. Скачать ключ бэкапов к себе и удалить его с сервера (см. выше), если ещё не сделали.
Настройки уведомлений: $ETC/api.env (после правки: dsh restart).
EOF
