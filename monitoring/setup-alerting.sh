#!/usr/bin/env bash
set -euo pipefail

# Gmail bilgilerini sorar ve yalnızca bu makinede kalan dosyalara yazar:
#   secrets/smtp_password, alertmanager/generated/alertmanager.yml, .env (kullanıcı kimliği)
cd "$(dirname "$0")"

read -r -p "Gönderici Gmail adresi: " SMTP_USER
read -r -s -p "Gmail uygulama şifresi (yazarken görünmez): " SMTP_PASS
echo
read -r -p "Uyarıların gideceği adres [$SMTP_USER]: " ALERT_TO
ALERT_TO="${ALERT_TO:-$SMTP_USER}"
SMTP_PASS="${SMTP_PASS// /}"

EMAIL_RE='^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+$'
[[ "$SMTP_USER" =~ $EMAIL_RE ]] || { echo "Gönderici adresi geçersiz" >&2; exit 1; }
[[ "$ALERT_TO" =~ $EMAIL_RE ]] || { echo "Alıcı adresi geçersiz" >&2; exit 1; }
[ -n "$SMTP_PASS" ] || { echo "Şifre boş olamaz" >&2; exit 1; }

umask 077
mkdir -p secrets alertmanager/generated alertmanager/data
printf '%s' "$SMTP_PASS" > secrets/smtp_password
sed -e "s|__SMTP_FROM__|$SMTP_USER|g" \
    -e "s|__SMTP_USER__|$SMTP_USER|g" \
    -e "s|__ALERT_TO__|$ALERT_TO|g" \
    alertmanager/alertmanager.yml.tpl > alertmanager/generated/alertmanager.yml

if ! grep -q '^ALERTMANAGER_USER=' .env; then
  printf 'ALERTMANAGER_USER=%s:%s\n' "$(id -u)" "$(id -g)" >> .env
fi
echo "Hazır: şifre ve Alertmanager yapılandırması bu makinede oluşturuldu (repoya girmez)."
