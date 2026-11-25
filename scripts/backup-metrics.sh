#!/usr/bin/env bash
set -euo pipefail

# Yedek durumunu Prometheus metriklerine çevirir (node_exporter textfile biçimi).
# backup-pull.sh ve backup-verify.sh her çalışmadan sonra bunu çağırır.
# Yedek ve sınama metrikleri env + app (myapp, depo) etiketi taşır; çekme metrikleri yalnızca env.
STORE="${BACKUP_PULL_DIR:-$HOME/backup-store}"
STATE="$STORE/state"
OUT_DIR="$STORE/metrics"
hosts=(staging production)
apps=(myapp depo)
declare -A PREFIX=([myapp]=appdb [depo]=depodb)
# Eski durum dosyası adları korunur: myapp için verify-<host>.*, Depo için verify-<host>-depo.*
declare -A SUFFIX=([myapp]="" [depo]="-depo")

mkdir -p "$STATE" "$OUT_DIR"
chmod 755 "$OUT_DIR"
tmp=$(mktemp "$OUT_DIR/.backup.prom.XXXXXX")
trap 'rm -f "$tmp"' EXIT

# State dosyası "<unix zamanı> <0|1>" biçimindedir; dosya yoksa 0 döner
field() { if [ -f "$1" ]; then cut -d' ' -f"$2" "$1"; else echo 0; fi; }

declare -A pull_run pull_ok pull_res
declare -A latest size files ver_run ver_ok ver_res
for h in "${hosts[@]}"; do
  pull_run[$h]=$(field "$STATE/pull-$h.last" 1)
  pull_res[$h]=$(field "$STATE/pull-$h.last" 2)
  pull_ok[$h]=$(field "$STATE/pull-$h.ok" 1)
  for a in "${apps[@]}"; do
    k="$h:$a"
    p="${PREFIX[$a]}"
    s="${SUFFIX[$a]}"
    f=$(ls -t "$STORE/$h"/"$p"-*.sql.gz 2>/dev/null | head -n1 || true)
    if [ -n "$f" ]; then
      latest[$k]=$(stat -c %Y "$f")
      size[$k]=$(stat -c %s "$f")
    else
      latest[$k]=0
      size[$k]=0
    fi
    files[$k]=$(find "$STORE/$h" -maxdepth 1 -name "$p-*.sql.gz" 2>/dev/null | wc -l || true)
    ver_run[$k]=$(field "$STATE/verify-$h$s.last" 1)
    ver_res[$k]=$(field "$STATE/verify-$h$s.last" 2)
    ver_ok[$k]=$(field "$STATE/verify-$h$s.ok" 1)
  done
done

# Aynı metriğin tüm örnekleri tek grup halinde yazılmalı
emit_env() {
  local name="$1" help="$2" h
  local -n ref="$3"
  echo "# HELP $name $help"
  echo "# TYPE $name gauge"
  for h in "${hosts[@]}"; do
    echo "$name{env=\"$h\"} ${ref[$h]}"
  done
}

emit_app() {
  local name="$1" help="$2" h a
  local -n ref="$3"
  echo "# HELP $name $help"
  echo "# TYPE $name gauge"
  for h in "${hosts[@]}"; do
    for a in "${apps[@]}"; do
      echo "$name{env=\"$h\",app=\"$a\"} ${ref["$h:$a"]}"
    done
  done
}

{
  emit_app backup_latest_timestamp_seconds "En yeni yedek dosyasinin zamani (unix)" latest
  emit_app backup_latest_size_bytes "En yeni yedegin boyutu" size
  emit_app backup_files "Saklanan yedek sayisi" files
  emit_env backup_pull_last_run_timestamp_seconds "Yedek cekme isinin son calisma zamani" pull_run
  emit_env backup_pull_last_success_timestamp_seconds "Yedek cekmenin son basarili zamani" pull_ok
  emit_env backup_pull_success "Son yedek cekme basarili mi (1/0)" pull_res
  emit_app backup_verify_last_run_timestamp_seconds "Geri yukleme sinamasinin son calisma zamani" ver_run
  emit_app backup_verify_last_success_timestamp_seconds "Geri yukleme sinamasinin son basarili zamani" ver_ok
  emit_app backup_verify_success "Son geri yukleme sinamasi basarili mi (1/0)" ver_res
} > "$tmp"

chmod 644 "$tmp"
mv "$tmp" "$OUT_DIR/backup.prom"
