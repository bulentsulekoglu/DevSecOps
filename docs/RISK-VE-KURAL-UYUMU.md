# Risk ve Kural Uyumu Belgesi

Ölçümler 19 Kasım 2026 tarihlidir. Bulgular ya doğrudan ölçüldü ya da repodaki dosyalardan okundu. Ölçülmeyen noktalar "teyit gerekli" olarak işaretlidir.

## 1. Ödev kurallarına uyum

| Kural | Durum | Kanıt ve not |
| --- | --- | --- |
| Production ve gerçek şirket kimlik bilgisi kullanılmaz | Uyuyor | Laboratuvar ortamı. Alertmanager e-posta için Gmail SMTP uygulama parolası kullanıyor, parola `monitoring/secrets` altında ve repoda yok. Hesap kişiseldir, şirkete ait değildir |
| Repoda gizli bilgi yok | Uyuyor | Her pull request'te Gitleaks tüm geçmişi tarar. `.env` dosyaları yalnızca sunucularda. İlk bulgu (test parolası) allowlist ile değil, parolayı çalışma anında üreterek giderildi |
| Production dağıtımı pipeline ve yetkili onayla yapılır | Kısmen uyuyor | Production yalnızca `main` dalından ve onaylayıcı tanımlı ortamdan dağıtılır. Tek kişilik laboratuvarda onaylayıcı kodu yazan kişinin kendisi, dört göz ilkesi yok (R6) |
| `latest` yerine digest ya da sürüm etiketi | Kısmen uyuyor | Uygulama imajı digest ile dağıtılır, `latest` etiketi artık yayınlanmıyor (PR 28). Üçüncü taraf imajlarda eksikler var (R5) |
| Güvenlik kontrolleri nedensiz kapatılmaz | Uyuyor | Hiçbir kontrol kapatılmadı. Tek sapma TLS doğrulamasının izleme araçlarında kapalı olması (R3), gerekçesi self-signed sertifika |
| Ayrıcalıklı runner belgelenir | Uyuyor | Bölüm 2 |
| Her tasarım kararı ve komut açıklanabilir | Uyuyor | Kararlar `docs/` altında, hata kayıtları `docs/troubleshooting/` altında |

## 2. Ayrıcalıklı runner

**Ölçüm:** runner kullanıcısı `docker`, `sudo` ve `lxd` gruplarının üyesi. Runner bu kullanıcının ev dizininde kurulu (`~/actions-runner`), iş akışları bu kullanıcının yetkileriyle çalışır. Servisin hangi kullanıcıyla çalıştığı `systemctl` çıktısıyla ayrıca teyit edilmeli.

**Neden ayrıcalıklı:** pipeline imaj üretiyor, tarama araçlarını konteynerde çalıştırıyor ve SSH ile iki ortama dağıtıyor, bunların hepsi Docker erişimi istiyor. `docker` grubu pratikte root yetkisi demektir, çünkü bu gruptaki biri sunucunun dosya sistemini bir konteynere bağlayabilir. `lxd` grubu da aynı türden bir yetki taşır.

**Sonuç:** runner'da kod çalıştırabilen biri runner'da root olur ve runner'daki SSH anahtarlarıyla staging ve production'a ulaşabilir.

**Mevcut önlemler:**
- `main` dalı korumalı, dört kontrol zorunlu, force push ve silme yasak.
- Repo herkese açık olduğu için dışarıdan gelen pull request'lerin çalışması tüm dış katkıcılar için onaya bağlı.
- İşlerde `permissions` blokları tanımlı.
- Production ortamı onaylayıcı gerektirir.
- Staging ve production'da SSH yalnızca runner adresinden kabul edilir (UFW).
- Kimlik bilgisi diskte tutulmaz: her iş girişini yapıp çıkışını yapar.

**Eksikler (ölçüldü):** runner'da UFW kapalı. Sertleştirme betikleri staging ve production'a uygulandı, UFW'nin kapalı olması runner'a uygulanmadığını gösteriyor. Diğer ayarlar ölçülmedi.

## 3. Risk tablosu

