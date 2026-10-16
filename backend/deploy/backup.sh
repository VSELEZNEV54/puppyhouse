#!/usr/bin/env bash
# Nightly encrypted backup, kept in Russia (152-ФЗ localisation). Kept 20 days: data erased on a request (within
# 10 days of it) leave the backups before the 30-day term ends. After restoring an older copy run
#   python -m app reapply-erasures   — it destroys again everyone erased since (erasure_log keeps keyed hashes).
#   cron: 30 2 * * *  /opt/domshchenkov/backend/deploy/backup.sh || logger -t domshchenkov-backup FAILED
# Needs: age (https://age-encryption.org) with the PUBLIC key in AGE_RECIPIENT; the private key stays offline.
# Optional: an S3-compatible bucket of a Russian provider (Yandex Object Storage, Selectel, VK Cloud) via rclone.
# A new copy is checked (non-empty, readable by pg_restore) BEFORE old ones are rotated; any failure exits non-zero.
set -euo pipefail
umask 077   # the dumps are encrypted, but nobody else needs to read them either
: "${AGE_RECIPIENT:?set AGE_RECIPIENT (age public key)}"
DIR="${BACKUP_DIR:-/var/backups/domshchenkov}"
KEEP_DAYS="${KEEP_DAYS:-20}"
DB_ENV="${DSH_DB_ENV_FILE:-/etc/domshchenkov/db.env}"
cd "$(dirname "$0")/.."
mkdir -p "$DIR"
STAMP="$(date +%Y-%m-%d_%H%M)"
OUT="$DIR/domshchenkov_$STAMP.dump.age"
TMP="$(mktemp "$DIR/.dump.XXXXXX")"
trap 'rm -f "$TMP" "$OUT.partial"' EXIT

docker compose --env-file "$DB_ENV" exec -T postgres pg_dump -U dsh_owner -d domshchenkov -Fc > "$TMP"
[ -s "$TMP" ] || { echo "backup: empty dump" >&2; exit 1; }
docker compose --env-file "$DB_ENV" exec -T postgres pg_restore -l < "$TMP" > /dev/null \
  || { echo "backup: the dump is not readable by pg_restore" >&2; exit 1; }
age -r "$AGE_RECIPIENT" < "$TMP" > "$OUT.partial"
mv "$OUT.partial" "$OUT"

# rotate only now that a verified new copy exists (-mtime +N = older than N+1 full days)
find "$DIR" -name 'domshchenkov_*.dump.age' -mtime +"$((KEEP_DAYS - 1))" -delete
if [ -n "${RCLONE_REMOTE:-}" ]; then
  rclone copy "$OUT" "$RCLONE_REMOTE"
  rclone delete --min-age "${KEEP_DAYS}d" "$RCLONE_REMOTE"
fi
echo "backup → $OUT"
# Restore test (monthly): age -d -i key.txt FILE | pg_restore -d <empty db>
