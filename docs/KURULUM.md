# DevSecOps Platformunu Kendi Uygulamanla Kullanmak: Kurulum ve Uyarlama Kılavuzu

## Genel bakış

Sistem iki katmandan oluşur: bir kez kurulan **platform** ve proje başına değişen **uygulama**. Başka biri bunu kendi uygulamasıyla kullanacaksa platformu bir kez kurar, uygulamasını birkaç kurala uydurur ve sonrasında yalnızca kod yazıp GitHub'a gönderir.

- **Platform:** üç sunucu (runner, staging, production), GitHub Actions hattı, güvenlik taramaları, dağıtım ve geri alma betikleri, izleme (Prometheus, Grafana, Alertmanager), yedekleme ve sertleştirme betikleri.
- **Uygulama:** `app/` klasörü ve ona bağlı birkaç dosya (Dockerfile, nginx yönlendirmesi, sağlık kontrolü, smoke test).

Akış şöyle işler: kod gönderilir, pull request açılır, test, lint, Gitleaks, Semgrep ve Trivy çalışır, imaj üretilir, staging'e otomatik dağıtılır, production için onay beklenir, sonra izleme başlar. Dağıtım bozulursa uygulama önceki sağlıklı sürüme kendiliğinden döner.

## Aşama 1: Platformu kur (bir kerelik)

Bu aşama sunucuları ve otomasyonu hazırlar ve uygulamadan bağımsızdır. Adımları sırayla uygula:

1. **Üç sunucu:** Ubuntu Server kurulu üç VM hazırla: `runner`, `staging`, `production`. Her birinde Docker Engine ve Docker Compose olsun, VM'ler birbirini görebilsin. Başlangıç için toplam 16-24 GB RAM yeterlidir.
2. **Runner:** GitHub self-hosted runner'ı root olmayan bir kullanıcıyla kur, kullanıcıyı `docker` grubuna ekle, servis olarak çalıştır ve repoya bağla.
3. **SSH takma adları:** Runner'dan staging ve production'a şifresiz bağlanmak için bir anahtar çifti üret, public anahtarı iki VM'e kopyala. Runner'daki `~/.ssh/config` dosyasına `Host staging` ve `Host production` bloklarını yaz (`HostName`, `User`, `IdentityFile`). Pipeline hiçbir yerde IP kullanmaz, yalnızca bu iki adı kullanır.
4. **Staging ve production'a özel dosyalar:** Bunlar repoya girmez ve her makinede ayrı olur.
    - `~/myapp/.env`: `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`. Her ortam kendi rastgele parolasını kullanır.
    - `~/myapp/nginx/certs/server.crt` ve `server.key`: TLS sertifikası (self-signed ya da gerçek).
    - `~/myapp/nginx/metrics-allow.conf`: `allow <runner-ip>; deny all;` satırları.
5. **Sertleştirme:** Her iki VM'de `scripts/harden-host.sh apply <runner-ip>` çalıştır, yeni bir SSH bağlantısını doğrulayıp `confirm` ile onayla, ardından `scripts/harden-docker.sh apply` çalıştır.
6. **İzleme:** İki VM'e `prometheus-node-exporter` kur (apt). Runner'da `monitoring/` klasöründe `bash gen-targets.sh`, Grafana için `.env`, `bash setup-alerting.sh` (e-posta bilgileri) ve `docker compose up -d` komutlarını çalıştır.
7. **Yedekleme:** VM'lerde her gece 02:30'da `scripts/db-backup.sh` için cron ekle. Runner'da `backup-pull.sh`, `backup-verify.sh` ve `backup-metrics.sh` dosyalarını `~/ops` altına kur, 03:00 ve 03:20 için cron ekle.

## Aşama 2: GitHub tarafını ayarla

Repoyu kendi hesabına kopyala (fork ya da yeni repo) ve aşağıdaki ayarları yap. İmaj adı repo adından kendiliğinden türetilir (`ghcr.io/<hesap>/<repo>`), bir şey değiştirmen gerekmez.

| Ayar | Değer |
| --- | --- |
| `main` dalı koruması | Pull request zorunlu. `lint-test`, `secret-scan`, `sast`, `dependency-scan` kontrolleri zorunlu. Force push ve silme yasak. Atlama listesi boş |
| Actions: workflow izinleri | Okuma ve yazma |
| Actions: dışarıdan gelen pull request'ler | Tüm dış katkıcılar için onay zorunlu (runner senin sunucun olduğu için) |
| Environment `staging` | Koruma yok, otomatik dağıtım |
| Environment `production` | Onaylayıcı (required reviewers) tanımlı, yalnızca `main` dalından dağıtım |

