# DevSecOps CI/CD Projesi

FastAPI + PostgreSQL uygulaması. Docker Compose ile konteyner ortamında, nginx (TLS) arkasında çalışır. Tüm servisler root olmayan kullanıcıyla çalışır.

## Mimari

- nginx (TLS, 80/443) -> FastAPI uygulaması -> PostgreSQL
- `frontend` ağı: nginx ve uygulama
- `backend` ağı: uygulama ve veritabanı (internete kapalı)

## Yerelde çalıştırma

1. Proje kökünde `.env` dosyası oluştur (repoda yok, `.gitignore`'da):

        POSTGRES_USER=appuser
        POSTGRES_PASSWORD=guclu_bir_parola
        POSTGRES_DB=appdb

2. Self-signed TLS sertifikası üret:

        mkdir -p nginx/certs
        openssl req -x509 -nodes -newkey rsa:2048 -days 365 \
          -keyout nginx/certs/server.key -out nginx/certs/server.crt \
          -subj "/CN=localhost"
        chmod 644 nginx/certs/server.key

3. Başlat:

        docker compose up -d --build

## CI/CD

`.github/workflows/ci.yml`, self-hosted runner üzerinde çalışır:

- `lint-test`: ruff ile lint, pytest ile unit testler (her push ve PR'da)
- `build-push`: Docker imajını build edip ghcr.io'ya gönderir (sadece `main`'e push'ta ve `lint-test` başarılıysa)

Testler başarısız olursa build ve push çalışmaz.

## Branch politikası

- `main` korumalıdır: doğrudan push, force push ve branch silme yasaktır.
- Her iş ayrı branch'te yapılır: `feature/...` (yeni özellik), `fix/...` (hata düzeltme), `chore/...` (bakım).
- Değişiklikler pull request ile `main`'e girer.
- Merge için `lint-test` kontrolü yeşil olmalı ve branch `main` ile güncel olmalıdır.
- PR'daki yorumlar çözülmeden merge edilemez.
