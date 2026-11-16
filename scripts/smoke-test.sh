#!/usr/bin/env bash
set -euo pipefail

# Kullanım: [SMOKE_WRITE=0] scripts/smoke-test.sh <host-veya-ip>
# SMOKE_WRITE=0 ise veritabanına test verisi yazılmaz (production için).
HOST="${1:?host gerekli}"
BASE="https://$HOST"
fail() { echo "SMOKE TEST BAŞARISIZ: $1" >&2; exit 1; }

echo "1) /health"
body=$(curl -ksS --max-time 10 --retry 5 --retry-delay 3 --retry-connrefused "$BASE/health") \
  || fail "/health erişilemedi"
[ "$body" = '{"status":"ok"}' ] || fail "/health beklenmeyen cevap: $body"

echo "1b) /version"
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

echo "2) HTTP -> HTTPS yönlendirmesi"
code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "http://$HOST/")
[ "$code" = "301" ] || fail "yönlendirme 301 olmalı, gelen: $code"

if [ "${SMOKE_WRITE:-1}" = "1" ]; then
  echo "3) Yazma ve okuma (nginx -> uygulama -> veritabanı)"
  marker="smoke-$(date +%s)-$RANDOM"
  curl -ksS -f --max-time 10 -X POST "$BASE/notes?text=$marker" >/dev/null \
    || fail "not yazılamadı"
  curl -ksS -f --max-time 10 "$BASE/notes" | grep -q "$marker" \
    || fail "yazılan not geri okunamadı"
else
  echo "3) Okuma (veri yazılmaz): nginx -> uygulama -> veritabanı"
  curl -ksS -f --max-time 10 "$BASE/notes" >/dev/null \
    || fail "notlar okunamadı (veritabanı bağlantısı?)"
fi

echo "Smoke test başarılı"
