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
. /etc/os-release
case "$ID" in ubuntu|debian) ;; *) echo "ВНИМАНИЕ: проверено на Ubuntu и Debian, у вас $PRETTY_NAME" ;; esac
export DEBIAN_FRONTEND=noninteractive

say "Пакеты"
apt-get update -q
apt-get install -y -q ca-certificates curl git rsync nginx certbot ufw fail2ban unattended-upgrades cron \
  age python3 python3-jinja2 >/dev/null
echo "  ok"

say "Docker"
if ! docker compose version >/dev/null 2>&1; then
  apt-get install -y -q docker.io docker-compose-v2 >/dev/null 2>&1 \
    || apt-get install -y -q docker.io docker-compose-plugin >/dev/null 2>&1 \
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
if [ "$mem_mb" -lt 2000 ] && [ -z "$(swapon --noheadings)" ]; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  echo "  ОЗУ $mem_mb МБ — добавлен swap 2 ГБ (сборка образа и PostgreSQL не упрутся в память)"
else
  echo "  ОЗУ $mem_mb МБ — ok"
fi

say "Система: время, обновления безопасности"
timedatectl set-timezone Europe/Moscow 2>/dev/null || ln -sf /usr/share/zoneinfo/Europe/Moscow /etc/localtime
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF
systemctl enable --now fail2ban >/dev/null 2>&1 || true
echo "  часовой пояс Europe/Moscow, автообновления безопасности, fail2ban для ssh"

say "Файрвол"
ssh_ports="$( (sshd -T 2>/dev/null || true) | awk '$1=="port"{print $2}' | sort -u)"
[ -n "$ssh_ports" ] || ssh_ports=22
for p in $ssh_ports; do ufw allow "$p/tcp" >/dev/null; done
ufw allow 80/tcp >/dev/null
ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null
echo "  открыты: ssh ($ssh_ports), 80, 443. API и база снаружи недоступны"

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
