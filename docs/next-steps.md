# Güncel durum ve sıradaki işler

Son kullanıcı talimatı: **Main'e gönder ve devam et.**
Bu talimat, önceki oturumun “Faz 4'e geçme” kararının yerini alır.
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
- Kapı 5/v1.0 tamamlanmadı; Windows portable ve PyPI yayını yapılmadı.

## Sıradaki iş

Sırada özgün dört aşamalı tünelin kodsuz kurulması ve API karşılaştırması var.
Ara yüz ile mevcut ağın mekanik sınır/yer değiştirme düzenleyicileri ve sonuç
grafikleri de açık. Ayrıntılı sıra [Faz 5 kapsamı](phase5-desktop.md) içinde.

Önceki Faz 3 ölçümleri `phase3-status.md`, `s4-comparison.md` ve `docs/data/s4/`
altında tarihsel kanıt olarak korunur; yeni tümleşik dalın test sonucu inceleme
kaydında ayrı verilir.
