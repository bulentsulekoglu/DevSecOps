#!/usr/bin/env bash
set -euo pipefail

# Kullanım: scripts/smoke-test.sh <host-veya-ip>
# Ortam değişkenleri:
#   SMOKE_LEVEL=basic  yalnızca /health ve yönlendirme (rollback sonrası için)
#   SMOKE_WRITE=0      veritabanına test verisi yazma (production için)
#   SMOKE_SSH_HOST     giriş bilgilerinin okunacağı hedef (ör. staging), tam test için gerekli
#   EXPECTED_VERSION, EXPECTED_IMAGE   /version çıktısı bunlarla eşleşmeli
HOST="${1:?host gerekli}"
BASE="https://$HOST"
LEVEL="${SMOKE_LEVEL:-full}"
token=""
device_id=""

fail() { echo "SMOKE TEST BAŞARISIZ: $1" >&2; exit 1; }
api() {
  curl -ksS -f --max-time 10 -H @<(printf 'Authorization: Bearer %s\n' "$token") "$@"
}
status_of() {
  curl -ks -o /dev/null -w '%{http_code}' --max-time 10 \
    -H @<(printf 'Authorization: Bearer %s\n' "$token") "$@"
}
cleanup() {
  if [ -n "$device_id" ]; then
    status_of -X DELETE "$BASE/devices/$device_id" >/dev/null || true
  fi
}
trap cleanup EXIT

echo "1) /health"
body=$(curl -ksS --max-time 10 --retry 5 --retry-delay 3 --retry-connrefused "$BASE/health") \
  || fail "/health erişilemedi"
[ "$body" = '{"status":"ok"}' ] || fail "/health beklenmeyen cevap: $body"

echo "2) HTTP -> HTTPS yönlendirmesi"
code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "http://$HOST/")
[ "$code" = "301" ] || fail "yönlendirme 301 olmalı, gelen: $code"

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

echo "4) Kimlik doğrulama zorunlu (token'sız /devices -> 401)"
code=$(curl -ks -o /dev/null -w '%{http_code}' --max-time 10 "$BASE/devices")
[ "$code" = "401" ] || fail "token'sız /devices 401 olmalı, gelen: $code"

echo "5) Giriş"
SSH_HOST="${SMOKE_SSH_HOST:?SMOKE_SSH_HOST gerekli (giriş bilgileri hedefin .env dosyasından okunur)}"
creds=$(ssh -o BatchMode=yes "$SSH_HOST" 'grep -E "^ADMIN_(USERNAME|PASSWORD)=" myapp/.env') \
  || fail "giriş bilgileri okunamadı ($SSH_HOST)"
user=$(printf '%s\n' "$creds" | sed -n 's/^ADMIN_USERNAME=//p')
pass=$(printf '%s\n' "$creds" | sed -n 's/^ADMIN_PASSWORD=//p')
user="${user:-admin}"
[ -n "$pass" ] || fail "ADMIN_PASSWORD boş"
token=$(printf '%s\n%s' "$user" "$pass" \
  | python3 -c 'import json,sys; u,p=sys.stdin.read().split("\n",1); print(json.dumps({"username":u,"password":p}))' \
  | curl -ksS -f --max-time 10 -X POST -H 'Content-Type: application/json' -d @- "$BASE/login" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])') \
  || fail "giriş yapılamadı"
unset pass creds

if [ "${SMOKE_WRITE:-1}" = "1" ]; then
  echo "6) Cihaz API'si: ekle, oku, sil"
  tag="SMOKE-$(date +%s)-$RANDOM"
  payload=$(printf '{"name":"smoke-test","asset_tag":"%s","device_type":"test"}' "$tag")
  created=$(api -X POST -H 'Content-Type: application/json' -d "$payload" "$BASE/devices") \
    || fail "cihaz eklenemedi"
  device_id=$(printf '%s' "$created" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])') \
    || fail "eklenen cihazın kimliği okunamadı"
  api "$BASE/devices/$device_id" | grep -F "\"asset_tag\":\"$tag\"" >/dev/null \
    || fail "eklenen cihaz okunamadı"
  api -X DELETE "$BASE/devices/$device_id" >/dev/null || fail "cihaz silinemedi"
  deleted_id="$device_id"
  device_id=""
  [ "$(status_of "$BASE/devices/$deleted_id")" = "404" ] || fail "silinen cihaz hâlâ okunabiliyor"
else
  echo "6) Cihaz listesi (veri yazılmaz)"
  api "$BASE/devices?limit=1" >/dev/null || fail "cihaz listesi okunamadı"
fi

echo "Smoke test başarılı"
