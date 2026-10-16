#!/bin/sh
# Nightly encrypted backup, kept in Russia (152-ФЗ localisation), rotated after 30 days so erasures reach backups.
#   cron: 30 2 * * *  /opt/domshchenkov/backend/deploy/backup.sh
# Needs: age (https://age-encryption.org) with the PUBLIC key in AGE_RECIPIENT; the private key stays offline.
# Optional: an S3-compatible bucket of a Russian provider (Yandex Object Storage, Selectel, VK Cloud) via rclone.
set -eu
: "${AGE_RECIPIENT:?set AGE_RECIPIENT (age public key)}"
DIR="${BACKUP_DIR:-/var/backups/domshchenkov}"
KEEP_DAYS="${KEEP_DAYS:-30}"
mkdir -p "$DIR"
STAMP="$(date +%Y-%m-%d_%H%M)"
OUT="$DIR/domshchenkov_$STAMP.dump.age"
cd "$(dirname "$0")/.."
docker compose exec -T postgres pg_dump -U dsh_owner -d domshchenkov -Fc | age -r "$AGE_RECIPIENT" > "$OUT"
find "$DIR" -name 'domshchenkov_*.dump.age' -mtime +"$KEEP_DAYS" -delete
if [ -n "${RCLONE_REMOTE:-}" ]; then
  rclone copy "$OUT" "$RCLONE_REMOTE"
  rclone delete --min-age "${KEEP_DAYS}d" "$RCLONE_REMOTE"
fi
echo "backup → $OUT"
# Restore test (monthly): age -d -i key.txt FILE | pg_restore -d <empty db>
