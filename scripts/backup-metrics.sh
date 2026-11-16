#!/usr/bin/env bash
set -euo pipefail

# Yedek durumunu Prometheus metriklerine çevirir (node_exporter textfile biçimi).
# backup-pull.sh ve backup-verify.sh her çalışmadan sonra bunu çağırır.
STORE="${BACKUP_PULL_DIR:-$HOME/backup-store}"
STATE="$STORE/state"
OUT_DIR="$STORE/metrics"
hosts=(staging production)

mkdir -p "$STATE" "$OUT_DIR"
chmod 755 "$OUT_DIR"
tmp=$(mktemp "$OUT_DIR/.backup.prom.XXXXXX")
trap 'rm -f "$tmp"' EXIT

# State dosyası "<unix zamanı> <0|1>" biçimindedir; dosya yoksa 0 döner
field() { if [ -f "$1" ]; then cut -d' ' -f"$2" "$1"; else echo 0; fi; }

declare -A latest size files pull_run pull_ok pull_res ver_run ver_ok ver_res
for h in "${hosts[@]}"; do
  f=$(ls -t "$STORE/$h"/appdb-*.sql.gz 2>/dev/null | head -n1 || true)
  if [ -n "$f" ]; then
    latest[$h]=$(stat -c %Y "$f")
    size[$h]=$(stat -c %s "$f")
  else
    latest[$h]=0
    size[$h]=0
  fi
  files[$h]=$(find "$STORE/$h" -maxdepth 1 -name 'appdb-*.sql.gz' 2>/dev/null | wc -l || true)
  pull_run[$h]=$(field "$STATE/pull-$h.last" 1)
  pull_res[$h]=$(field "$STATE/pull-$h.last" 2)
  pull_ok[$h]=$(field "$STATE/pull-$h.ok" 1)
  ver_run[$h]=$(field "$STATE/verify-$h.last" 1)
  ver_res[$h]=$(field "$STATE/verify-$h.last" 2)
  ver_ok[$h]=$(field "$STATE/verify-$h.ok" 1)
done

# Aynı metriğin tüm örnekleri tek grup halinde yazılmalı
emit() {
  local name="$1" help="$2" h
  local -n ref="$3"
  echo "# HELP $name $help"
  echo "# TYPE $name gauge"
  for h in "${hosts[@]}"; do
    echo "$name{env=\"$h\"} ${ref[$h]}"
  done
}

{
  emit backup_latest_timestamp_seconds "En yeni yedek dosyasinin zamani (unix)" latest
  emit backup_latest_size_bytes "En yeni yedegin boyutu" size
  emit backup_files "Saklanan yedek sayisi" files
  emit backup_pull_last_run_timestamp_seconds "Yedek cekme isinin son calisma zamani" pull_run
  emit backup_pull_last_success_timestamp_seconds "Yedek cekmenin son basarili zamani" pull_ok
  emit backup_pull_success "Son yedek cekme basarili mi (1/0)" pull_res
  emit backup_verify_last_run_timestamp_seconds "Geri yukleme sinamasinin son calisma zamani" ver_run
  emit backup_verify_last_success_timestamp_seconds "Geri yukleme sinamasinin son basarili zamani" ver_ok
  emit backup_verify_success "Son geri yukleme sinamasi basarili mi (1/0)" ver_res
} > "$tmp"

chmod 644 "$tmp"
mv "$tmp" "$OUT_DIR/backup.prom"
