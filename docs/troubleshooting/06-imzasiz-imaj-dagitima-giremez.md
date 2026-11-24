# Senaryo 6: imzasız imaj dağıtıma giremez

## Özet

PDF'in 10. maddesindeki ileri seviye geliştirme yapıldı: imajlar Cosign ile **anahtarsız** imzalanıyor ve dağıtımdan önce imza doğrulanıyor. Üç ayrı durum denendi: imzasız imaj reddedildi, bizim CI hattının `main` dalında imzaladığı imaj kabul edildi, aynı imaj yanlış imzalayan beklentisiyle verilince reddedildi. Production şu an imzalı bir imajı çalıştırıyor. Veritabanına ve uygulama verisine dokunulmadı.

## Önce yapılan iyileştirme: imzalama ve doğrulama

| Parça | Ne yapar |
| --- | --- |
| `build-push` işi, imzalama adımı | İmaj registry'ye gönderilip digest'i alındıktan sonra Cosign ile imzalar. İmzayı atan kimlik, GitHub'ın bu koşu için verdiği geçici kimliktir (OIDC). Saklanan uzun ömürlü gizli anahtar yoktur. |
| `verify-image` işi | Dağıtım işlerinden önce çalışır. İmzanın **bu deponun `ci.yml` iş akışı tarafından, `main` dalında** atıldığını doğrular. |
| `deploy-staging`, `deploy-production` | `verify-image` işine bağlandı. Doğrulama düşerse dağıtım işleri hiç başlamaz. |
| `scripts/verify-image.sh` | Doğrulamayı yapan script. İmaj digest ile verilmezse çalışmaz. |

Tasarım kararları:

- **Anahtarsız imzalama** seçildi: çalınacak sır yok, depoda ve runner'da saklanan imza anahtarı yok.
- **Doğrulama ayrı bir iş.** Doğrulamayı dağıtım işinin içine koysaydık, doğrulama düştüğünde "başarısız yayını geri al" adımı da çalışırdı ve ortada geri alınacak bir şey olmadığı için yanlış bir geri alma tetiklenirdi. Ayrı iş olduğundan dağıtım hiç başlamıyor.
- Cosign aracı konteyner olarak çalışıyor ve sürümü sabit (`v2.6.5`), Trivy, Gitleaks ve Semgrep ile aynı yöntem. İmzalama ve doğrulama aynı sürümle yapılıyor.
- Runner'ın kendi docker ayarı Cosign konteynerine verilmiyor. Her iş için geçici bir giriş açılıp iş bitince siliniyor.

## Başlangıç durumu

- Production, Cosign eklenmeden önce üretilmiş imzasız bir imajı çalıştırıyordu (commit `b9fa70a`, digest `sha256:ffc783c3...`).
- İmaj paketi herkese açık okunabiliyor (giriş yapmadan çekilebiliyor).

## Denemeler

Doğrulama komutu üç farklı durumda elle çalıştırıldı.

| # | Durum | Beklenen | Sonuç |
| --- | --- | --- | --- |
| 1 | İmzasız eski production imajı, `scripts/verify-image.sh` ile | Reddedilmeli | `no signatures found`, çıkış kodu 10 |
| 2 | Birleştirmeden sonra production'daki yeni imaj (commit `9baf157`, digest `sha256:89ee9011...`), doğrudan `cosign verify` ile | Kabul edilmeli | Doğrulama geçti, çıkış kodu 0 |
| 3 | Aynı yeni imaj, beklenen imzalayan olarak başka bir depo adı verilerek | Reddedilmeli | `none of the expected identities matched`, çıkış kodu 12 |

Deneme 2'nin çıktısından okunan bilgiler:

- İmzalanan şey: production'daki imajın digest'i (`89ee9011...`).
- Kimliği veren: `token.actions.githubusercontent.com` (GitHub Actions).
- İmzalayan: bu deponun `.github/workflows/ci.yml` iş akışı, `refs/heads/main`.
- Tetikleyen olay: `push`.
- İmzayı atan koşunun commit'i: `9baf157`, sayfa altındaki sürüm yazısıyla aynı.
- Herkese açık kayıt defterindeki (Rekor) sıra numarası: `4072345398`. İmza 24 Kasım 2026 saat 10:29'da (Türkiye saati) kayda yazıldı.

