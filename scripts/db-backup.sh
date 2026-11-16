#!/usr/bin/env bash
set -euo pipefail

# PostgreSQL yedeği: konteynerde pg_dump, sıkıştırma, doğrulama, sha256 ve eski yedeklerin temizliği.
# Ayarlar (ortam değişkeni): BACKUP_DIR, RETENTION_DAYS, BACKUP_PREFIX
BACKUP_DIR="${BACKUP_DIR:-$HOME/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
PREFIX="${BACKUP_PREFIX:-appdb}"

DB=$(docker ps -q --filter label=com.docker.compose.project=myapp --filter label=com.docker.compose.service=db)
[ -n "$DB" ] || { echo "db konteyneri çalışmıyor, yedek alınamadı" >&2; exit 1; }

umask 077
mkdir -p "$BACKUP_DIR"
ts=$(date -u +%Y%m%dT%H%M%SZ)
tmp="$BACKUP_DIR/.${PREFIX}-$ts.tmp"
out="$BACKUP_DIR/${PREFIX}-$ts.sql.gz"
trap 'rm -f "$tmp"' EXIT

docker exec "$DB" sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --clean --if-exists' \
  | gzip -9 > "$tmp"

gzip -t "$tmp"
zcat "$tmp" | tail -n 5 | grep 'PostgreSQL database dump complete' >/dev/null \
  || { echo "Yedek tamamlanmamış görünüyor" >&2; exit 1; }

mv "$tmp" "$out"
(cd "$BACKUP_DIR" && sha256sum "$(basename "$out")" > "$(basename "$out").sha256")
echo "Yedek alındı: $out ($(stat -c %s "$out") bayt)"

# Saklama: yeni yedek başarıyla alındıktan sonra eski olanları sil
find "$BACKUP_DIR" -maxdepth 1 -name '*.sql.gz' -mtime +"$RETENTION_DAYS" -print -delete \
  | sed 's/^/Silindi: /'
find "$BACKUP_DIR" -maxdepth 1 -name '*.sql.gz.sha256' -mtime +"$RETENTION_DAYS" -delete
