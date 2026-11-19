# Senaryo 3: runner container registry'ye ulaşamıyor

## Özet

Runner'ın `ghcr.io` için ad çözümlemesi kasıtlı olarak bozuldu: `/etc/hosts` dosyasına bu alan adını `127.0.0.1`'e yönlendiren bir satır eklendi. Pipeline'ın `build-push` işi registry'ye giriş adımında 12 saniyede başarısız oldu ve sonraki tüm imaj adımları atlandı. Kayıt defteri adresi geri verilince erişim düzeldi.

Hata süresi: 13:55:29 - 13:59:08 (Türkiye saati), yaklaşık 3 dakika 39 saniye.

## Neden bu yöntem seçildi

Ödev dört olası nedeni sayıyor: DNS, güvenlik duvarı, izin ve token. Token'ı bozmak için önce kimlik bilgisinin nerede durduğuna bakıldı: runner'da ve staging'de diskte kayıtlı kimlik bilgisi yok (`~/.docker/config.json` içinde kayıt defteri girişi bulunmuyor). Her iş kendi girişini `GITHUB_TOKEN` ile yapıyor ve işin sonunda çıkış yapıyor (`ci.yml` içinde `docker login` ve `docker logout`, `deploy.sh` içinde hedefte giriş, çekme, çıkış). Bozulacak bir dosya olmadığı için token yöntemi bir güvenlik ayarına ya da `ci.yml`'ye dokunmayı gerektirirdi.

DNS yöntemi daha güvenli çıktı: yalnızca bir alan adını etkiler, tek satır eklenip tek dosya geri konarak geri alınır, kimlik bilgisine ve güvenlik ayarlarına dokunmaz.

Başlamadan önce tarama araçlarının imajlarının (Trivy, Gitleaks, Semgrep) runner'da önbellekte olduğu doğrulandı. Böylece `ghcr.io` erişimi kesilince yalnızca registry'ye giriş yapan adım etkilenecek, tarama işleri etkilenmeyecekti.

## Kök neden (kurulan hata)

`/etc/hosts` dosyasına şu satır eklendi: `ghcr.io` → `127.0.0.1` (yorum olarak `SENARYO3-TEST`). Runner, kayıt defterine bağlanmak yerine kendi 80 numaralı portuna bağlanmaya çalıştı, orada dinleyen bir şey olmadığı için bağlantı reddedildi.

Başlangıç durumu: `ghcr.io` gerçek GitHub adresine çözülüyordu, `https://ghcr.io/v2/` isteği `401` (erişilebilir, kimlik doğrulaması istiyor) döndürüyordu. Hata sonrası: adres `127.0.0.1`, istek `000` (bağlantı kurulamadı).

## Belirtiler

- `build-push` işi `GitHub Container Registry'ye giriş` adımında kırmızı bitti, toplam süre 12 saniye.
- Günlükteki hata: `Error response from daemon: Get "http://ghcr.io/v2/": dial tcp 127.0.0.1:80: connect: connection refused`.
- `İmajı build et`'ten `SBOM'u arşivle`'ye kadar tüm adımlar atlandı. `Geçici dosyaları ve oturumu temizle` adımı yine çalıştı ve başarılı bitti, yani başarısız girişten sonra oturum temizliği bozulmadı.

## Teşhis adımları

1. **Hata satırını oku:** adres `127.0.0.1:80`. Gerçek bir ağ hatası ya da kimlik hatası olsaydı GitHub'ın adresi görünürdü. Kendi makinenin adresi ad çözümlemede sorun olduğunu gösteriyor.
2. **Alan adını çöz:** `getent hosts ghcr.io` komutu `127.0.0.1` döndürdü.
3. **`hosts` dosyasına bak:** `grep ghcr /etc/hosts` eklenen satırı gösterdi.
4. **Kayıt defterine doğrudan istek at:** `curl https://ghcr.io/v2/` bağlantı kuramadı (`000`), normalde `401` dönmesi gerekir.

## Zaman çizelgesi (Türkiye saati, UTC+3)

