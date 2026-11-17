#!/usr/bin/env bash
set -euo pipefail

# Docker daemon ve Docker dosyaları için denetim kurallarını sertleştirir (CIS Docker Benchmark).
# Kullanım (root olarak): harden-docker.sh apply | rollback
# NOT: Docker servisini yeniden başlatır, konteynerler birkaç saniye kesintiye uğrar.

[ "$(id -u)" -eq 0 ] || { echo "root olarak çalıştırılmalı (sudo)" >&2; exit 1; }
CONF=/etc/docker/daemon.json
BACKUP=/etc/docker/daemon.json.pre-hardening
ABSENT_MARK=/etc/docker/daemon.json.was-absent

wait_for_docker() {
  for _ in $(seq 1 30); do
    if docker info >/dev/null 2>&1; then return 0; fi
    sleep 2
  done
  return 1
}

revert_file() {
  if [ -f "$BACKUP" ]; then
    cp -p "$BACKUP" "$CONF"
  elif [ -f "$ABSENT_MARK" ]; then
    rm -f "$CONF"
  fi
}

restore() {
  revert_file
  systemctl restart docker
  wait_for_docker || echo "UYARI: geri alma sonrası docker başlamadı" >&2
}

case "${1:-}" in
  apply) ;;
  rollback)
    restore
    echo "daemon.json geri alındı."
    exit 0
    ;;
  *)
    echo "kullanım: apply | rollback" >&2
    exit 1
    ;;
esac

mkdir -p /etc/docker
# Özgün durumu yalnızca bir kez kaydet (betik tekrar çalışırsa yedeğin üstüne yazılmasın)
if [ ! -f "$BACKUP" ] && [ ! -f "$ABSENT_MARK" ]; then
  if [ -f "$CONF" ]; then cp -p "$CONF" "$BACKUP"; else : > "$ABSENT_MARK"; fi
fi

echo ">> daemon.json birleştiriliyor"
python3 - "$CONF" <<'PY'
import json, os, sys

path = sys.argv[1]
cfg = {}
if os.path.exists(path):
    with open(path) as f:
        text = f.read().strip()
        cfg = json.loads(text) if text else {}
cfg.update({
    "icc": False,
    "live-restore": True,
    "userland-proxy": False,
    "no-new-privileges": True,
    "log-level": "info",
    "log-driver": "json-file",
    "log-opts": {"max-size": "10m", "max-file": "3"},
})
with open(path, "w") as f:
    json.dump(cfg, f, indent=2)
    f.write("\n")
PY

if ! dockerd --validate --config-file "$CONF" >/dev/null 2>&1; then
  echo "DURDU: daemon.json doğrulamadan geçemedi, değişiklik geri alınıyor." >&2
  revert_file
  exit 1
fi

echo ">> auditd kuralları (Docker dosyaları)"
{
  for p in /usr/bin/dockerd /run/containerd /var/lib/docker /etc/default/docker \
           /etc/docker/daemon.json /etc/containerd/config.toml /usr/bin/containerd \
           /usr/bin/containerd-shim-runc-v2 /usr/bin/runc \
           "$(systemctl show -p FragmentPath docker.service | cut -d= -f2)" \
           "$(systemctl show -p FragmentPath docker.socket | cut -d= -f2)"; do
    if [ -n "$p" ] && [ -e "$p" ]; then echo "-w $p -p wa -k docker"; fi
  done
} > /etc/audit/rules.d/docker.rules
augenrules --load >/dev/null 2>&1 || echo "UYARI: auditd kuralları yüklenemedi"

echo ">> Docker yeniden başlatılıyor (konteynerler birkaç saniye kesintiye uğrar)"
systemctl restart docker
if ! wait_for_docker; then
  echo "DURDU: Docker başlamadı, eski yapılandırma geri yükleniyor." >&2
  restore
  exit 1
fi

echo ">> Konteynerlerin geri gelmesi bekleniyor"
for _ in $(seq 1 45); do
  running=$(docker ps -q | wc -l)
  waiting=$(docker ps --filter health=starting --filter health=unhealthy -q | wc -l)
  if [ "$running" -ge 3 ] && [ "$waiting" -eq 0 ]; then break; fi
  sleep 2
done

echo
echo ">> Özet"
docker ps --format 'table {{.Names}}\t{{.Status}}'
echo "live-restore: $(docker info --format '{{.LiveRestoreEnabled}}')"
cat "$CONF"
