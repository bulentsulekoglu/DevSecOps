# Güvenlik Politikası ve Eşikler

Bu doküman, CI/CD pipeline'ındaki güvenlik taramalarının hangi bulgularda pipeline'ı durdurduğunu ve nedenini tanımlar. Eşikler `.github/workflows/ci.yml` dosyasının en üstündeki `env:` bölümünde tutulur. Eşik değiştirmek, bu politikayı değiştirmektir ve PR ile gerekçeli yapılır.

## Eşikler

| Tarama | Araç | Pipeline'ı durdurur | Sadece raporlanır |
|---|---|---|---|
| Sır tarama | Gitleaks | Her bulgu | - |
| Statik kod analizi | Semgrep | ERROR, WARNING | - |
| Bağımlılık taraması | Trivy | HIGH, CRITICAL (düzeltmesi mevcut) | MEDIUM |
| İmaj taraması | Trivy | HIGH, CRITICAL (düzeltmesi mevcut) | MEDIUM |

## Gerekçeler

- **Sır: sıfır tolerans.** Sızmış bir parola ya da anahtar için "düşük risk" yoktur. Bulunursa değer hemen döndürülür (rotate), sadece koddan silmek yetmez, çünkü git geçmişinde kalır.
- **HIGH ve CRITICAL durdurur.** Bunlar istismar edilebilir ciddi açıklardır. MEDIUM'u da durdurucu yapmak gürültüyü artırır, ekip kontrolleri aşmanın yollarını arar ve gerçek tehlikeler kaybolur.
- **Düzeltmesi olmayan açıklar durdurmaz** (`--ignore-unfixed`). Yapılabilecek bir şey yoktur, pipeline'ı kilitlemek sadece işi durdurur. Ama görmezden gelinmez: bu tür bulgular gerekçeyle kayda geçer, düzeltme çıkınca yeniden değerlendirilir.
- **MEDIUM raporlanır.** Engellemez ama her çalışmada log'da görünür, böylece birikip gözden kaçmaz.
- **Semgrep'te INFO dışarıda.** Bilgilendirme düzeyindeki bulgular gürültü üretir, çoğu zaman eyleme dönüşmez.

## İstisna süreci

Düzeltilemeyen ya da yanlış pozitif olan bir bulgu kabul edilecekse:

1. İstisna PR ile eklenir, doğrudan `main`'e girmez.
2. Her istisna için şunlar yazılır: bulgu kimliği (CVE ya da kural adı), neden kabul edildiği, kimin onayladığı ve **bitiş tarihi**.
3. Bitiş tarihinde istisna yeniden değerlendirilir. Süresiz istisna verilmez.

## Araç sürümleri

Araçlar sabit sürümle çalıştırılır (etiketler sonradan değiştirilebileceği için `latest` kullanılmaz). Trivy'nin 2026 Mart'ındaki tedarik zinciri olayı bu yüzden önemlidir: `trivy-action` kullanılmaz, Trivy doğrudan Docker imajından çalıştırılır. Sürüm yükseltmeleri PR ile yapılır.
