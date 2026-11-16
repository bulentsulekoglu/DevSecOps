#!/usr/bin/env bash
set -euo pipefail

# PostgreSQL geri yükleme. Kullanım: scripts/db-restore.sh <yedek.sql.gz> [--yes]
FILE="${1:?yedek dosyası gerekli (ör. ~/backups/appdb-....sql.gz)}"
ASSUME_YES="${2:-}"
BACKUP_DIR="${BACKUP_DIR:-$HOME/backups}"

container() {
  docker ps -q --filter label=com.docker.compose.project=myapp \
    --filter label=com.docker.compose.service="$1"
}
DB=$(container db)
APP=$(container app)
[ -n "$DB" ] || { echo "db konteyneri çalışmıyor" >&2; exit 1; }
[ -f "$FILE" ] || { echo "Dosya bulunamadı: $FILE" >&2; exit 1; }

echo ">> Yedek doğrulanıyor"
if [ -f "$FILE.sha256" ]; then
  (cd "$(dirname "$FILE")" && sha256sum -c "$(basename "$FILE").sha256")
fi
gzip -t "$FILE"
zcat "$FILE" | tail -n 5 | grep 'PostgreSQL database dump complete' >/dev/null \
  || { echo "Yedek tamamlanmamış görünüyor, geri yükleme iptal" >&2; exit 1; }

if [ "$ASSUME_YES" != "--yes" ]; then
  echo "UYARI: $FILE içeriği mevcut veritabanının ÜZERİNE yazılacak."
  read -r -p "Devam etmek için 'evet' yaz: " answer
  [ "$answer" = "evet" ] || { echo "İptal edildi"; exit 1; }
fi

echo ">> Geri yüklemeden önce güvenlik yedeği alınıyor"
BACKUP_DIR="$BACKUP_DIR" BACKUP_PREFIX=pre-restore bash "$(dirname "$0")/db-backup.sh"

if [ -n "$APP" ]; then
  echo ">> Uygulama durduruluyor"
  docker stop "$APP" >/dev/null
  # Geri yükleme hata verse bile uygulama kapalı kalmasın
  trap 'docker start "$APP" >/dev/null 2>&1 || true' EXIT
fi

echo ">> Geri yükleniyor"
zcat "$FILE" \
  | docker exec -i "$DB" sh -c 'psql -v ON_ERROR_STOP=1 -q -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null

if [ -n "$APP" ]; then
  echo ">> Uygulama başlatılıyor"
  docker start "$APP" >/dev/null
  status=""
  for _ in $(seq 1 30); do
    status=$(docker inspect --format '{{.State.Health.Status}}' "$APP")
    [ "$status" = "healthy" ] && break
    sleep 2
  done
  [ "$status" = "healthy" ] || { echo "Uygulama sağlıklı duruma gelmedi ($status)" >&2; exit 1; }
fi
echo ">> Geri yükleme tamamlandı: $FILE"
