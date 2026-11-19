# Senaryo 2: yeni sürüm sağlık kontrolünden geçemiyor ve otomatik geri alma

## Özet

Uygulamanın başlangıç komutundaki port kasıtlı olarak 8000'den 8001'e çevrilip pull request ile `main`'e birleştirildi. Pipeline'ın statik kontrolleri ve imaj üretimi başarılı geçti, ama staging'e dağıtım sırasında uygulama konteyneri `unhealthy` kaldı ve dağıtım başarısız oldu. Pipeline başarısız sürümü otomatik geri aldı, staging önceki sağlam sürüme döndü, production için onay hiç istenmedi. Düzeltme pull request'i birleştirilince iyi sürüm iki ortama da dağıtıldı.

Test daha önce 16 Kasım'da (PR 11 ve 12) yapılmıştı. Bu kayıt, uygulama sertleştirildikten sonra 19 Kasım'daki tekrardır.

## Kök neden

`app/Dockerfile` içindeki başlangıç komutu uygulamayı 8001 portunda başlatıyordu. `HEALTHCHECK` ve nginx ise 8000'e bakıyordu. Uygulama süreç olarak çalıştı ama beklenen portta cevap vermediği için sağlık kontrolü başarısız oldu ve konteyner `unhealthy` kaldı.

## Başlangıç durumu

| Ortam | Çalışan sürüm (digest) | Commit |
| --- | --- | --- |
| staging | `a594e2bf…` | `470bdfb` |
| production | `a594e2bf…` | `470bdfb` |

`previous` kaydı staging'de `635ec09c…` (commit `e7a339f`). Aktif alarm yoktu.

## Belirtiler ve pipeline davranışı

- Statik kontroller (`lint-test`, `secret-scan`, `sast`, `dependency-scan`) ve `build-push` **başarılı** geçti. Hata kodda ya da testlerde değildi, yalnızca konteynerin çalışma ayarındaydı, bu yüzden statik kontroller yakalayamadı.
- `deploy-staging` imajı çekti, uygulama konteynerini yeniden oluşturdu. Konteyner `unhealthy` kaldı, `deploy.sh` şu hatayla ve `exit code 1` ile durdu: `dependency failed to start: container myapp-app-1 is unhealthy`.
- `Smoke test` ve `Sürümü onayla` adımları atlandı.
- `Hata durumunda staging durumunu göster` ve `Başarısız yayını geri al` adımları çalıştı ve başarılı bitti.
- `deploy-production` **atlandı**, production için onay hiç istenmedi.

## Zaman çizelgesi (Türkiye saati, UTC+3)

| Saat | Olay |
| --- | --- |
| 11:44:10 - 11:45:10 | Blackbox'ın başarısız saydığı ölçümler (5 ölçüm, 15 saniye aralıkla) |
| 11:45:17 | `ROLLBACK` kaydı: bozuk imaj reddedildi, `a594e2bf…` geri kondu |
| 11:54:19 | Düzeltme birleşti, staging'e iyi sürüm dağıtıldı ve terfi etti (`deployed`, `promoted`) |
| 11:55:22 | Production onayı verildi, iyi sürüm dağıtıldı ve terfi etti |

Kesinti süresi yaklaşık 1 dakika 15 saniye: ilk başarısız ölçümden (11:44:10) geri almaya (11:45:17) kadar. Ölçüm adımı 15 saniye olduğu için hata payı ±15 saniye.

## Alarm değerlendirmesi

| Alarm | Gözlenen durum | Yorum |
| --- | --- | --- |
| `ServisErisilemiyor` | `pending`, sonra `firing` | 1 dakikalık beklemeyi doldurdu |
| `UygulamaMetrikleriGelmiyor` | Yalnızca `pending` | 2 dakikalık bekleme dolmadan hizmet düzeldi, ateşlenmedi |

`ServisErisilemiyor` e-postalarının gönderilme saatleri ve `UygulamaMetrikleriGelmiyor` için e-posta gelmediği bu kayıtta **doğrulanmadı** (e-posta kutusu görüntüsü eklenmedi). Alarm durumları Prometheus'un kendi geçmişinden okundu.

## Geri alma doğrulaması

- Staging'in `current` kaydı hata boyunca `a594e2bf…` olarak kaldı, bozuk sürüm hiçbir zaman `current` olmadı.
- Çalışan konteynerin imajı `a594e2bf…` idi (konteynerden doğrudan okundu), kayıtla tutarlı.
- `history.log`'a `ROLLBACK` satırı yazıldı (başarısız imaj ve geri konan imaj ile birlikte).
- Uygulama `healthy`, `/health` 200 döndürdü, aktif alarm kalmadı.
- Production'ın `current` kaydı ve `history.log` son satırları değişmedi.

## Düzeltme

Başlangıç komutundaki port 8000'e geri alındı, pull request ile birleştirildi. Sonuç (digest ve commit):

| Ortam | Sürüm (digest) | Commit |
| --- | --- | --- |
| staging | `4a4e899f…` | `7ee87f5` |
| production | `4a4e899f…` | `7ee87f5` |

İki ortamda da konteyner `healthy`, `/health` 200, çalışan konteynerin başlangıç komutu `--port 8000`, aktif alarm yok. İkinci dağıtımda `ROLLBACK` kaydı yok.

## Çıkarılan dersler

- **Sağlık kontrolü kapısı çalışıyor.** Statik kontrollerin yakalayamadığı bir çalışma hatası dağıtım sırasında yakalandı ve sürüm hiçbir zaman `current` olmadı.
- **Production korunuyor.** Staging başarısız olunca production için onay bile istenmedi, bozuk sürüm production'a ulaşma şansı bulmadı.
- **Geri alma digest ile yapılıyor.** Önceki sağlam sürümün digest'i kayıtlı olduğu için geri alma etiket tahminine ya da yeniden derlemeye dayanmıyor.
- **Bozuk sürüm `main`'de kalır.** Geri alma yalnızca çalışan ortamı korur, repodaki hata ayrıca bir düzeltme pull request'iyle giderilmelidir. Düzeltilene kadar sıradaki her birleşme yeniden bozuk dağıtım ve geri alma anlamına gelir.
- **Küçültülmüş imajda `ps` yok.** Çalışan sürecin portunu `ps` ile değil, `docker inspect` ile konteynerin başlangıç komutundan doğrulamak gerekti.
