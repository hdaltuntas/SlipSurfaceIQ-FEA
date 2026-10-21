# S4 örnek çıktıları

`results.json` beş tamamlanmış SlipSurfaceIQ-FEA koşusunu içerir. Üretim çözücüsü
`b51733abd39fffd8390864f92de66a66fb20bbc8` ile aynıdır; bu değişiklik yalnız aktarım
örneğini, testlerini ve belgeleri ekler.

- `h050`, `h025`, `h0125`: 0.5/0.25/0.125 m yerel T6+Q8 ağ, high integrasyon.
- `h050-half-steps`: 0.5 m ağda başlangıç/azami adım 0.05/0.25.
- `h050-split-release`: aynı kazı yükünün %50 ve kalan kısmı ayrı çözüm aşamalarında.
- Her koşu için `wall-end-forces.csv` iki uç değerini korur;
  `wall-displacements.csv` tekil duvar düğümlerini içerir.
- Bütün koşuların fiziksel girdileri `case.json` ile aynıdır; SHA-256 özeti
  sonuç kaydındadır. Tam ağlı `model.json` dosyaları tekrar aracıyla üretilir.

Kaynak komutları, işaretler, ölçütler ve kapsam [S4 protokolünde](../../s4-comparison.md).
Bağımsız palplanş programının sonuçları bu dizinde **yoktur**; S4 geçişi ilan edilmez.