`production` ortamını ve onaylayıcıyı, ona bağlanan workflow'u merge etmeden önce oluştur ve ayarı kaydet. Ortam yokken ya da koruma kaydedilmemişken dağıtım onay beklemeden production'a gider.

## Aşama 3: Kendi uygulamanı yerleştir

Platform, uygulamanın birkaç kurala uymasını bekler. Uyarsa geri kalan her şey değişmeden çalışır.

**Uygulamanın uyması gereken kurallar:**

- `app/` klasöründe, 8000 portunda dinleyen bir konteyner olmalı.
- `GET /health` veritabanını da kontrol edip 200 ve tam olarak `{"status":"ok"}` döndürmeli. İzleme ve smoke test bu çıktıyı arar.
- `GET /version` ortam değişkenlerinden `APP_VERSION` ve `APP_IMAGE` değerlerini göstermeli. Dağıtım doğrulaması bunu kullanır.
- `GET /metrics` Prometheus biçiminde `http_requests_total` ve `http_request_duration_seconds` üretmeli. HTTP panelleri ve alarmları bunlara bağlıdır.
- Veritabanı bilgilerini `POSTGRES_*` ortam değişkenlerinden okumalı. Kodda hiç sır olmamalı, Gitleaks bunu yakalar.

**Değiştirilecek dosyalar:**

| Dosya | Ne değişir |
| --- | --- |
| `app/*` | Kendi kodun, `requirements.txt` ve testler |
| `app/Dockerfile` | Bizimki yalnızca `main.py`'yi kopyalar, çok dosyalı uygulamada `COPY` satırını genişlet. Dil farklıysa temel imajı ve kurulum adımlarını değiştir |
| `nginx/default.conf` | Uygulama 8000'de dinlemiyorsa `proxy_pass` portu. `/login` hız sınırı yalnızca giriş yolun varsa anlamlıdır |
| `docker-compose.deploy.yml` | Sağlık kontrolü komutu ve portu, bellek sınırları, uygulamanın ek ortam değişkenleri |
| `scripts/smoke-test.sh` | 4-6. adımlar bizim cihaz API'mize özgüdür (giriş ve cihaz ekleme). Kendi API'ne göre yeniden yaz ya da yalnızca `/health` ve `/version` kontrolüne indir |
| `.github/workflows/ci.yml` | Python dışı bir dil için test ve lint adımları (ör. `eslint`, `jest`) ve uygun Semgrep kural kümesi |
| `scripts/run-tests.sh` | Test ortamı değişkenleri ve veritabanı bilgileri |

## Dokunmadan kullanabileceğin bileşenler

Platformun büyük kısmı uygulamadan bağımsızdır ve olduğu gibi çalışır:

- **Pipeline yapısı ve sırası:** test, lint, Gitleaks, Semgrep, Trivy, imaj üretimi, staging, onay, production.
- **Güvenlik kapıları ve eşikleri:** `SECURITY-POLICY.md` dosyasında tanımlıdır, `ci.yml` içindeki `env:` bölümünden değiştirilir.
- **Dağıtım, onay ve geri alma betikleri:** `deploy.sh`, `promote.sh`, `rollback.sh`.
- **İzleme:** Prometheus, Grafana panoları, Alertmanager ve alarm kuralları. HTTP kuralları `http_requests_total` metriğine bağlıdır.
- **Yedekleme ve geri yükleme:** `db-backup.sh`, `db-restore.sh` ve runner'daki çekme ve sınama betikleri.
- **Sertleştirme:** `harden-host.sh` ve `harden-docker.sh`.

## Bilinen sınırlar

Platform şu varsayımlarla yazıldı, bunlardan ayrılan bir kurulum betikleri uyarlamayı gerektirir:

- **Sabit adlar:** Proje adı `myapp`, uygulama servisi `app`, veritabanı servisi `db`, sunucudaki klasör `~/myapp`. Betikler bu adlara güvenir, değişirse çalışmaz.
- **PostgreSQL:** Uygulama PostgreSQL kullanmıyorsa `db` servisini, yedekleme betiklerini ve yedek alarmlarını çıkarmak gerekir.
- **Tek uygulama konteyneri:** Dağıtım, doğrulama ve geri alma tek bir `app` konteyneri varsayar.
- **Altyapıya bağlılık:** İşler `runs-on: [self-hosted, linux]` ile yalnızca runner VM'inde çalışır. Runner olmadan pipeline'daki kontroller bekler. CI kısmı için GitHub'ın kendi sunucularına (`ubuntu-latest`) geçmek mümkündür, ama dağıtım adımları yine VM'lere SSH gerektirir.
- **Yapılandırma rollback kapsamı dışında:** Otomatik geri alma yalnızca uygulama imajını geri alır. Compose ve nginx yapılandırma hatalarını git üzerinden geri alıp yeniden dağıtmak gerekir.
