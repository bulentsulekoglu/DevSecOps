#!/usr/bin/env bash
set -euo pipefail

# Runner VM'inde çalışır: staging ve production yedeklerini çeker, sha256 doğrular, eskileri temizler.
# Ayarlar: BACKUP_PULL_DIR, RETENTION_DAYS
DEST="${BACKUP_PULL_DIR:-$HOME/backup-store}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*"; }

umask 077
rc=0
for host in staging production; do
  mkdir -p "$DEST/$host"
  if ! rsync -a --ignore-existing -e "ssh -o BatchMode=yes -o StrictHostKeyChecking=yes" \
       --include='appdb-*.sql.gz' --include='appdb-*.sql.gz.sha256' --exclude='*' \
       "$host:backups/" "$DEST/$host/"; then
    log "[HATA] $host: yedekler çekilemedi"
    rc=1
    continue
  fi

  bad=0
  shopt -s nullglob
  for s in "$DEST/$host"/appdb-*.sql.gz.sha256; do
    (cd "$DEST/$host" && sha256sum -c --quiet "$(basename "$s")" >/dev/null 2>&1) \
      || { log "[HATA] $host: $(basename "$s") doğrulanamadı"; bad=1; }
  done
  shopt -u nullglob
  [ "$bad" = 0 ] || rc=1

  n=$(find "$DEST/$host" -maxdepth 1 -name 'appdb-*.sql.gz' | wc -l)
  log "[OK] $host: yedekler çekildi (toplam $n dosya)"
  find "$DEST/$host" -maxdepth 1 -name 'appdb-*' -mtime +"$RETENTION_DAYS" -delete
done
exit "$rc"
