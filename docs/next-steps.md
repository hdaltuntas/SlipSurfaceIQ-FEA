# Güncel durum ve sıradaki işler

Son kullanıcı talimatı: **Faz 4 tamamlandı; hataları düzelt ve Faz 5'e geç.**
Bu talimat, önceki oturumun “Faz 4'e geçme” kararının yerini alır.
Bu depo Python `slipsurface.fe2d` / **SlipSurfaceIQ-FEA** projesidir.

## Mevcut teslim

- `main` üzerindeki Faz 4 (W1–W3, C1–C3, drenajsız A/B/C) ile açık PR #1'deki
  Faz 3 düzeltmeleri `codex/phase4-fixes-phase5` dalında birleştirildi.
- MC kabul edilebilir dönüş koruması, açık Rankine-apex seçeneği, ara yüz gömülü uç
  düzeltmeleri, karma ağ ve tanı kayıtları taşındı. Ana daldaki tam kaymalı liner ve
  Winkler palplanş testleri ayrıca korunur.
- Faz 4'ün sızma kabulü, HB akış-koni kontrolü, MCC hata türü ve girdi kontrolleri
  düzeltildi. [İnceleme kaydı](phase4-review.md).
- **Faz 5.1 başladı ve çalışıyor:** native PySide6 uygulaması, arka plan çözüm,
  proje/malzeme/aşama işlemleri, aktif sonuç görüntüsü ve dışa aktarım.
  [Çalıştırma ve kapsam](phase5-desktop.md).

## Korunan sınırlar

- S4 iş kaydı kullanıcı kararıyla kapalıdır; **RS2/PLAXIS bağımsız karşılaştırması
  ertelenmiştir**. İç Winkler/LE testleri bu dış doğrulamayı geçilmiş yapmaz.
- Eski kesmesiz P4, yerel dönüş hatası nedeniyle strict xfail olarak tutulur.
  Yerel malzeme reddi SRF göçme üst sınırı olamaz.
- Sayısal yakınsamama tek başına fiziksel göçme kanıtı değildir. Açık Rankine-apex
  akışı farklı bir bünye seçeneğidir; varsayılana gizlice eklenmez.
- Kapı 5/v1.0 tamamlanmadı; Windows portable ve PyPI yayını yapılmadı.

## Sıradaki iş

Faz 5.2: native CAD geometri düzenleyicisi, geometri → ağ bağlantısı ve yeni yük/
yapı/aşama oluşturma. Ardından özgün dört aşamalı tünelin kodsuz kurulması ve API
karşılaştırması. Ayrıntılı sıra [Faz 5 kapsamı](phase5-desktop.md) içinde.

Önceki Faz 3 ölçümleri `phase3-status.md`, `s4-comparison.md` ve `docs/data/s4/`
altında tarihsel kanıt olarak korunur; yeni tümleşik dalın test sonucu inceleme
kaydında ayrı verilir.
