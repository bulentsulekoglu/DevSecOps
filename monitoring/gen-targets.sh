#!/usr/bin/env bash
set -euo pipefail

# Hedef IP'lerini ~/.ssh/config'ten okuyup Prometheus hedef dosyalarını üretir.
# IP'ler repoya girmesin diye çıktı (targets/) .gitignore'dadır.
# Her hedef app etiketi taşır: myapp (IT Asset Portal, :443) ve depo (Depo Stok, :9443).
cd "$(dirname "$0")"
mkdir -p targets

: > targets/node.yml
: > targets/http.yml
: > targets/app.yml
: > targets/depo.yml
for env in staging production; do
  ip=$(ssh -G "$env" | awk '/^hostname /{print $2}')
  printf -- "- targets: ['%s:9100']\n  labels:\n    env: %s\n" "$ip" "$env" >> targets/node.yml
  printf -- "- targets: ['https://%s/health']\n  labels:\n    env: %s\n    app: myapp\n" "$ip" "$env" >> targets/http.yml
  printf -- "- targets: ['https://%s:9443/health']\n  labels:\n    env: %s\n    app: depo\n" "$ip" "$env" >> targets/http.yml
  printf -- "- targets: ['%s:443']\n  labels:\n    env: %s\n    app: myapp\n" "$ip" "$env" >> targets/app.yml
  printf -- "- targets: ['%s:9443']\n  labels:\n    env: %s\n    app: depo\n" "$ip" "$env" >> targets/depo.yml
done
echo "Hedefler üretildi: targets/node.yml, targets/http.yml, targets/app.yml, targets/depo.yml"
