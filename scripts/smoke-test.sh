#!/usr/bin/env bash
set -euo pipefail

# Kullanım: scripts/smoke-test.sh <host-veya-ip>
HOST="${1:?host gerekli}"
BASE="https://$HOST"
fail() { echo "SMOKE TEST BAŞARISIZ: $1" >&2; exit 1; }

echo "1) /health"
body=$(curl -ksS --max-time 10 --retry 5 --retry-delay 3 --retry-connrefused "$BASE/health") \
  || fail "/health erişilemedi"
[ "$body" = '{"status":"ok"}' ] || fail "/health beklenmeyen cevap: $body"

echo "2) HTTP -> HTTPS yönlendirmesi"
code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "http://$HOST/")
[ "$code" = "301" ] || fail "yönlendirme 301 olmalı, gelen: $code"

echo "3) Yazma ve okuma (nginx -> uygulama -> veritabanı)"
marker="smoke-$(date +%s)-$RANDOM"
curl -ksS -f --max-time 10 -X POST "$BASE/notes?text=$marker" >/dev/null \
  || fail "not yazılamadı"
curl -ksS -f --max-time 10 "$BASE/notes" | grep -q "$marker" \
  || fail "yazılan not geri okunamadı"

echo "Smoke test başarılı"
