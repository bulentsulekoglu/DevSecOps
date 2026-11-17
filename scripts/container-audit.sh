#!/usr/bin/env bash
# Çalışan konteynerlerin sertleştirme durumunu listeler (salt okunur, hiçbir şeyi değiştirmez).
# Bir alan okunamazsa "?" yazar, betik durmaz.
insp() { docker inspect --format "$1" "$2" 2>/dev/null || echo "?"; }

printf '%-14s %-10s %-6s %-9s %-9s %-24s %-7s %-7s %-8s %-6s\n' \
  KONTEYNER UID PRIV CAP_DROP READONLY SECURITY_OPT MEM_MB PIDS LOG_MAX SOKET

ids=$(docker ps -q)
if [ -z "$ids" ]; then
  echo "(çalışan konteyner bulunamadı)"
  exit 0
fi

for id in $ids; do
  name=$(insp '{{.Name}}' "$id")
  name=${name#/}
  uids=$(docker top "$id" -eo uid 2>/dev/null | tail -n +2 | sort -u | paste -sd, - || true)
  priv=$(insp '{{.HostConfig.Privileged}}' "$id")
  capdrop=$(insp '{{json .HostConfig.CapDrop}}' "$id")
  ro=$(insp '{{.HostConfig.ReadonlyRootfs}}' "$id")
  secopt=$(insp '{{json .HostConfig.SecurityOpt}}' "$id")
  mem=$(insp '{{.HostConfig.Memory}}' "$id")
  case "$mem" in
    ''|*[!0-9]*) mem_mb='?' ;;
    *) mem_mb=$((mem / 1048576)) ;;
  esac
  pids=$(insp '{{.HostConfig.PidsLimit}}' "$id")
  logmax=$(docker inspect --format '{{index .HostConfig.LogConfig.Config "max-size"}}' "$id" 2>/dev/null || true)
  sock=hayir
  if docker inspect --format '{{range .Mounts}}{{.Source}} {{end}}' "$id" 2>/dev/null | grep docker.sock >/dev/null; then
    sock=EVET
  fi
  printf '%-14s %-10s %-6s %-9s %-9s %-24s %-7s %-7s %-8s %-6s\n' \
    "$name" "${uids:-?}" "$priv" "$capdrop" "$ro" "$secopt" "$mem_mb" "$pids" "${logmax:-yok}" "$sock"
done
