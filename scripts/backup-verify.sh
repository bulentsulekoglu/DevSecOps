#!/usr/bin/env bash
set -euo pipefail

# Runner VM'inde çalışır: her ortamın ve her uygulamanın (myapp, depo) en yeni yedeğini geçici bir PostgreSQL konteynerinde geri yükleyip doğrular.
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
  local host="$1" app="$2" prefix="$3" dir="$STORE/$1" label="$1/$2" file age_h count ready=0

  file=$(ls -t "$dir"/"$prefix"-*.sql.gz 2>/dev/null | head -n1 || true)
  [ -n "$file" ] || { fail "$label: hiç yedek yok"; return 1; }

  age_h=$(( ( $(date +%s) - $(stat -c %Y "$file") ) / 3600 ))
  [ "$age_h" -le "$MAX_AGE_HOURS" ] \
    || { fail "$label: en yeni yedek ${age_h} saat önce alınmış (sınır ${MAX_AGE_HOURS})"; return 1; }

  (cd "$dir" && sha256sum -c --quiet "$(basename "$file").sha256") >/dev/null 2>&1 \
    || { fail "$label: sha256 doğrulaması başarısız ($(basename "$file"))"; return 1; }
  gzip -t "$file" || { fail "$label: gzip dosyası bozuk"; return 1; }

  CURRENT="pgverify-$host-$app-$$"
  docker run -d --rm --name "$CURRENT" --network none --tmpfs /var/lib/postgresql/data \
    -e POSTGRES_PASSWORD=verify -e POSTGRES_DB=appdb "$IMAGE" >/dev/null \
    || { fail "$label: geçici veritabanı başlatılamadı"; return 1; }

  for _ in $(seq 1 90); do
    if docker logs "$CURRENT" 2>&1 | grep 'ready for start up' >/dev/null \
       && docker exec "$CURRENT" pg_isready -U postgres -d appdb -q; then
      ready=1
      break
    fi
    sleep 1
  done
  [ "$ready" = 1 ] || { fail "$label: geçici veritabanı hazır olmadı"; return 1; }

  zcat "$file" | docker exec -i "$CURRENT" psql -v ON_ERROR_STOP=1 -q -U postgres -d appdb >/dev/null \
    || { fail "$label: geri yükleme hata verdi ($(basename "$file"))"; return 1; }
  tables=$(docker exec "$CURRENT" psql -U postgres -d appdb -tAc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'") \
    || { fail "$label: tablolar sorgulanamadı"; return 1; }
  [ "$tables" -ge 1 ] || { fail "$label: geri yüklenen veritabanında hiç tablo yok"; return 1; }
  count="tablo sayısı: $tables"

  cleanup
  log "[OK] $label: $(basename "$file") geri yüklendi ($count, yaş: ${age_h} saat)"
}

rc=0
STATE="$STORE/state"
mkdir -p "$STATE"
# Eski durum dosyası adları korunur: myapp için verify-<host>.*, Depo için verify-<host>-depo.*
for host in staging production; do
  for entry in "myapp:appdb:" "depo:depodb:-depo"; do
    IFS=: read -r app prefix suffix <<< "$entry"
    now=$(date +%s)
    if verify_host "$host" "$app" "$prefix"; then
      echo "$now 1" > "$STATE/verify-$host$suffix.last"
      echo "$now" > "$STATE/verify-$host$suffix.ok"
    else
      echo "$now 0" > "$STATE/verify-$host$suffix.last"
      rc=1
    fi
  done
done
bash "$(dirname "$0")/backup-metrics.sh" || log "[UYARI] metrikler yazılamadı"
exit "$rc"
