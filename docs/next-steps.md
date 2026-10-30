# Güncel durum ve sıradaki işler

Son kullanıcı talimatı (22 Ekim 2026): **Arayüz kullanışlı değil; release hazır
değil, yayını kaldır.** Faz 5 yeniden açık; yeni release ve PyPI yayını durduruldu.
Bu depo Python `slipsurface.fe2d` / **SlipSurfaceIQ-FEA** projesidir.

## Mevcut teslim

- Faz 4 (W1–W3, C1–C3, drenajsız A/B/C) ile PR #1'deki Faz 3 düzeltmeleri ve
  Faz 5.1, PR #3 üzerinden `main` dalına birleştirildi: `de1f12a`.
- MC kabul edilebilir dönüş koruması, açık Rankine-apex seçeneği, ara yüz gömülü uç
  düzeltmeleri, karma ağ ve tanı kayıtları taşındı. Ana daldaki tam kaymalı liner ve
  Winkler palplanş testleri ayrıca korunur.
- Faz 4'ün sızma kabulü, HB akış-koni kontrolü, MCC hata türü ve girdi kontrolleri
  düzeltildi. [İnceleme kaydı](phase4-review.md).
- **Faz 5.1 başladı ve çalışıyor:** native PySide6 uygulaması, arka plan çözüm,
  proje/malzeme/aşama işlemleri, aktif sonuç görüntüsü ve dışa aktarım.
  [Çalıştırma ve kapsam](phase5-desktop.md).
- **Faz 5.2 CAD teslimi:** native bölge/boşluk/çizgi, snap, koordinat düzenleme,
  geometri undo/redo, sınırlı ve kayıpsız DXF, kenar mesnet/basınç tablosu, iptal
  edilebilir T6 ağ işçisi, çizim/proje kaydı. [Kapsam ve testler](phase5-cad.md).

- **Faz 5.3 teslimi:** altı bünye formu ve bölge atamaları, liner/bolt kurucuları,
  başlangıç durumu, yük/su ve aşama malzemesi, aşama ekleme/kopyalama/silme/sıralama.
  [Kullanım ve kabul kapsamı](phase5-model-editors.md).

## Korunan sınırlar

- S4'ün RS2/PLAXIS karşılaştırması **yoktur**. Bu bir ürün sınırıdır, ertelenmiş
  bir geçiş değildir. İç Winkler/LE testleri dış doğrulama sayılmaz.
  [Nasıl konacağı](s4-external.md).
- Eski kesmesiz P4, yerel dönüş hatası nedeniyle strict xfail olarak tutulur.
  Yerel malzeme reddi SRF göçme üst sınırı olamaz.
- Sayısal yakınsamama tek başına fiziksel göçme kanıtı değildir. Açık Rankine-apex
  akışı farklı bir bünye seçeneğidir; varsayılana gizlice eklenmez.
- Faz 5 işlevsel GUI/API kabulü geçti. Paket ve PyPI yayın durumu
  [sürüm kaydında](phase5-release.md) ayrı tutulur. S4/P4 istisnaları gizlenmez.

## Faz 5 — kullanıcı kabulü bekleniyor

Mekanik sınırlar, aşama yer değiştirmeleri, ara yüz kütüphanesi, zaman çizelgesi,
plastik GP/asal oklar, sorgu çizgisi ve liner N–V–M eklendi. Boş GUI'den dört aşamalı
tünel kabulü API ile birebir eşleşti. Portable paket kaldırıldı; wheel/sdist ve PyPI
Trusted Publisher iş akışı hazır. Linux/Windows CI 10/10 ve
bağımsız Windows portable testi geçti. Test kanıtı, yayın durumu ve korunan
istisnalar [phase5-release.md](phase5-release.md) içindedir.

Bu otomatik kontroller kullanıcı kabulünün yerine geçmez. Kullanıcının Windows
ekran görüntüsünde açık zeminde kaybolan menü/araç yazıları, zayıf kontrol
kontrastı ve model alanını daraltan panel yerleşimi görülüyor. Sıradaki işler:

1. ~~Windows açık/koyu tema ve ekran ölçeklerinde okunabilir menü/araç/sekme renkleri.~~
   Uygulandı (27 Ekim 2026): açık renk şeması sabit, Windows koyu modu kapalı,
   spin kutusu okları ve SNAP/GRID kontrastı düzeltildi, WCAG AA kontrast testi.
2. ~~Geometri, malzeme, sınır/yük, aşama ve sonuç adımlarının anlaşılır düzenlenmesi.~~
   Uygulandı: numaralı sekiz adımlı iş akışı, ✓ tamamlanma ve “sıradaki adım” ipucu.
3. ~~Model alanı, aşama listesi ve çözüm günlüğünün dengeli, ayarlanabilir yerleşimi.~~
   Uygulandı: tam genişlikte iş akışı satırı, Görünüm menüsü, kalıcı yerleşim.
4. Gerçek Windows ekranında görsel kontrol ve kullanıcı kullanılabilirlik kabulü.
   **Hâlâ açık**: Linux offscreen görüntüleri kabul yerine geçmez. Sayı üretmek için
   `scripts/phase5_cases.py` (dört durumlu tünel ve, `--sheet-pile` ile, S4 duvarı)
   log ve N–V–M yazar; bu betik Faz 5'i kapatmaz.
5. ~~Yeniden ağda malzeme, aşama, ara yüz ve yapı tanımlarının korunması.~~
   Uygulandı: [ayrıntı](integrated-modeler.md#kayıt-geri-alma-ve-yeniden-ağ).

Bu kabul alınmadan Faz 5 kapatılmayacak veya yeni release yayımlanmayacak.

Önceki Faz 3 ölçümleri `phase3-status.md`, `s4-comparison.md` ve `docs/data/s4/`
altında tarihsel kanıt olarak korunur; yeni tümleşik dalın test sonucu inceleme
kaydında ayrı verilir.
