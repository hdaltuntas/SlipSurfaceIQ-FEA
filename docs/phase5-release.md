# SlipSurfaceIQ-FEA 1.0.0 — Faz 5 sürüm adayı

Native PySide6 masaüstü: CAD/DXF → T6 ağ; malzeme/bölge, liner/bolt/ara yüz,
mekanik sınır ve aşama su/yük/yer değiştirme düzenleyicileri; aşama zaman çizelgesi;
arka plan çözüm/iptal; kontur, deforme ağ, plastik GP ve düzlem içi asal oklar;
sorgu çizgileri ve yönü tanımlı liner N–V–M grafikleri; proje/CSV/VTU/HTML kaydı.

![Dört aşamalı tünel](images/phase5-tunnel.png)

![Liner moment grafiği](images/phase5-liner.png)

## Kapı 5 kabulü

`test_phase5_acceptance.py` boş CAD formundan 16 kenarlı dairesel tünel yaklaşımı,
çevre kaya bölgesi ve taç bolt çizgisini oluşturur. Gerilme başlangıcı → %40
gevşeme → shotcrete ile toplam %70 → bolt ve kalan kazının tamamlanması.
GUI işçisi ve bağımsız Domain/API modelinin bütün aşamalarında u, gerilme,
liner/bolt kuvveti, plastik bayrak, su ve aktivasyon dizileri birebir eşleşir.
Kazı boşluğundaki sorgular NaN kalır; kaydedilen proje yeniden açılır.

Bu bir GUI/API eşitlik kabulüdür; bağımsız tünel doğrulamasının yerine geçmez.
S1–S3 ve diğer mevcut analitik doğrulamalar ayrı CI testleridir.

Yerel tam regresyon: **472 geçti, 1 strict xfail, 2 benchmark hariç** (108.27 s).
Kaynak smoke kontrolü dört durum, kayıt, DXF, dışa aktarım ve Numba ile başarılı.

## Sayısal ve kullanım sınırları

- Kullanıcının kararıyla S4 RS2/PLAXIS dış karşılaştırması ertelenmiştir.
- Eski kesmesiz P4 strict xfail olarak korunur. Yerel bünye dönüş hatası fiziksel
  göçme kanıtı veya SRF üst sınırı sayılmaz. Açık Rankine-apex akışı ayrı seçenektir.
- Çizgisel 2B DXF desteği vardır; DWG ve eğri/blok DXF bu sürüme dahil değildir.
- CAD yeniden ağlaması yeni model oluşturur; mevcut FE atamalarını otomatik taşımaz.
- Sonuç konturları eleman ortalamasıdır. Sorgu çizgisi gerilmeleri eleman içinde GP
  ekstrapolasyonuyla hesaplanır; malzeme sınırında taraf için bölge filtresi vardır.
- Asal oklar düzlem içi iki gerilmeyi gösterir; szz ile sıralanmış 3B asal değerler
  kontur alanlarında ayrıdır. Plastik nokta/ok sayısı büyük modelde seyreltilirse
  ekranda gösterilir. Sorgu çizgisi deforme olmamış koordinatları kullanır.
- Liner yerel x yol yönündedir, yerel y 90° saat yönü tersidir. N çekme pozitiftir.
  N/V/M başlangıçta eksi yerel düğüm etkisi, bitişte artı yerel etkidir. Yol tersine
  dönen elemanda uç sırası ters çevrilir ve M işareti değişir. Ortak uçlar ortalanmaz.
- Ara yüz silme çakışan eş düğümleri birleştirir; başka bir ara yüzü tamamen
  kapatacak silme reddedilir. Kullanılmayan düğüm kimlikleri korunur.
- Liner plastisitesi, dinamik analiz ve tam konsolidasyon v1 kapsamı dışındadır.

## Paket ve yayın

`portable.yml` onedir Windows x64 paketi, wheel/sdist, SHA256 ve bağımlılık lisans
arşivi üretir. Ayrı Windows makinesi, kaynak kod ve Python kurulumu yapmadan,
Python yollarını ortamdan kaldırıp ZIP içindeki EXE'yi test eder; dört durumlu
çözüm, kayıt, DXF, grafikler ve plastik bünye derlemesini kontrol eder. CI kanıtı
ayrı artifact olarak saklanır. Paket imzasızdır.

PyPI iş akışı `publish.yml`, GitHub release yayımlandığında veya elle çalıştırıldığında
OIDC Trusted Publishing kullanır. PyPI tarafında şu yayıncı tanımlanmış olmalıdır:
`hdaltuntas / SlipSurfaceIQ-FEA / publish.yml / pypi`, proje `slipsurface-fe2d`.
Gerçek yayın ve paket test sonuçları tamamlanınca bu kayıt kesinleştirilir.