| Saat | Olay |
| --- | --- |
| 13:55:29 | `/etc/hosts` dosyasına yanlış kayıt eklendi. Hata başladı |
| hata penceresi içinde | `main` çalıştırması yeniden başlatıldı, `build-push` 12 saniyede başarısız oldu (kesin başlangıç saati kaydedilmedi) |
| 13:59:08 | Yedekten `/etc/hosts` geri konuldu, `ghcr.io` gerçek adrese döndü, `401` alındı. Hata bitti |

## Alarm değerlendirmesi

Hata penceresini kapsayan son 30 dakika için Prometheus'ta alarm geçmişi sorgulandı (13:31-14:01), hiçbir alarm kaydı bulunmadı. Hiçbir alarm `pending` ya da `firing` olmadı, e-posta da gönderilmedi. Beklenen sonuç buydu: blackbox yalnızca staging ve production uygulamalarının `/health` adresine bakıyor, runner'ın registry erişimini izleyen bir kural yok. Registry erişimi kesilince uygulama hizmeti etkilenmedi, bu yüzden izleme bir şey görmedi.

## Geri alma ve doğrulama

- `/etc/hosts` yedekten geri konuldu, `SENARYO3` kaydı kalmadı (`0` kayıt).
- `getent hosts ghcr.io` gerçek GitHub adresini, `curl https://ghcr.io/v2/` yeniden `401` döndürdü.
- Yedek dosya silindi, runner'da test izi kalmadı.

Bu kayıtta **doğrulanmadı**: (1) düzeltme sonrası aynı çalıştırmanın yeniden başlatılıp `build-push`'un yeşil bitmesi, (2) hata sırasında `lint-test`, `secret-scan`, `sast`, `dependency-scan` işlerinin durumu ve iki dağıtım işinin atlandığının görüntüsü. Tarama araçlarının önbellekte olması ölçüldüğü için tarama işlerinin etkilenmemesi beklenir, ama bu çalıştırmada görülmedi.

## Çıkarılan dersler

- **Hata mesajındaki adres, nedeni gösterir.** İstek GitHub'ın adresine değil `127.0.0.1`'e gittiyse sorun ağda ya da kimlikte değil, ad çözümlemededir. Ağ engeli olsaydı genellikle zaman aşımı, kimlik sorunu olsaydı `unauthorized` benzeri bir cevap görürdük. Bu ayrım genel bir ipucudur, bu çalışmada yalnızca DNS durumu denendi.
- **İş akışı registry'ye ilk temas noktasında durdu.** Hata erkenden (giriş adımı) yakalandı ve imaj hiç üretilmeden pipeline kesildi. Dağıtım işlerinin bu yüzden başlamaması beklenir, ama bu çalıştırmada iş listesi görülmedi. Bu akışla registry erişimi koparsa canlı ortama yarım bir sürüm gitme riski düşük görünüyor.
- **Kimlik bilgisi diskte tutulmuyor.** Her iş kendi girişini yapıp çıkışını yapıyor, bu yüzden token'ın sızması ya da eski bir kimlik bilgisinin kalması riski düşük. Bu aynı zamanda token senaryosunu bu ortamda kolayca simüle edilemez yapıyor.
- **Önbellekteki araç imajları pipeline'ı kısmen bağımsız tutuyor.** Tarama araçlarının imajları runner'da önbellekte olduğu için registry kesintisi taramaları bozmuyor.
- **Eksik izleme (ölçüldü):** runner'ın registry'ye ulaşıp ulaşamadığını izleyen bir kural yok, hata penceresinde hiçbir alarm çalmadı. Böyle bir kesinti ancak pipeline kırılınca fark ediliyor. Olası iyileştirme: runner'dan `ghcr.io`'ya düzenli bir kontrol (blackbox ile) ve ona bağlı bir alarm.
- **Süreç dersi:** test sırasında geri alma komutu yanlışlıkla hatayı kuran komutla aynı blokta verilmişti ve ilk denemede hata kurulur kurulmaz geri alındı. Hata kuran ve geri alan komutlar ayrı adımlarda verilmeli.
