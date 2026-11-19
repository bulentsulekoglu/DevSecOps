# Senaryo 1: nginx yanlış upstream portu (502 Bad Gateway)

## Özet

staging ortamında nginx'in uygulamaya yönlendirdiği port kasıtlı olarak 8000'den 8001'e çevrildi. Uygulama sağlıklı kaldı ama nginx ona ulaşamadı, `/health` 502 döndü. İki alarm tetiklendi ve e-posta ile bildirildi. Ayar geri alındığında hizmet düzeldi, ancak ilk düzeltme denemesi etki etmedi ve nginx konteynerinin yeniden başlatılması gerekti.

Hata süresi: 17:54:08 - 17:58:26 (Türkiye saati), yaklaşık 4 dakika 18 saniye.

## Kök neden

nginx yapılandırmasındaki üç `proxy_pass` satırı uygulama konteynerinin dinlemediği 8001 portuna işaret ediyordu. Uygulama 8000'de dinliyordu. nginx isteği alıp uygulamaya iletemeyince istemciye 502 döndürdü.

Uygulamanın kendisinde bir sorun yoktu, bu doğrudan kanıtlandı: nginx atlanıp uygulamaya konteyner içinden 8000 portundan sorulduğunda `{"status":"ok"}` döndü.

## Belirtiler

- `https://<staging>/health` isteği 502 döndü.
- Blackbox servis kontrolü (`/health`) başarısız oldu, kontrolü yapan Blackbox-Exporter'ın kendi isteği de nginx günlüğünde 502 olarak göründü.
- nginx günlüğünde her istek için `Connection refused` hatası ve upstream adresi 8001 olarak görünüyor.
- İki alarm tetiklendi: `ServisErisilemiyor` ve `UygulamaMetrikleriGelmiyor`.

## Teşhis adımları

1. **Belirtiyi doğrula:** `/health` isteği 502 döndürdü.
2. **nginx günlüğüne bak:** her istek için `connect() failed (111: Connection refused) while connecting to upstream` ve upstream olarak 8001 portu görüldü. Hatayı üreten nginx'in kendisi, uygulama değil.
3. **Uygulamayı nginx'ten bağımsız sına:** nginx konteynerinden uygulamaya `http://app:8000/health` isteği gönderildi, cevap `{"status":"ok"}`. Uygulama sağlam, sorun yönlendirmede.
4. **Yapılandırmayı oku:** `grep proxy_pass` üç satırın hepsinde 8001 gösterdi.

## Zaman çizelgesi (Türkiye saati, UTC+3)

| Saat | Olay |
| --- | --- |
| 17:54:08 | nginx yapılandırması 8001'e çevrildi, yeniden yüklendi. Hata başladı |
| 17:54:24 | `ServisErisilemiyor` ve `UygulamaMetrikleriGelmiyor` bekleme (pending) durumuna girdi |
| 17:55 | `ServisErisilemiyor` (critical) e-postası geldi |
| 17:56 | `UygulamaMetrikleriGelmiyor` (warning) e-postası geldi |
| 17:57:33 | İlk düzeltme denemesi: dosya geri konuldu, ama `/health` hâlâ 502 |
| 17:58:26 | nginx konteyneri yeniden başlatıldı, `/health` 200 döndü. Hata bitti |
| 18:00 | `ServisErisilemiyor` çözüldü e-postası geldi |
| 18:01 | `UygulamaMetrikleriGelmiyor` çözüldü e-postası geldi |

## Alarm değerlendirmesi

| Alarm | Sonuç | Neden |
| --- | --- | --- |
| `ServisErisilemiyor` | Tetiklendi | Blackbox `/health` kontrolü 1 dakika başarısız oldu |
| `UygulamaMetrikleriGelmiyor` | Tetiklendi | Prometheus uygulama metriklerini de nginx üzerinden çeker, o hat da koptu |
| `SunucuHatalari5xx` | Tetiklenmedi | 502'yi nginx üretti, istek uygulamaya hiç ulaşmadı. Uygulamanın kendi 5xx sayacı boş kaldı |

`SunucuHatalari5xx` yalnızca uygulamanın kendi ürettiği hataları yakalar. nginx kaynaklı 502'ler için `ServisErisilemiyor` devreye girer. İki alarm birbirinin eksiğini kapatan farklı katmanlardır, bu bir boşluk değil bilinen bir iş bölümüdür.

## Düzeltme

1. Yedek dosya (`default.conf.bak`) geri konuldu ve yapılandırma sınandı (`nginx -t` başarılı). Bu adım hizmeti düzeltmedi, `/health` hâlâ 502 döndürdü.
2. Çalışan nginx'in gerçekte hangi ayarı kullandığına bakıldı (`nginx -T`): hâlâ 8001 görünüyordu. Dosya doğru, çalışan süreç eski ayarda kalmıştı.
3. nginx konteyneri yeniden başlatıldı (`docker restart`). Ayar doğru okundu, `/health` 200 döndü.

Büyük olasılıkla neden: yapılandırma dosyası konteynere tek dosya olarak bağlı, hatayı kurarken dosyanın içeriği yerinde değiştirildi, geri alırken ise dosya `mv` ile yeni bir dosyayla değiştirildi. Konteyner eski dosyaya bağlı kaldı. Bu açıklama kanıtla tutarlı ama bağlantı türü ayrıca doğrulanmadı.

## Çıkarılan dersler

- **"Dosya doğru" ile "çalışan süreç doğru ayarı kullanıyor" aynı şey değildir.** Düzeltmeden sonra `nginx -T` ile çalışan ayarı doğrulamak ve `/health` yanıtına bakmak gerekir.
- **`nginx -t` anlam hatalarını yakalamaz.** Yanlış port sözdizimi açısından geçerlidir, sınama başarılı döner.
- **Yapılandırma değişiklikleri pull request ile gelir.** nginx ayarı repoda sürümlenir, sunucuda elle değiştirmek yerine PR ile değiştirmek hem iz bırakır hem gözden geçirilir.
- **İzleme iki yönden doğrulandı:** blackbox dıştan servisi, uygulama metrikleri içten hizmeti izler. Biri tek başına yeterli olmazdı.
