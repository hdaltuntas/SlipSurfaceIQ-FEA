# Faz 3 — devam durumu

Bu adım 6db8e55 üzerindeki mevcut Faz 3 WIP uygulamasını ilerletir. Referans:
*SlipSurface 2D — Teknik Mimari ve Yol Haritası*, Faz 3 ve Ek A.

| Yol haritası maddesi | Durum | Kanıt / kalan iş |
|---|---|---|
| Aktif küme, kazı, load split, aktivasyon ve yer değiştirme referansı | Mevcut; S3 testi var | `test_s3_staging.py`: tek/çok aşama, üç gevşeme oranı, geri dolgu |
| Timoshenko liner, BAR2 ankraj, ön germe ve akma | Mevcut; S2 eklendi | Üç ankraj aralığında seri yay dengesi ve ön germenin tekrar uygulanmaması; S1/S4 henüz yok |
| Goodman ara yüzü ve düğüm çoğaltma | Mevcut; karma model kayıt testi eklendi | Ayrıntılı kayma/açılma ve tutarlı tanjant doğrulamaları halen gerekli |
| Aşama bazlı piezometrik su ve malzeme değişimi | Mevcut | Su ve statik birim testleri |
| HDF5 sonuçları ve `.ssproj` | Bu adımda eklendi | Sıkıştırma, aşama bazlı okuma, karma elemanların gidiş-dönüşü, hata halinde atomik kayıt |
| Kapı 3 | **Açık** | S1 liner'lı tünel ve S4 konsol palplanş benchmarkları eksik |

## Bu adımda bulunan ve düzeltilen hatalar

- Ön germeli ankrajın değişmeden tutulduğu aşamada sıfıra yakın yük artımı, kayan
  nokta iptal hatasını büyük bir göreli kalıntıya dönüştürebiliyordu. Sonuç, analitik
  dengede bile gereksiz adım küçültme ve yakınsamamaydı (S2, aralık 2.5 m). Newton
  kontrolüne kuvvet ölçeğine bağlı makine hassasiyeti eşiği eklendi; zorlanmış yer
  değiştirme artımları ilk iterasyondaki erken kabulden yine hariç tutulur.
- VTU dosyası kiriş/çubuk hücrelerini içerirken `plastic` dizisi yalnızca sürekli
  ortam elemanlarını kapsıyordu. Dizi artık tüm dışa aktarılan hücreleri kapsar;
  yapısal ve etkin olmayan hücrelerde bu alan NaN'dır. Düşük seviyeli yazıcı yanlış
  uzunluktaki hücre/nokta verisini reddeder.

## Sıradaki kapatma işleri

1. S1: elastik dairesel tünelde liner N ve M değerlerini Einstein–Schwartz referansı
   ile karşılaştır; ağ yakınsamasını göster.
2. Ara yüzün kayma/açılma, iki taraflı düğüm çoğaltma ve tanjant testlerini tamamla.
3. S4: konsol palplanşın maksimum momentini bağımsız kiriş-yay ve limit denge
   sonuçlarıyla karşılaştır.
4. S1–S4 ve aşama bölme değişmezliği birlikte geçince Kapı 3'ü kapat. Faz 4'e geçme.

## Sınırlar

Sonuç dosyaları yakınsamış aşama çıktılarıdır; nonlinear çözümün kaldığı yerden devam
etmesini sağlayan bir restart formatı değildir. Aktivasyon referansları ve solver'ın
commit durumu yeniden kurulmaz. `api.run(project.model)` modeli baştan çözer.
Performans kapısı Numba önbelleği ısıtılmış ve donanımı belirtilmiş ayrı bir ölçüm ister.

## Bu oturumun doğrulaması

- Linux / Python 3.12: `pytest -q -m 'not benchmark'`: **152 geçti**, PyVista
  kurulu olmadığından görüntüleyici modülü **1 atlandı**, performans testleri **2 hariç**.
- Sonradan eklenen iki plastik kayıt senaryosu ve son JSON/HDF5 düzenlemeleri dahil
  `test_io.py`, `test_results_storage.py`, `test_s2_anchor.py`: **22 geçti**.
  Bunlar regresyon toplamıyla örtüşür; sayıların toplamı ayrı test sayısı değildir.
- S2 + kayıt + Newton yakınsama kontrollerinin önceki hedefli koşusu: **16 geçti**.
- `ruff check src tests` ve `git diff --check`: başarılı.
- `pip wheel --no-deps --no-build-isolation .`: başarılı; yeni iki kayıt modülü
  wheel içinde doğrulandı. Bu bir Windows taşınabilir uygulama paketi değildir.
- GUI ve performans kapısı bu oturumda doğrulanmadı; Windows CI sonucu ayrıca izlenmeli.
