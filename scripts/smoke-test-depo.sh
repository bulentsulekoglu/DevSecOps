#!/usr/bin/env bash
set -euo pipefail

# Depo Stok smoke testi. Kullanım: scripts/smoke-test-depo.sh <host-veya-ip>
# Ortam değişkenleri:
#   SMOKE_LEVEL=basic  yalnızca /health ve parola zorunluluğu (rollback sonrası için)
#   SMOKE_SSH_HOST     tam testte veritabanı kontrolü için hedef (ör. staging)
#   EXPECTED_VERSION, EXPECTED_IMAGE   /version çıktısı bunlarla eşleşmeli
# Test hiçbir parola kullanmaz ve veri yazmaz: sınanan şey tam olarak "parolasız girilemiyor".
HOST="${1:?host gerekli}"
BASE="https://$HOST:9443"
LEVEL="${SMOKE_LEVEL:-full}"

fail() { echo "SMOKE TEST BAŞARISIZ: $1" >&2; exit 1; }
status_of() { curl -ks -o /dev/null -w '%{http_code}' --max-time 10 "$@"; }

echo "1) /health"
body=$(curl -ksS --max-time 10 --retry 5 --retry-delay 3 --retry-connrefused "$BASE/health") \
  || fail "/health erişilemedi"
[ "$body" = '{"status":"ok"}' ] || fail "/health beklenmeyen cevap: $body"

echo "2) Parola zorunlu (parolasız arayüz ve API -> 401)"
for path in / /api/products /api/export.csv; do
  code=$(status_of "$BASE$path")
  [ "$code" = "401" ] || fail "parolasız $path 401 olmalı, gelen: $code"
done
code=$(status_of -H 'X-Remote-User: admin' "$BASE/api/me")
[ "$code" = "401" ] || fail "sahte X-Remote-User başlığı kabul edildi (gelen: $code)"

if [ "$LEVEL" = "basic" ]; then
  echo "Temel smoke test başarılı"
  exit 0
fi

echo "3) /version"
ver=$(curl -ksS --max-time 10 "$BASE/version") || fail "/version erişilemedi"
echo "   $ver"
if [ -n "${EXPECTED_VERSION:-}" ]; then
  echo "$ver" | grep -F "\"version\":\"$EXPECTED_VERSION\"" >/dev/null \
    || fail "/version beklenen sürümü göstermiyor (beklenen: $EXPECTED_VERSION)"
fi
if [ -n "${EXPECTED_IMAGE:-}" ]; then
  echo "$ver" | grep -F "\"image\":\"$EXPECTED_IMAGE\"" >/dev/null \
    || fail "/version beklenen imaj digest'ini göstermiyor (beklenen: $EXPECTED_IMAGE)"
fi

echo "4) Veritabanı ve şema (salt okunur sayım)"
SSH_HOST="${SMOKE_SSH_HOST:?SMOKE_SSH_HOST gerekli (veritabanı hedef makinede sorgulanır)}"
n=$(ssh -o BatchMode=yes "$SSH_HOST" \
  "docker exec \$(docker ps -q --filter label=com.docker.compose.project=depo --filter label=com.docker.compose.service=db) sh -c 'psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -tAc \"SELECT count(*) FROM products\"'") \
  || fail "veritabanı sorgulanamadı ($SSH_HOST)"
[[ "$n" =~ ^[0-9]+$ ]] || fail "veritabanı beklenmeyen cevap verdi: $n"
echo "   ürün sayısı: $n"

echo "Smoke test başarılı"
