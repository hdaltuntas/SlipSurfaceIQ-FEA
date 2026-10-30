SlipSurfaceIQ-FEA 0.9.0 - Windows x64 portable

1. ZIP dosyasinin tamamini yazilabilir bir klasore cikarin.
2. SlipSurfaceIQ-FEA.exe dosyasini calistirin.
3. Ornekler > Dort asamali tunel ile ornegi acin ve F5 ile cozun.

Kurulum, yonetici hakki veya ayrica Python gerekmez. _internal klasorunu EXE'nin
yaninda tutun. Qt/PySide6 DLL'leri bu klasordedir ve degistirilebilir.
Ilk plastik analiz Numba derlemesi nedeniyle daha uzun surebilir.
Paket kod imzali degildir; Windows kaynak yayinlayiciyi dogrulanmis gostermez.

Birimler: kN, m, kPa. Gerilmede cekme pozitif.
Sonuclar: asal oklar / plastik noktalar; Sonuc incele > Sorgu cizgisi / Liner N-V-M.
Proje kaydi: .ssproj. CSV, VTU ve HTML disari aktarim desteklenir.

Bilinen dogrulama sinirlari ve surum durumu: RELEASE-NOTES.md
Lisans: _internal/LICENSE ve THIRD_PARTY_LICENSES/.

Otomatik paket kontrolu:
  SlipSurfaceIQ-FEA.exe --smoke-test "C:\Temp\slipsurface-check"
Cikti: smoke-result.json, tunel projesi, ekran goruntusu ve sonuc dosyalari.
