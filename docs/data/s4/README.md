# S4 örnek çıktıları

`results.json` iki ara yüzünde de gömülü ucu kapalı SlipSurfaceIQ-FEA koşularını
içerir. Başlangıç commit'i ve değişen kaynak dosyalarının SHA-256 özetleri sonuç
dosyasındadır. Önceki, ekleme sırasına bağlı asimetrik uçlu sonuçlar
[5f0c4eb](https://github.com/hdaltuntas/SlipSurfaceIQ-FEA/tree/5f0c4eba64b1ad72ad01f9d8db52eace9f31446f/docs/data/s4)
commit'inde korunur; güncel sonuçların yerine kullanılmaz.

- `h050`, `h025`, `h0125`: 0.5/0.25/0.125 m yerel T6+Q8 ağ, high integrasyon.
- `h050-half-steps`: 0.5 m ağda başlangıç/azami adım 0.05/0.25.
- `h050-split-release`: aynı kazı yükünün %50 ve kalan kısmı ayrı çözüm aşamalarında.
- `h050-right-first`: aynı fiziksel modelin ara yüzleri ters sırayla eklenir.
- Her koşu için `wall-end-forces.csv` iki uç değerini korur;
  `wall-displacements.csv` tekil duvar düğümlerini içerir.
- Bütün koşuların fiziksel girdileri `case.json` ile aynıdır; SHA-256 özeti
  sonuç kaydındadır. Tam ağlı `model.json` dosyaları tekrar aracıyla üretilir.

Kaynak komutları, işaretler, ölçütler ve kapsam [S4 protokolünde](../../s4-comparison.md).
Bağımsız palplanş programının sonuçları bu dizinde **yoktur**. 21 Ekim 2026
kullanıcı kararıyla S4 işi kapatıldı, dış karşılaştırma ertelendi; doğrulama
geçişi ilan edilmez. Faz 4 başlatılmadı.
