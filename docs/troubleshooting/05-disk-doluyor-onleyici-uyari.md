# Senaryo 5: disk doluyor ve önleyici uyarı

## Özet

staging ortamında kök disk kontrollü olarak yaklaşık %88 doluluğa getirildi. Mevcut eşik alarmı (`DiskDoluyor`) çalıştı. Senaryo öncesinde ödevin "önleyici uyarı" şartı için eğilime bakan yeni bir kural (`DiskDolacak`) eklendi ve o da çalıştı. İki alarm e-posta ile bildirildi ve test dosyası silinince kendiliğinden kapandı. Veri kaybı olmadı, veritabanına ve Docker'a dokunulmadı.

## Önce yapılan iyileştirme: önleyici kural

Mevcut `DiskDoluyor` kuralı yalnızca eşiğe bakar: kök disk %85'i 5 dakika aşarsa uyarır. Bu, disk neredeyse dolunca haber verir, ödevin istediği "önleyici uyarı" ise dolmadan önce haber vermektir. Bu yüzden eğilime bakan ikinci bir kural eklendi:

| Kural | Koşul | Bekleme | Ne zaman uyarır |
| --- | --- | --- | --- |
| `DiskDoluyor` | Kök disk doluluğu %85'in üstünde | 5 dakika | Disk neredeyse doluyken |
| `DiskDolacak` | Son 1 saatin gidişatıyla boş alan 4 saat içinde sıfırın altına düşecek (`predict_linear`) | 15 dakika | Disk daha dolmadan, hızı ölçerek |

Kural pull request ile eklendi, kontroller geçti ve `promtool check rules` ile sınandı (14 kural).

Yükleme sırasında bir ders çıktı: kural dosyası Prometheus konteynerine tek dosya olarak bağlı olduğu için `git pull` sonrası konteyner eski dosyayı görmeye devam etti (konteynerdeki dosyada `DiskDolacak` bulunmuyordu, sunucudaki dosyada vardı). Bu, Senaryo 1'deki duruma benzer. HTTP üzerinden yeniden yükleme de kapalıydı, bu yüzden Prometheus konteyneri yeniden başlatıldı. Veri ayrı bir volume'da olduğu için geçmiş metrikler korundu. Yeniden başlatmadan sonra dokuz hedefin hepsi çalışıyordu.

## Başlangıç durumu

- Kök disk 67,3 GB, yaklaşık 12 GB dolu. Kuralın hesapladığı doluluk %24,17.
- Aktif alarm yok.

## Hatanın kurulması

Diski gerçekten doldurmak yerine kontrollü bir yöntem seçildi: staging'de ayrı bir klasörde `fallocate` ile 40 GiB'lık tek bir dosya oluşturuldu. `fallocate` gerçek veri yazmaz, alanı anında ayırır, yani saniyeler içinde biter ve tek `rm` ile geri alınır. Veritabanına ve Docker'a dokunulmadı.

Dosya boyutu hesapla seçildi: kuralın doluluğu ayrılmış blokları saymadığı için `df` çıktısının yüzdesi yerine kuralın kendi ölçtüğü değer kullanıldı. 40 GiB, doluluğu yaklaşık %87,97'ye çıkardı (boş alan yaklaşık 8,1 GB), %85 eşiğini aşar ama diski tamamen doldurmaz.

## Zaman çizelgesi (Türkiye saati, UTC+3)

| Saat | Olay |
| --- | --- |
| 10:46:39 | 40 GiB'lık test dosyası oluşturuldu. Doluluk yaklaşık %87,97 |
| 10:46:54 | `DiskDoluyor` bekleme (pending) durumuna girdi |
| 10:49:24 | `DiskDolacak` bekleme durumuna girdi (tahmin negatife döndü) |
| 10:52 | `DiskDoluyor` (warning) e-postası geldi |
| 11:04 | `DiskDolacak` (warning) e-postası geldi |
| yaklaşık 11:05-11:07 | Test dosyası ve klasörü silindi (kesin saat kaydedilmedi) |
| 11:07 | `DiskDoluyor` çözüldü e-postası geldi |
| 11:24 | `DiskDolacak` çözüldü e-postası geldi |

## Gözlemler

- **Eşik alarmı hızlı, tahmin alarmı yavaş çalıştı.** Ani bir sıçramada `DiskDoluyor` 6 dakikada, `DiskDolacak` 18 dakikada ateşlendi. İkisinin bekleme süreleri farklı (5 dakika ve 15 dakika) ve tahmin kuralı bir saatlik pencerede eğilimin oturmasını da bekliyor.
- **Tahmin değeri hemen negatife dönmedi.** Hatadan yaklaşık iki dakika sonraki ilk ölçümde 4 saat sonrası için tahmini boş alan hâlâ pozitifti (yaklaşık +12,2 GB), birkaç dakika sonra negatife döndü (yaklaşık -73,5 GB). Pencerenin büyük kısmı hata öncesi verilerle dolu olduğu için eğim önce yumuşak kaldı.
- **Alarmlar kendiliğinden kapandı.** Dosya silindikten sonra `DiskDoluyor` birkaç dakika içinde (11:07), `DiskDolacak` yaklaşık 17-19 dakika içinde (11:24) çözüldü. Önceden bir saate yakın süreceğini tahmin etmiştim, ölçüm bunun daha kısa olduğunu gösterdi. Olası açıklama: tahmin doğrusal regresyonla hesaplandığı için silme sonrası yükselen değerler eğimi hızla pozitife çevirdi.

## Değerlendirme ve sınır

Bu test **ani bir sıçramayı** ölçtü. Böyle bir durumda eşik alarmı daha hızlı çalışır ve tahmin alarmı yalnızca onu doğrular. `DiskDolacak` kuralının asıl değeri **yavaş ve düzenli büyümede** ortaya çıkar (büyüyen günlükler, birikmiş yedekler gibi): boş alan eşiğe henüz gelmeden, hızı görüp saatler önceden uyarır. Yavaş büyüme senaryosu bu çalışmada denenmedi, kuralın o durumdaki davranışı ölçülmedi.

## Geri alma ve doğrulama

1. Test dosyası ve klasörü silindi.
2. Boş alan başlangıç değerine döndü (yaklaşık 51 GB).
3. `/health` 200 döndürdü, aktif alarm kalmadı (her iki alarm da çözüldü e-postası gönderdi).

Disk dolu kaldığı sürede `/health` ölçülmedi, yalnızca silme sonrası doğrulandı.

## Çıkarılan dersler

- **Eşik alarmı ile tahmin alarmı birbirini tamamlar.** Eşik alarmı ani doluluğu, tahmin alarmı yavaş büyümeyi yakalar.
- **`df` yüzdesi ile alarm kuralının hesapladığı doluluk aynı değildir.** Test boyutunu kuralın kendi ölçümüyle belirlemek gerekir.
- **Tek dosya olarak bağlanmış yapılandırma dosyaları `git pull` ile güncellenmeyebilir.** Konteynerin gerçekte hangi içeriği gördüğü ayrıca kontrol edilmeli (`docker exec ... grep`), konteyner yeniden başlatılmadan önce de sonra da.
- **Kontrollü hata kurmak için gerçek dolgu yerine ayırma yöntemi kullanılabilir.** `fallocate` hızlı, güvenli ve tek komutla geri alınabilir.
