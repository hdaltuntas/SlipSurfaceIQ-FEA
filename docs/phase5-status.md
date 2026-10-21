# Faz 5 — masaüstü arayüz başlangıcı

Temel: `baeac4c` (Faz 4 tamamlanmış `main`). Faz 3 ve Faz 4 mevcut kodu üzerinden
ilerlenir; eski PR #1 dalındaki farklı uygulamalar bu dala taşınmaz.

## İncelemede düzeltilen hatalar

* **Faz 3 / kazı sonrası sonuçlar:** SPR ve nodal ortalama artık ilgili aşamanın
  `active` maskesini kullanır. Devre dışı elemanların geçmiş Gauss verileri aktif
  düğümlerin gerilmelerini ve plastik şekil değiştirme ortalamalarını kirletmez.
  PyVista ve VTU yalnızca aktif süreklilik elemanlarını gösterir/yazar. Kullanılmayan
  düğümlerde NaN korunur; sıfır deplasman veya gerilme uydurulmaz. Tamamen boş aşama
  da desteklenir. Kaydedilmiş geçmiş diziler değiştirilmez.
* **Faz 3 / proje bütünlüğü:** `.ssproj` kaydında farklı bir modelin sonuçları artık
  yalnızca eşit düğüm sayısı nedeniyle kabul edilmez. Ayrı model nesnelerinin tam
  serileştirilmiş tanımları karşılaştırılır; aynı modelin eşdeğer kopyası kabul edilir.
  Çözülen modelin sonradan yerinde değiştirilmesini tespit eden bir sonuç parmak izi
  henüz yoktur; sonuç alındıktan sonra model değiştirilmemelidir.
* **Faz 4:** W1–W3, C1–C3 ve drenajsız analiz regresyonları bu dalın tam test
  çalıştırmasına dahildir. Bu incelemede bünye algoritmalarına yeni yama eklenmedi.
  `verification.md` içindeki fiziksel/sayısal sınırlamalar geçerlidir.

## Tamamlanan ilk Faz 5 parçası

```bash
python -m pip install -e '.[desktop]'
slipsurface model.ssproj
# Alternatif:
python -m slipsurface.fe2d.gui.desktop model.ssproj
```

* PySide6 ana pencere; mevcut `.ssproj` açma ve farklı adla kaydetme.
* Aynı `api.run` üzerinden QThread içinde çözüm; işlem sırasında açma/kaydetme ve
  ikinci çözüm engellenir. Hata gösterilir, kontroller geri açılır. Çalışan çözücü
  zorla durdurulmaz; pencere kapanışı çözüm bitene kadar engellenir.
* Aşama, gerilme/deplasman alanı ve deformasyon katsayısı seçimi; QGraphicsView
  üzerinde aktif süreklilik ağı. Renkler **eleman ortalaması önizlemesidir**;
  dışa aktarılan VTU düğüm değerlerini korur. Çekme pozitif, birimler m/kPa.
* Seçili aşamayı VTU dışa aktarma. Betik API'siyle yer değiştirme/gerilme eşitliği,
  başarısız çözümden toparlanma, ilk durum ve boş kazı görünümü Qt testlerinde denetlenir.
* Qt testleri ayrı CI işinde çalışır; sayısal çekirdek Qt gerektirmez.

## Sıradaki işler — Kapı 5 henüz kapanmadı

1. QGraphicsView CAD düzenleme: snap, poligon/çizgi, DXF; geri al/yinele ve doğrulama.
2. Malzeme/yapı kütüphanesi ve aşama zaman çizelgesi; kodsuz model tanımlama.
3. Adım/iterasyon ilerleme olayları, yakınsama grafiği ve güvenli iptal. Mevcut
   ilerleme çubuğu yalnızca meşgul göstergesidir; ilerleme yüzdesi vermez.
4. Yapı çizimi, liner N–V–M, plastik noktalar, asal gerilme okları, sorgu çizgileri;
   Faz 4 su yükü/aşırı boşluk suyu alanlarının GUI seçicisine eklenmesi.
5. HTML rapor, CSV, Windows taşınabilir paket ve PyPI sürüm hazırlığı.
6. Kapı 5: dört aşamalı tüneli GUI'den kodsuz kurup çözme, betik API'siyle birebir
   karşılaştırma ve Ek A testlerinin CI doğrulaması. Bu ilk parça v1.0 değildir.

## Bu değişikliğin doğrulaması (2026-10-21)

Python 3.12 / Linux üzerinde Qt offscreen ve gerçek PyVista PNG çizimi dahil:

```bash
QT_QPA_PLATFORM=offscreen SLIPSURFACE_RENDER_TESTS=1 PYTHONPATH=src \
OPENBLAS_NUM_THREADS=1 python -m pytest -q -m 'not benchmark'
# 212 passed, 2 deselected (94.90 s)
python -m ruff check src tests
# All checks passed
```

İki performans benchmark'ı bu koşuya dahil edilmedi. Yeni desktop CI işi Qt ve
PyVista regresyonlarını ayrıca çalıştırır. Geçen testler desteklenen doğrulama
modellerini kapsar; tüm geometrilerde yakınsama garantisi değildir.
