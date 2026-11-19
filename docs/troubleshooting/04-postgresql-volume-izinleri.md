# Senaryo 4: PostgreSQL volume izinleri bozuldu

## Özet

staging ortamında PostgreSQL'in veri klasörünün sahibi kasıtlı olarak `root` yapıldı. PostgreSQL konteyneri `postgres` kullanıcısıyla (70:70) çalıştığı için veri klasörüne giremedi, başlayamadı ve sürekli yeniden başlama döngüsüne girdi. Uygulama çalışmaya devam etti ama veritabanına ulaşamadı, `/health` 500 döndürdü. İki alarm tetiklendi ve e-posta ile bildirildi. Sahip eski haline döndürüldü, veri kaybolmadı.

Hata süresi: 18:06:54 - 18:10:51 (Türkiye saati), yaklaşık 3 dakika 57 saniye.

## Kök neden

PostgreSQL veri klasörü (`/var/lib/postgresql/data`) volume'un sunucudaki klasörüne bağlıdır. Bu klasörün sahibi `root:root` yapıldı. Klasörün izinleri `drwx------` olduğu için yalnızca sahibine açıktır. Konteyner `70:70` kullanıcısıyla çalıştığından klasöre erişemedi ve başlangıçta şu hatayı verdi: `initdb: error: could not access directory "/var/lib/postgresql/data": Permission denied`.

Veri dosyaları silinmedi ya da değişmedi. Yalnızca en üst klasörün sahibi değiştirildi.

## Belirtiler

- `/health` isteği **500** döndürdü. Bu sefer hatayı nginx değil uygulamanın kendisi üretti.
- Veritabanı konteyneri `Restarting` durumundaydı, ölçüm anında 8 kez yeniden başlamıştı (`unless-stopped` politikası).
- Veritabanı günlüğünde `Permission denied` hatası.
- Uygulama günlüğünde `failed to resolve host 'db': Temporary failure in name resolution`. Veritabanı konteyneri ayakta kalamadığı için `db` adı çözülemedi.
- Tetiklenen alarmlar: `ServisErisilemiyor` ve `SunucuHatalari5xx`. `UygulamaMetrikleriGelmiyor` tetiklenmedi, alarm listesinde hiç görünmedi (uygulama ayaktaydı).

## Başlangıç durumu (hata öncesi)

- Veri `myapp_pgdata` adlı volume'da.
- Konteyner `70:70` kullanıcısıyla çalışıyor, restart politikası `unless-stopped`.
- Veri klasörü `70:70` sahipli, izinler `drwx------`.
- `/health` 200 döndürüyordu.

## Teşhis adımları

1. **Belirtiyi doğrula:** `/health` 500 döndürdü. Hata 502 olmadığı için sorun nginx'te değil, uygulamada ya da arkasında.
2. **Uygulama günlüğüne bak:** veritabanı adı çözülemiyor hatası. Bu ikincil bir belirti, asıl sorunu veritabanı tarafında aramak gerekiyor.
3. **Veritabanı konteynerine bak:** `Restarting` durumunda, yeniden başlama sayısı artıyor.
4. **Veritabanı günlüğünü oku:** `Permission denied` hatası, veri klasörüne erişilemediğini söylüyor.
5. **Sahibi doğrula:** volume klasörünün sahibine bakıldığında `0 0` (root) görünüyor, konteyner kullanıcısı ise `70:70`.

## Zaman çizelgesi (Türkiye saati, UTC+3)

| Saat | Olay |
| --- | --- |
| 18:06:54 | Veri klasörünün sahibi `root` yapıldı, veritabanı yeniden başlatıldı. Hata başladı |
| 18:07:09 | `ServisErisilemiyor` bekleme (pending) durumuna girdi |
| 18:07:22 | `SunucuHatalari5xx` bekleme durumuna girdi |
| 18:08 | `ServisErisilemiyor` ve `SunucuHatalari5xx` (critical) e-postaları geldi |
| 18:10:51 | Sahip `70:70` olarak geri verildi, veritabanı yeniden başlatıldı. Hata bitti |
| 18:13 | `ServisErisilemiyor` çözüldü e-postası geldi |
| 18:18 | `SunucuHatalari5xx` çözüldü e-postası geldi |

## Alarm değerlendirmesi

| Alarm | Sonuç | Neden |
| --- | --- | --- |
| `ServisErisilemiyor` | Tetiklendi | Blackbox `/health` kontrolü 500 aldığı için başarısız sayıldı |
| `SunucuHatalari5xx` | Tetiklendi | Uygulama kendi ürettiği 500 cevaplarını saydı, son 5 dakikada eşik (3) aşıldı |
| `UygulamaMetrikleriGelmiyor` | Tetiklenmedi | Uygulama ayaktaydı, alarm hiç listede görünmedi |

Senaryo 1'deki durumla fark: orada hatayı nginx ürettiği için `SunucuHatalari5xx` tetiklenmemişti. Burada hatayı uygulama ürettiği için bu alarm çalıştı. İki senaryo birlikte alarmların katman iş bölümünü gösteriyor.

`SunucuHatalari5xx` alarmı düzeltmeden yaklaşık 7 dakika sonra kapandı (18:10:51 → 18:18), çünkü kural son 5 dakikadaki 5xx sayısına bakıyor. Hata düzelse bile eski 5xx cevapları pencereden çıkana kadar alarm sürüyor.

## Düzeltme

1. Veri klasörünün sahibi hata öncesindeki değere (`70:70`) geri verildi. Yalnızca en üst klasöre dokunuldu, içerideki dosyalar değiştirilmedi.
2. Veritabanı konteyneri yeniden başlatıldı.
3. 15 saniye sonra doğrulandı: konteyner `healthy`, `devices` tablosu okunabiliyor (veri yerinde), `/health` 200 döndürüyor.

## Çıkarılan dersler

- **İlk görünen hata asıl sorun olmayabilir.** Uygulama günlüğü "ad çözülemedi" diyordu, asıl neden veritabanı günlüğündeki izin hatasıydı. Zincirin en başındaki bileşenin günlüğüne bakmak gerekir.
- **Konteyner kullanıcısı ile klasör sahibi uyumlu olmalı.** Sertleştirmede veritabanı root olmayan bir kullanıcıyla çalışıyor, bu yüzden volume klasörünün sahibi değişirse (elle yapılan bir `chown`, yanlış bir geri yükleme gibi) veritabanı hiç başlayamaz.
- **Veri kaybı olmadı.** Sorun izinde, veride değil. Düzeltme yalnızca sahibi geri vermekti.
- **Yeniden başlama döngüsü sessiz bir belirtidir.** `unless-stopped` politikası konteyneri sürekli kaldırmaya çalışır ve sorunu gizleyebilir. Yeniden başlama sayısı izlenecek bir göstergedir.
- **Alarmlar bu senaryoda iki katmanı da yakaladı:** dıştan servis erişimi (`ServisErisilemiyor`) ve uygulamanın kendi hata sayacı (`SunucuHatalari5xx`).