## Zaman çizelgesi (Türkiye saati, UTC+3)

| Zaman | Olay |
| --- | --- |
| 23 Kasım, yaklaşık 17:06 | Deneme 1: imzasız imaj reddedildi (birleştirmeden önce, `feat/cosign` dalında) |
| 23 Kasım, birleştirmeden sonra | Pipeline yeni imajı imzaladı, `verify-image` yeşil oldu, staging ve production dağıtımı geçti |
| 24 Kasım, 10:29 | İmza Rekor kaydına yazıldı |
| 24 Kasım, yaklaşık 10:34 | Deneme 2: imza kabul edildi |
| 24 Kasım, yaklaşık 10:36 | Deneme 3: yanlış kimlik reddedildi |

Birleştirme ve dağıtım saatleri bu kayıtta tutulmadı, yalnızca sırası biliniyor.

## Gözlemler

- **İmzasız imaj reddedildi.** Eski production imajı Cosign'dan önce üretildiği için imzası yoktu, doğrulama bunu hemen yakaladı.
- **Kimlik de doğrulanıyor, yalnızca imza varlığına bakılmıyor.** Deneme 3'te imza geçerli olduğu halde, beklenen imzalayan farklı olduğu için ret geldi. Bir saldırgan kendi hesabıyla geçerli bir imza atsa da bu kontrolü geçemez.
- **İmaj paketi herkese açık olduğundan, doğrulama için ek yetki gerekmedi.** Herhangi bir dış kullanıcı aynı komutu çalıştırıp imajın kökenini görebilir.
- **İmza olayı herkese açık bir kayıt defterine yazılıyor.** İmzanın hangi iş akışından ve hangi commit'ten geldiği, silinemeyen bir kayıtta duruyor.

## Değerlendirme ve sınır

Dürüst sınırlar:

- **İmzasız imajın hat içinde reddedilmesi denenmedi.** Doğrulama komutu imzasız imajla elle çalıştırıldı ve reddedildi. Pipeline'ın kendisine bilerek imzasız bir imaj verilip `verify-image` işinin düştüğü ve dağıtımın başlamadığı görülmedi. Hat içindeki davranış, iş bağımlılıklarının (`needs`) okunmasına dayanıyor, ölçülmedi.
- **Doğrulamayı runner yapıyor.** Staging ve production sunucuları imzayı kendileri doğrulamıyor. Runner ele geçirilirse bu kontrol aşılabilir.
- **Eski imajlara dönüş.** Geri alma, daha önce kaydedilmiş imajlara dönebilir. Cosign'dan önceki imajlar imzasızdır ve geri alma bu imajlara dönerken doğrulama yapılmıyor. İmzalı sürümler biriktikçe bu risk azalır.
- **Cosign aracı sürüm etiketiyle sabitlendi, digest ile değil.**

## Geri alma ve doğrulama

Bu senaryo canlı sistemi bozacak bir hata kurmadığı için geri alınacak bir şey yoktu. Kontrol olarak:

1. Production `/version` yanıtı yeni sürümü ve yeni digest'i gösteriyor (`release` 1.0.0, digest `89ee9011...`).
2. Cosign doğrulaması bu digest için geçiyor.
3. Eski imzasız digest hâlâ `no signatures found` döndürüyor.

## Çıkarılan dersler

- **Digest imajın içeriğini sabitler, imza ise kökenini kanıtlar.** İkisi birbirini tamamlar.
- **İmzayı doğrularken imzalayanın kimliği de belirtilmelidir.** Yalnızca "imza var mı" diye bakmak yetmez.
- **Doğrulama, geri almayı tetiklememesi için dağıtımdan ayrı bir işte yapılmalıdır.**
- **Anahtarsız imzalama saklanacak sırrı ortadan kaldırır, karşılığında imza kaydı herkese açık bir kayıt defterinde durur.** Bu, açık bir repo için sorun değildir, gizli bir repo için düşünülmelidir.
- **Aracın sürümünü sabitlemek yetmez, mümkünse digest ile sabitlemek bir adım daha güvenlidir.**
