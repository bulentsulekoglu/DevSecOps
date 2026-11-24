#!/usr/bin/env bash
set -euo pipefail

# Kullanım: GHCR_USER=... GHCR_TOKEN=... scripts/deploy.sh <hedef> <imaj@digest> [commit]
HOST="${1:?hedef gerekli (ör. staging)}"
IMAGE="${2:?imaj gerekli (ör. ghcr.io/kullanici/repo@sha256:...)}"
SHA="${3:-bilinmiyor}"

# Uygulama seçimi (varsayılan myapp): APP=depo bash scripts/<betik> ...
APP="${APP:-myapp}"
[[ "$APP" =~ ^(myapp|depo)$ ]] || { echo "Bilinmeyen uygulama: $APP" >&2; exit 1; }
if [ "$APP" = depo ]; then SRC="depo"; REQ_VAR="POSTGRES_PASSWORD"; else SRC="."; REQ_VAR="ADMIN_PASSWORD"; fi
: "${GHCR_USER:?GHCR_USER gerekli}" "${GHCR_TOKEN:?GHCR_TOKEN gerekli}"

[[ "$IMAGE" =~ ^ghcr\.io/[a-z0-9._/-]+@sha256:[0-9a-f]{64}$ ]] \
  || { echo "İmaj digest ile verilmeli: $IMAGE" >&2; exit 1; }
[[ "$SHA" =~ ^[A-Za-z0-9._-]+$ ]] \
  || { echo "Geçersiz commit bilgisi: $SHA" >&2; exit 1; }

SSH_OPTS=(-o BatchMode=yes -o StrictHostKeyChecking=yes)

ssh "${SSH_OPTS[@]}" "$HOST" "test -f $APP/nginx/metrics-allow.conf" \
  || { echo "$HOST üzerinde $APP/nginx/metrics-allow.conf yok (bir kerelik kurulum eksik)" >&2; exit 1; }

ssh "${SSH_OPTS[@]}" "$HOST" "grep -q '^${REQ_VAR}=.' $APP/.env" \
  || { echo "$HOST üzerinde $APP/.env içinde $REQ_VAR yok (bir kerelik kurulum eksik)" >&2; exit 1; }

if [ "$APP" = depo ]; then
  ssh "${SSH_OPTS[@]}" "$HOST" 'test -s depo/nginx/htpasswd' \
    || { echo "$HOST üzerinde depo/nginx/htpasswd yok (scripts/setup-depo.sh çalıştırılmalı)" >&2; exit 1; }
fi

echo ">> Yapılandırma dosyaları $HOST hedefine kopyalanıyor"
scp "${SSH_OPTS[@]}" -q "$SRC/docker-compose.deploy.yml" "$HOST:$APP/docker-compose.yml"
scp "${SSH_OPTS[@]}" -q "$SRC/nginx/default.conf" "$HOST:$APP/nginx/default.conf"
ssh "${SSH_OPTS[@]}" "$HOST" "mkdir -p $APP/scripts"
scp "${SSH_OPTS[@]}" -q scripts/db-backup.sh scripts/db-restore.sh "$HOST:$APP/scripts/"

echo ">> İmaj $HOST üzerinde çekiliyor: $IMAGE"
printf '%s' "$GHCR_TOKEN" | ssh "${SSH_OPTS[@]}" "$HOST" \
  "docker login ghcr.io -u '$GHCR_USER' --password-stdin >/dev/null && docker pull '$IMAGE' >/dev/null; rc=\$?; docker logout ghcr.io >/dev/null; exit \$rc"

echo ">> Servisler başlatılıyor (sağlıklı olana kadar beklenir)"
ssh "${SSH_OPTS[@]}" "$HOST" \
  "cd $APP && APP_IMAGE='$IMAGE' docker compose up -d --wait --wait-timeout 120 --remove-orphans"

echo ">> Çalışan imaj doğrulanıyor"
running=$(ssh "${SSH_OPTS[@]}" "$HOST" \
  "docker inspect --format '{{.Config.Image}}' \$(docker ps -q --filter label=com.docker.compose.project=$APP --filter label=com.docker.compose.service=app)")
if [ "$running" != "$IMAGE" ]; then
  echo "Çalışan imaj beklenenden farklı!" >&2
  echo "  beklenen: $IMAGE" >&2
  echo "  çalışan : $running" >&2
  exit 1
fi

echo ">> Aday sürüm kaydediliyor (smoke test geçince onaylanacak)"
ssh "${SSH_OPTS[@]}" "$HOST" bash -s -- "$IMAGE" "$SHA" "$APP" <<'REMOTE'
set -euo pipefail
IMAGE="$1"; SHA="$2"; APP="$3"
mkdir -p ~/$APP/.release
cd ~/$APP/.release
printf '%s' "$IMAGE" > candidate
printf '%s deployed sha=%s image=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$SHA" "$IMAGE" >> history.log
REMOTE

echo ">> Dağıtım tamam (onay bekliyor): $IMAGE"
