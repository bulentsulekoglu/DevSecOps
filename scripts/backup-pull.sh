#!/usr/bin/env bash
set -euo pipefail

# Runner VM'inde çalışır: staging ve production yedeklerini (appdb-* ve Depo Stok'un depodb-*) çeker, sha256 doğrular, eskileri temizler.
# Ayarlar: BACKUP_PULL_DIR, RETENTION_DAYS
DEST="${BACKUP_PULL_DIR:-$HOME/backup-store}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*"; }

umask 077
rc=0
STATE="$DEST/state"
mkdir -p "$STATE"
for host in staging production; do
  mkdir -p "$DEST/$host"
  now=$(date +%s)
  if ! rsync -a --ignore-existing -e "ssh -o BatchMode=yes -o StrictHostKeyChecking=yes" \
       --include='appdb-*.sql.gz' --include='appdb-*.sql.gz.sha256' \
       --include='depodb-*.sql.gz' --include='depodb-*.sql.gz.sha256' --exclude='*' \
       "$host:backups/" "$DEST/$host/"; then
    log "[HATA] $host: yedekler çekilemedi"
    echo "$now 0" > "$STATE/pull-$host.last"
    rc=1
    continue
  fi

  bad=0
  shopt -s nullglob
  for s in "$DEST/$host"/appdb-*.sql.gz.sha256 "$DEST/$host"/depodb-*.sql.gz.sha256; do
    (cd "$DEST/$host" && sha256sum -c --quiet "$(basename "$s")" >/dev/null 2>&1) \
      || { log "[HATA] $host: $(basename "$s") doğrulanamadı"; bad=1; }
  done
  shopt -u nullglob
  if [ "$bad" = 0 ]; then
    echo "$now 1" > "$STATE/pull-$host.last"
    echo "$now" > "$STATE/pull-$host.ok"
  else
    echo "$now 0" > "$STATE/pull-$host.last"
    rc=1
  fi

  n=$(find "$DEST/$host" -maxdepth 1 \( -name 'appdb-*.sql.gz' -o -name 'depodb-*.sql.gz' \) | wc -l)
  log "[OK] $host: yedekler çekildi (toplam $n dosya)"
  find "$DEST/$host" -maxdepth 1 \( -name 'appdb-*' -o -name 'depodb-*' \) -mtime +"$RETENTION_DAYS" -delete
done
bash "$(dirname "$0")/backup-metrics.sh" || log "[UYARI] metrikler yazılamadı"
exit "$rc"
