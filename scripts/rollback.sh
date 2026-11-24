#!/usr/bin/env bash
set -euo pipefail

# Kullanım: GHCR_USER=... GHCR_TOKEN=... scripts/rollback.sh <hedef> <başarısız-imaj> [commit]
HOST="${1:?hedef gerekli}"
FAILED="${2:?başarısız imaj gerekli}"
SHA="${3:-bilinmiyor}"

# Uygulama seçimi (varsayılan myapp): APP=depo bash scripts/<betik> ...
APP="${APP:-myapp}"
[[ "$APP" =~ ^(myapp|depo)$ ]] || { echo "Bilinmeyen uygulama: $APP" >&2; exit 1; }
: "${GHCR_USER:?GHCR_USER gerekli}" "${GHCR_TOKEN:?GHCR_TOKEN gerekli}"

IMAGE_RE='^ghcr\.io/[a-z0-9._/-]+@sha256:[0-9a-f]{64}$'
[[ "$FAILED" =~ $IMAGE_RE ]] || { echo "Geçersiz imaj: $FAILED" >&2; exit 1; }
[[ "$SHA" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "Geçersiz commit bilgisi: $SHA" >&2; exit 1; }

SSH_OPTS=(-o BatchMode=yes -o StrictHostKeyChecking=yes)
summary() { if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then echo "$1" >> "$GITHUB_STEP_SUMMARY"; fi; }

# 1) Hedef sürümü belirle: son doğrulanmış sürüm, o da başarısız olanla aynıysa bir öncekisi
current=$(ssh "${SSH_OPTS[@]}" "$HOST" "cat $APP/.release/current 2>/dev/null || true")
previous=$(ssh "${SSH_OPTS[@]}" "$HOST" "cat $APP/.release/previous 2>/dev/null || true")
TARGET="$current"
if [ -z "$TARGET" ] || [ "$TARGET" = "$FAILED" ]; then
  TARGET="$previous"
fi
if [ -z "$TARGET" ] || [ "$TARGET" = "$FAILED" ]; then
  echo "GERİ DÖNÜLECEK doğrulanmış sürüm yok. Başarısız sürüm hedefte kalıyor: $FAILED" >&2
  summary "Yayın başarısız ve geri dönülecek doğrulanmış sürüm yok: $FAILED"
  exit 1
fi
[[ "$TARGET" =~ $IMAGE_RE ]] || { echo "Kayıttaki sürüm geçersiz: $TARGET" >&2; exit 1; }

echo ">> Geri alınıyor"
echo "   başarısız: $FAILED"
echo "   hedef    : $TARGET"

# 2) Hedef imajı hazırla
printf '%s' "$GHCR_TOKEN" | ssh "${SSH_OPTS[@]}" "$HOST" \
  "docker login ghcr.io -u '$GHCR_USER' --password-stdin >/dev/null && docker pull '$TARGET' >/dev/null; rc=\$?; docker logout ghcr.io >/dev/null; exit \$rc"

# 3) Servisleri hedef sürümle yeniden başlat
ssh "${SSH_OPTS[@]}" "$HOST" \
  "cd $APP && APP_IMAGE='$TARGET' docker compose up -d --wait --wait-timeout 120 --remove-orphans"

# 4) Çalışan imajı doğrula
running=$(ssh "${SSH_OPTS[@]}" "$HOST" \
  "docker inspect --format '{{.Config.Image}}' \$(docker ps -q --filter label=com.docker.compose.project=$APP --filter label=com.docker.compose.service=app)")
if [ "$running" != "$TARGET" ]; then
  echo "Rollback sonrası çalışan imaj beklenenden farklı: $running" >&2
  summary "ROLLBACK BAŞARISIZ: çalışan imaj beklenenden farklı"
  exit 1
fi

# 5) Smoke test ile doğrula
HOST_IP=$(ssh -G "$HOST" | awk '/^hostname /{print $2}')
if [ "$APP" = depo ]; then SMOKE=scripts/smoke-test-depo.sh; else SMOKE=scripts/smoke-test.sh; fi
SMOKE_LEVEL=basic bash "$SMOKE" "$HOST_IP"

# 6) Kaydı güncelle
ssh "${SSH_OPTS[@]}" "$HOST" bash -s -- "$FAILED" "$TARGET" "$SHA" "$APP" <<'REMOTE'
set -euo pipefail
FAILED="$1"; TARGET="$2"; SHA="$3"; APP="$4"
cd ~/$APP/.release
printf '%s' "$TARGET" > current
rm -f candidate
printf '%s ROLLBACK sha=%s failed=%s restored=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$SHA" "$FAILED" "$TARGET" >> history.log
REMOTE

echo ">> Rollback tamam, sistem son iyi sürümde: $TARGET"
summary "Yayın başarısız oldu: $FAILED. Otomatik olarak geri alındı: $TARGET (smoke test geçti)."
