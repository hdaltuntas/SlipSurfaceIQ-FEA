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

- S4 iş kaydı kullanıcı kararıyla kapalıdır; **RS2/PLAXIS bağımsız karşılaştırması
  ertelenmiştir**. İç Winkler/LE testleri bu dış doğrulamayı geçilmiş yapmaz.
- Eski kesmesiz P4, yerel dönüş hatası nedeniyle strict xfail olarak tutulur.
  Yerel malzeme reddi SRF göçme üst sınırı olamaz.
- Sayısal yakınsamama tek başına fiziksel göçme kanıtı değildir. Açık Rankine-apex
  akışı farklı bir bünye seçeneğidir; varsayılana gizlice eklenmez.
- Faz 5 işlevsel GUI/API kabulü geçti. Paket ve PyPI yayın durumu
  [sürüm kaydında](phase5-release.md) ayrı tutulur. S4/P4 istisnaları gizlenmez.

## Faz 5 — kullanıcı kabulü bekleniyor

Mekanik sınırlar, aşama yer değiştirmeleri, ara yüz kütüphanesi, zaman çizelgesi,
plastik GP/asal oklar, sorgu çizgisi ve liner N–V–M eklendi. Boş GUI'den dört aşamalı
tünel kabulü API ile birebir eşleşti. Windows portable ve temiz makine smoke CI'sı,
wheel/sdist ve PyPI Trusted Publisher iş akışı hazır. Linux/Windows CI 10/10 ve
bağımsız Windows portable testi geçti. Test kanıtı, yayın durumu ve korunan
istisnalar [phase5-release.md](phase5-release.md) içindedir.

Bu otomatik kontroller kullanıcı kabulünün yerine geçmez. Kullanıcının Windows
ekran görüntüsünde açık zeminde kaybolan menü/araç yazıları, zayıf kontrol
kontrastı ve model alanını daraltan panel yerleşimi görülüyor. Sıradaki işler:

1. Windows açık/koyu tema ve ekran ölçeklerinde okunabilir menü/araç/sekme renkleri.
2. Geometri, malzeme, sınır/yük, aşama ve sonuç adımlarının anlaşılır düzenlenmesi.
3. Model alanı, aşama listesi ve çözüm günlüğünün dengeli, ayarlanabilir yerleşimi.
4. Gerçek Windows ekranında görsel kontrol ve kullanıcı kullanılabilirlik kabulü.

Bu kabul alınmadan Faz 5 kapatılmayacak veya yeni release yayımlanmayacak.

Önceki Faz 3 ölçümleri `phase3-status.md`, `s4-comparison.md` ve `docs/data/s4/`
altında tarihsel kanıt olarak korunur; yeni tümleşik dalın test sonucu inceleme
kaydında ayrı verilir.
