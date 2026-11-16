#!/usr/bin/env bash
set -euo pipefail

# Kullanım: GHCR_USER=... GHCR_TOKEN=... scripts/deploy.sh <hedef> <imaj>
# Örnek:    scripts/deploy.sh staging ghcr.io/kullanici/repo:abc1234
HOST="${1:?hedef gerekli (ör. staging)}"
IMAGE="${2:?imaj gerekli (ör. ghcr.io/kullanici/repo:abc1234)}"
: "${GHCR_USER:?GHCR_USER gerekli}" "${GHCR_TOKEN:?GHCR_TOKEN gerekli}"

SSH_OPTS=(-o BatchMode=yes -o StrictHostKeyChecking=yes)

echo ">> Yapılandırma dosyaları $HOST hedefine kopyalanıyor"
scp "${SSH_OPTS[@]}" -q docker-compose.deploy.yml "$HOST:myapp/docker-compose.yml"
scp "${SSH_OPTS[@]}" -q nginx/default.conf "$HOST:myapp/nginx/default.conf"

echo ">> İmaj $HOST üzerinde çekiliyor: $IMAGE"
printf '%s' "$GHCR_TOKEN" | ssh "${SSH_OPTS[@]}" "$HOST" \
  "docker login ghcr.io -u '$GHCR_USER' --password-stdin >/dev/null && docker pull '$IMAGE' >/dev/null; rc=\$?; docker logout ghcr.io >/dev/null; exit \$rc"

echo ">> Servisler başlatılıyor (sağlıklı olana kadar beklenir)"
ssh "${SSH_OPTS[@]}" "$HOST" \
  "cd myapp && APP_IMAGE='$IMAGE' docker compose up -d --wait --wait-timeout 120 --remove-orphans"

echo ">> Dağıtım tamam: $IMAGE"
