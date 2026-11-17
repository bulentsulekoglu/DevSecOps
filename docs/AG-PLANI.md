# Ağ ve Port Planı

Bu belge sunucuların hangi portları dinlediğini ve kimin kime hangi porttan ulaşabildiğini anlatır. Değerler 17 Kasım 2026'da `ss -tln` ve `ufw status` çıktılarıyla ölçülmüştür. Belgede IP adresi yazmaz, sunucular rolleriyle anılır: `runner`, `staging`, `production`. `<runner-ip>` runner'ın laboratuvar ağındaki adresidir.

## Sunucu rolleri

| Sunucu | Görevi |
| --- | --- |
| `runner` | GitHub self-hosted runner, izleme yığını (Prometheus, Grafana, Alertmanager, blackbox), yedek çekme ve sınama |
| `staging` | Uygulamanın test ortamı, her main birleşiminde otomatik dağıtım |
| `production` | Uygulamanın canlı ortamı, dağıtım için onay gerekir |

## Dinlenen portlar

### staging ve production (aynı)

| Port | Erişebilen | Ne için |
| --- | --- | --- |
| 22/tcp | Yalnızca `<runner-ip>` | SSH: dağıtım, yedek çekme, yönetim |
| 9100/tcp | Yalnızca `<runner-ip>` | node_exporter, sunucu metrikleri |
| 80/tcp | Herkes | HTTP (nginx) |
| 443/tcp | Herkes | HTTPS (nginx, TLS) |

Uygulama (8000) ve veritabanı (5432) sunucuya port açmaz. Yalnızca Docker'ın iç ağında erişilebilir. nginx konteyner içinde 8080 ve 8443'te dinler, sunucuda 80 ve 443'e yayınlanır. UFW açıktır, izin verilen kurallar yukarıdaki tabloda listelenmiştir.

### runner

| Port | Dinlediği adres | Ne için |
| --- | --- | --- |
| 22/tcp | Tüm arayüzler | SSH, yönetim |
| 3000/tcp | Tüm arayüzler (şu an) | Grafana. Erişim SSH tüneliyle yapılır. Hedef: yalnızca localhost |
| 9090/tcp | Yalnızca localhost | Prometheus |
| 9093/tcp | Yalnızca localhost | Alertmanager |
| 9100/tcp | Yalnızca Docker ağı | Yedek metrikleri (backup-metrics) |
| 9115/tcp | Yalnızca Docker ağı | blackbox exporter |

## Erişim matrisi

| Kaynak | Hedef | Port | Amaç |
| --- | --- | --- | --- |
| Yönetici (SSH tüneliyle) | `runner` | 22, 3000 | Yönetim ve Grafana panoları |
| `runner` | `staging`, `production` | 22 | Dağıtım, yedek çekme, tanı komutları |
| `runner` | `staging`, `production` | 9100 | Prometheus, node_exporter metriklerini çeker |
| `runner` | `staging`, `production` | 443 | blackbox servis kontrolü ve uygulama `/metrics` (nginx yalnızca runner'a izin verir) |
| Herkes | `staging`, `production` | 80, 443 | Uygulama kullanımı |
| `runner` | GitHub ve `ghcr.io` | 443 | İş kuyruğu, kod çekme, imaj gönderme ve çekme |
| `runner` | Gmail SMTP | SMTP | Alertmanager e-posta bildirimi |

## Sınır kuralları

- Yönetim erişimi (SSH ve metrikler) yalnızca runner adresine açıktır.
- `/metrics` yolu dışarıya kapalıdır: nginx yalnızca runner adresine izin verir, diğer adresler reddedilir.
- Uygulama ve veritabanı konteynerleri sunucu ağına port açmaz. Dışarıdan tek giriş noktası nginx'tir.
- Staging ve production ayrı `.env` dosyaları ve ayrı parolalar kullanır.

## Bilinen açıklar

- **Grafana (3000) runner'da tüm arayüzlerde dinler.** Erişim SSH tüneliyle yapılır, ama iyileştirme olarak yalnızca localhost'a bağlanabilir.