| No | Risk | Önem | Durum | Gerekçe ve önerilen iyileştirme |
| --- | --- | --- | --- | --- |
| R1 | Runner kullanıcısı `docker`, `sudo`, `lxd` gruplarında (root eşdeğeri) | Yüksek | Kabul edildi | İşler Docker gerektiriyor. İyileştirme: `lxd` üyeliği gereksiz görünüyor (teyit gerekli), kaldırılabilir. Rootless Docker ya da ayrı bir runner kullanıcısı değerlendirilebilir |
| R2 | Runner'da UFW kapalı, Grafana (3000) tüm arayüzlerde dinliyor | Yüksek | Açık | Laboratuvar ağındaki herkes Grafana'ya ulaşabilir. İyileştirme: UFW ile 22 ve 3000'i yalnızca yönetici erişim noktasına aç. Grafana'ya erişim bir tünelle runner'ın ağ adresinden yapılıyor, kural tünelin geldiği adresi kapsamalı yoksa erişim kesilir |
| R3 | `insecure_skip_verify` açık (`blackbox.yml`, `prometheus.yml`) | Orta | Kabul edildi | Sertifika self-signed ve ağ izole. Etki: izleme sahte sertifikayı fark etmez, sertifika süresi izlenemez. İyileştirme: kendi CA'sını izleme araçlarına tanıt ya da gerçek sertifika kullan |
| R4 | Swagger sayfaları (`/docs`, `/redoc`, `/openapi.json`) staging ve production'da açık | Orta | Açık | Tüm uç noktalar ve alan şemaları herkese görünür. Kimlik gerektiren uç noktalar yine giriş ister, yani doğrudan yetkisiz erişim vermez. İyileştirme: production'da uygulama ayarından kapat ya da nginx'te yalnızca yönetici adresine aç |
| R5 | Üçüncü taraf imajlar tam sabitlenmemiş | Orta | Açık | `nginx-unprivileged:stable-alpine` kayan bir kanal etiketi, `postgres:16-alpine` 16 sürümü içinde kayıyor. İzleme imajları (Prometheus, Alertmanager, Grafana, node-exporter, blackbox) sürüm etiketli ama digest ile sabit değil. CI araç imajları (Trivy, Gitleaks, Semgrep, Cosign) da sürüm etiketiyle sabit, digest ile değil. İyileştirme: çalışan sürümü öğrenip tam sürüm ya da digest ile sabitle |
| R6 | Onaylayıcı ile kodu yazan aynı kişi, `main` için onay sayısı 0 | Orta | Kabul edildi | Tek kişilik laboratuvar. İyileştirme: ikinci bir onaylayıcı ve pull request'te en az bir onay |
| R7 | Dağıtım sırasında kimlik bilgisi kısa süre diskte | Düşük | Kabul edildi | Dağıtım günlüğündeki "credentials are stored unencrypted" uyarısı bunu gösteriyor. Giriş, çekme ve çıkış sırası boyunca kalıyor, çıkıştan sonra kayıt yok (runner ve staging'de `auths` boş, ölçüldü) |
| R8 | CIS ve Lynis'te kabul edilen kalemler | Düşük | Kabul edildi | Aşağıda |
| R9 | İmza doğrulamasını yalnızca runner yapıyor | Orta | Kabul edildi | Staging ve production sunucuları imzayı kendileri doğrulamıyor, runner ele geçirilirse doğrulama aşılabilir. Ayrıca imzasız bir imajın hat içinde reddedildiği (dağıtım işinin hiç başlamadığı) denenmedi, yalnızca doğrulama komutu elle sınandı (Senaryo 6). İyileştirme: dağıtım sırasında hedef sunucuda da `cosign verify` çalıştır, hatta bilerek imzasız bir imajla hattı sına |
| R10 | Geri alma imzasız eski imajlara dönebilir | Düşük | Kabul edildi | Cosign'dan önce üretilmiş imajlar imzasızdır ve geri alma daha önce kaydedilmiş bir imaja dönerken imza doğrulaması yapılmıyor. İmzalı sürümler biriktikçe risk azalır. İyileştirme: `rollback.sh` içinde hedef imajı da doğrula |

**R8 ayrıntısı.** Docker Bench başarısız kontrolleri 32'den 11'e (skor 6'dan 51'e), Lynis puanı 65'ten 77'ye (öneriler 48'den 29'a) çıktı. Bilerek kabul edilen Docker Bench kalemleri: ayrı bölüm (1.1.1), `userns-remap` (2.9), yetkilendirme eklentisi (2.12), uzak günlük (2.13), içerik güveni (4.5, yerine digest sabitleme kullanılıyor), üçüncü taraf imajlarda `HEALTHCHECK` (4.6), ayrıcalıklı portlar 80 ve 443 (5.8, 5.9), bağlanma arayüzü (5.14), yeniden başlatma politikası (5.15, `on-failure` yerine `unless-stopped` seçildi). `ip_forward` bilerek değiştirilmedi, Docker'ın ağı buna ihtiyaç duyuyor. Compose ağları konteynerler arası iletişim gerektirdiği için varsayılan köprü ağında `icc` kapalı, compose ağlarında açık.

## 4. Kapatılan riskler

- `latest` etiketi yayını durduruldu (PR 28).
- `trivy-action` tedarik zinciri riski: Trivy doğrudan sabit sürümlü imajdan çalıştırılıyor.
- Starlette ve zlib1g kaynaklı HIGH bulgular yamalandı.
- `pip` çalışma imajından çıkarıldı (MEDIUM bulgular ortadan kalktı).
- Test parolası Gitleaks bulgusu allowlist kullanılmadan giderildi.

## 5. Önerilen iyileştirme sırası

1. R2: runner'da UFW (önce tünelin geldiği adresi öğren).
2. R4: Swagger sayfalarını production'da kapat.
3. R5: nginx ve postgres imajlarını sabitle.
4. R6: ikinci onaylayıcı.
5. R3: sertifika ve doğrulama.
