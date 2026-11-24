#!/usr/bin/env bash
set -euo pipefail

# Hedef VM'de (staging veya production) Depo Stok için bir kerelik kurulum.
# Kullanım: bash setup-depo.sh <kullanıcı-adı>
# Tekrar çalıştırılabilir: .env, sertifika ve metrik dosyasının üzerine yazmaz.
# Aynı betikle başka bir kullanıcı da eklenebilir (parola sorulur, ekrana yazılmaz).
NAME="${1:?kullanıcı adı gerekli (ör. bulent)}"
[[ "$NAME" =~ ^[A-Za-z0-9._-]{1,32}$ ]] || { echo "Geçersiz kullanıcı adı" >&2; exit 1; }

D="$HOME/depo"
[ -d "$HOME/myapp/nginx/certs" ] || { echo "$HOME/myapp/nginx/certs yok: önce myapp kurulu olmalı" >&2; exit 1; }
[ -f "$HOME/myapp/nginx/metrics-allow.conf" ] || { echo "$HOME/myapp/nginx/metrics-allow.conf yok" >&2; exit 1; }

mkdir -p "$D/nginx/certs" "$D/scripts" "$D/.release"

# Sertifika ve metrik izni myapp ile aynı makineye ait, kopyalanır (varsa üzerine yazılmaz)
cp -pn "$HOME"/myapp/nginx/certs/* "$D/nginx/certs/"
cp -pn "$HOME/myapp/nginx/metrics-allow.conf" "$D/nginx/metrics-allow.conf"

# Veritabanı bilgileri: rastgele parola, yalnızca sahibi okuyabilir, ekrana yazılmaz
if [ -f "$D/.env" ]; then
  echo ".env zaten var, dokunulmadı"
else
  (umask 077; printf 'POSTGRES_USER=depo\nPOSTGRES_DB=depo\nPOSTGRES_PASSWORD=%s\n' "$(openssl rand -hex 16)" > "$D/.env")
  echo ".env oluşturuldu"
fi

# Basic Auth kullanıcısı: bcrypt özeti nginx/htpasswd dosyasına eklenir
HT="$D/nginx/htpasswd"
if [ -f "$HT" ] && grep -q "^${NAME}:" "$HT"; then
  echo "Kullanıcı zaten var: $NAME (parolasını değiştirmek için satırı dosyadan silip betiği yeniden çalıştırın)" >&2
  exit 1
fi
read -rsp "$NAME için parola: " P; echo
read -rsp "Parola (tekrar): " P2; echo
[ "$P" = "$P2" ] || { echo "Parolalar uyuşmuyor" >&2; exit 1; }
[ -n "$P" ] || { echo "Parola boş olamaz" >&2; exit 1; }
printf '%s' "$P" | docker run --rm -i httpd:2.4-alpine htpasswd -niBC 12 "$NAME" >> "$HT"
unset P P2
chmod 644 "$HT"   # yalnızca bcrypt özeti içerir. nginx konteyneri (root olmayan) okuyabilmeli
echo "Kullanıcı eklendi: $NAME"

if ss -ltn 'sport = :9443' | grep -q LISTEN; then
  echo "UYARI: 9443 portu bu makinede zaten kullanımda" >&2
fi
echo "Hazır: $D"
