#!/usr/bin/env bash
set -euo pipefail

# Runner VM'inde çalışır: her ortamın en yeni yedeğini geçici bir PostgreSQL konteynerinde geri yükleyip doğrular.
# Ayarlar: BACKUP_PULL_DIR, PG_IMAGE, MAX_AGE_HOURS
STORE="${BACKUP_PULL_DIR:-$HOME/backup-store}"
IMAGE="${PG_IMAGE:-postgres:16-alpine}"
MAX_AGE_HOURS="${MAX_AGE_HOURS:-30}"
log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*"; }

CURRENT=""
cleanup() {
  if [ -n "$CURRENT" ]; then
    docker rm -f "$CURRENT" >/dev/null 2>&1 || true
    CURRENT=""
  fi
}
trap cleanup EXIT
fail() { log "[HATA] $1"; cleanup; return 1; }

# Not: if/|| bağlamında "set -e" çalışmaz, bu yüzden her adımı açıkça kontrol ediyoruz.
verify_host() {
  local host="$1" dir="$STORE/$1" file age_h count ready=0

  file=$(ls -t "$dir"/appdb-*.sql.gz 2>/dev/null | head -n1 || true)
  [ -n "$file" ] || { fail "$host: hiç yedek yok"; return 1; }

  age_h=$(( ( $(date +%s) - $(stat -c %Y "$file") ) / 3600 ))
  [ "$age_h" -le "$MAX_AGE_HOURS" ] \
    || { fail "$host: en yeni yedek ${age_h} saat önce alınmış (sınır ${MAX_AGE_HOURS})"; return 1; }

  (cd "$dir" && sha256sum -c --quiet "$(basename "$file").sha256") >/dev/null 2>&1 \
    || { fail "$host: sha256 doğrulaması başarısız ($(basename "$file"))"; return 1; }
  gzip -t "$file" || { fail "$host: gzip dosyası bozuk"; return 1; }

  CURRENT="pgverify-$host-$$"
  docker run -d --rm --name "$CURRENT" --network none --tmpfs /var/lib/postgresql/data \
    -e POSTGRES_PASSWORD=verify -e POSTGRES_DB=appdb "$IMAGE" >/dev/null \
    || { fail "$host: geçici veritabanı başlatılamadı"; return 1; }

  for _ in $(seq 1 90); do
    if docker logs "$CURRENT" 2>&1 | grep 'ready for start up' >/dev/null \
       && docker exec "$CURRENT" pg_isready -U postgres -d appdb -q; then
      ready=1
      break
    fi
    sleep 1
  done
  [ "$ready" = 1 ] || { fail "$host: geçici veritabanı hazır olmadı"; return 1; }

  zcat "$file" | docker exec -i "$CURRENT" psql -v ON_ERROR_STOP=1 -q -U postgres -d appdb >/dev/null \
    || { fail "$host: geri yükleme hata verdi ($(basename "$file"))"; return 1; }
  count=$(docker exec "$CURRENT" psql -U postgres -d appdb -tAc "SELECT count(*) FROM notes") \
    || { fail "$host: notes tablosu sorgulanamadı"; return 1; }

  cleanup
  log "[OK] $host: $(basename "$file") geri yüklendi (notes satır sayısı: $count, yaş: ${age_h} saat)"
}

rc=0
for host in staging production; do
  verify_host "$host" || rc=1
done
exit "$rc"
