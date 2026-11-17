# DevSecOps CI/CD Projesi

FastAPI + PostgreSQL uygulaması. Docker Compose ile konteyner ortamında, nginx (TLS) arkasında çalışır. Tüm servisler root olmayan kullanıcıyla çalışır.

**Kurulum ve uyarlama kılavuzu:** [docs/KURULUM.md](docs/KURULUM.md)

## Mimari

- nginx (TLS, 80/443) -> FastAPI uygulaması -> PostgreSQL
- `frontend` ağı: nginx ve uygulama
- `backend` ağı: uygulama ve veritabanı (internete kapalı)

## Yerelde çalıştırma

1. Proje kökünde `.env` dosyası oluştur (repoda yok, `.gitignore`'da):

        POSTGRES_USER=appuser
        POSTGRES_PASSWORD=guclu_bir_parola
        POSTGRES_DB=appdb
        ADMIN_USERNAME=admin
        ADMIN_PASSWORD=guclu_bir_admin_parolasi

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

## Dağıtım akışı

`main`'e merge sonrası: `build-push` imajı üretir ve digest'ini çıkarır, `deploy-staging` aynı digest'i staging'e otomatik dağıtır (health check ve smoke test ile) ve başarısız olursa otomatik geri alır. `deploy-production` aynı digest'i, GitHub `production` ortamındaki manuel onaydan sonra production'a dağıtır. Sürüm kayıtları hedef makinelerde `~/myapp/.release/` altında tutulur.

## Yedekleme ve geri yükleme

- **Yedek:** Staging ve production VM'lerinde her gece 02:30'da `scripts/db-backup.sh` çalışır (`~/backups/`, 14 gün saklanır, `sha256` ile). Her yedek geçerlilik için doğrulanır.
- **Kopya:** Runner VM'i her gece 03:00'te yedekleri çeker (`~/backup-store/`, 30 gün saklanır) ve `sha256`'larını doğrular.
- **Sınama:** Runner VM'i 03:20'de her ortamın en yeni yedeğini geçici bir PostgreSQL konteynerinde geri yükler, yedeğin gerçekten kullanılabilir olduğunu doğrular.
- **Geri yükleme:** VM üzerinde `bash myapp/scripts/db-restore.sh <yedek.sql.gz>`. Önce güvenlik yedeği alır, uygulamayı durdurup geri yükler ve sağlıklı olmasını bekler. Onay için `evet` yazılması gerekir.
- **Sınırlar:** Yedekler şifrelenmemiştir (dosya izinleri `600`). Geri yükleme yalnızca veritabanı verisini geri alır, uygulama imajını ya da yapılandırma dosyalarını değil.

## IT Asset Portal API

| Uç nokta | Giriş | Açıklama |
|---|---|---|
| `GET /health` | hayır | Uygulama ve veritabanı sağlık kontrolü |
| `GET /version` | hayır | Çalışan commit kodu ve imaj digest'i |
| `POST /login` | hayır | `{"username","password"}` -> `access_token` (8 saat geçerli, dakikada 5 deneme) |
| `POST /logout` | evet | Oturumu sonlandırır |
| `GET /devices` | evet | Cihaz listesi (`limit`, `offset`) |
| `POST /devices` | evet | Cihaz ekler (`name`, `asset_tag`, `device_type`, `owner`, `location`, `status`) |
| `GET /devices/{id}` | evet | Tek cihaz |
| `PUT /devices/{id}` | evet | Cihazı günceller |
| `DELETE /devices/{id}` | evet | Cihazı siler |

Giriş gerektiren uç noktalara `Authorization: Bearer <token>` başlığıyla erişilir. Etkileşimli arayüz: `/docs` (Swagger). İlk yönetici kullanıcı, ilk açılışta `.env` içindeki `ADMIN_USERNAME` ve `ADMIN_PASSWORD` ile oluşturulur; sonradan `.env`'i değiştirmek mevcut parolayı değiştirmez.
