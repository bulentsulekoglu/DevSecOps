#!/usr/bin/env bash
set -euo pipefail

# Kullanım: scripts/promote.sh <hedef> <imaj@digest> [commit]
HOST="${1:?hedef gerekli}"
IMAGE="${2:?imaj gerekli}"
SHA="${3:-bilinmiyor}"

# Uygulama seçimi (varsayılan myapp): APP=depo bash scripts/<betik> ...
APP="${APP:-myapp}"
[[ "$APP" =~ ^(myapp|depo)$ ]] || { echo "Bilinmeyen uygulama: $APP" >&2; exit 1; }

[[ "$IMAGE" =~ ^ghcr\.io/[a-z0-9._/-]+@sha256:[0-9a-f]{64}$ ]] \
  || { echo "Geçersiz imaj: $IMAGE" >&2; exit 1; }
[[ "$SHA" =~ ^[A-Za-z0-9._-]+$ ]] \
  || { echo "Geçersiz commit bilgisi: $SHA" >&2; exit 1; }

ssh -o BatchMode=yes -o StrictHostKeyChecking=yes "$HOST" bash -s -- "$IMAGE" "$SHA" "$APP" <<'REMOTE'
set -euo pipefail
IMAGE="$1"; SHA="$2"; APP="$3"
cd ~/$APP/.release
[ "$(cat candidate 2>/dev/null || true)" = "$IMAGE" ] \
  || { echo "Aday sürüm beklenenle uyuşmuyor" >&2; exit 1; }
if [ -f current ] && [ "$(cat current)" != "$IMAGE" ]; then
  cp current previous
fi
printf '%s' "$IMAGE" > current
rm -f candidate
printf '%s promoted sha=%s image=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$SHA" "$IMAGE" >> history.log
REMOTE

echo ">> Sürüm onaylandı: $IMAGE"
