#!/usr/bin/env bash
set -euo pipefail

# Kullanım: GHCR_USER=... GHCR_TOKEN=... scripts/deploy.sh <hedef> <imaj@digest> [commit]
HOST="${1:?hedef gerekli (ör. staging)}"
IMAGE="${2:?imaj gerekli (ör. ghcr.io/kullanici/repo@sha256:...)}"
SHA="${3:-bilinmiyor}"
: "${GHCR_USER:?GHCR_USER gerekli}" "${GHCR_TOKEN:?GHCR_TOKEN gerekli}"

[[ "$IMAGE" =~ ^ghcr\.io/[a-z0-9._/-]+@sha256:[0-9a-f]{64}$ ]] \
  || { echo "İmaj digest ile verilmeli: $IMAGE" >&2; exit 1; }
[[ "$SHA" =~ ^[A-Za-z0-9._-]+$ ]] \
  || { echo "Geçersiz commit bilgisi: $SHA" >&2; exit 1; }

SSH_OPTS=(-o BatchMode=yes -o StrictHostKeyChecking=yes)

ssh "${SSH_OPTS[@]}" "$HOST" 'test -f myapp/nginx/metrics-allow.conf' \
  || { echo "$HOST üzerinde myapp/nginx/metrics-allow.conf yok (bir kerelik kurulum eksik)" >&2; exit 1; }

echo ">> Yapılandırma dosyaları $HOST hedefine kopyalanıyor"
scp "${SSH_OPTS[@]}" -q docker-compose.deploy.yml "$HOST:myapp/docker-compose.yml"
scp "${SSH_OPTS[@]}" -q nginx/default.conf "$HOST:myapp/nginx/default.conf"

echo ">> İmaj $HOST üzerinde çekiliyor: $IMAGE"
printf '%s' "$GHCR_TOKEN" | ssh "${SSH_OPTS[@]}" "$HOST" \
  "docker login ghcr.io -u '$GHCR_USER' --password-stdin >/dev/null && docker pull '$IMAGE' >/dev/null; rc=\$?; docker logout ghcr.io >/dev/null; exit \$rc"

echo ">> Servisler başlatılıyor (sağlıklı olana kadar beklenir)"
ssh "${SSH_OPTS[@]}" "$HOST" \
  "cd myapp && APP_IMAGE='$IMAGE' docker compose up -d --wait --wait-timeout 120 --remove-orphans"

echo ">> Çalışan imaj doğrulanıyor"
running=$(ssh "${SSH_OPTS[@]}" "$HOST" \
  "docker inspect --format '{{.Config.Image}}' \$(docker ps -q --filter label=com.docker.compose.project=myapp --filter label=com.docker.compose.service=app)")
if [ "$running" != "$IMAGE" ]; then
  echo "Çalışan imaj beklenenden farklı!" >&2
  echo "  beklenen: $IMAGE" >&2
  echo "  çalışan : $running" >&2
  exit 1
fi

echo ">> Aday sürüm kaydediliyor (smoke test geçince onaylanacak)"
ssh "${SSH_OPTS[@]}" "$HOST" bash -s -- "$IMAGE" "$SHA" <<'REMOTE'
set -euo pipefail
IMAGE="$1"; SHA="$2"
mkdir -p ~/myapp/.release
cd ~/myapp/.release
printf '%s' "$IMAGE" > candidate
printf '%s deployed sha=%s image=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$SHA" "$IMAGE" >> history.log
REMOTE

echo ">> Dağıtım tamam (onay bekliyor): $IMAGE"
