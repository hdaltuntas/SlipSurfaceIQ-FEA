SlipSurfaceIQ-FEA 0.9.0 - Ubuntu / Linux x64 portable

1. Tar dosyasinin tamamini yazilabilir bir klasore cikarin:
     tar -xzf SlipSurfaceIQ-FEA-linux-x64.tar.gz
2. SlipSurfaceIQ-FEA dosyasini calistirin:
     ./SlipSurfaceIQ-FEA/SlipSurfaceIQ-FEA
3. Ornekler > Dort asamali tunel ile ornegi acin ve F5 ile cozun.

Kurulum, yonetici hakki veya ayrica Python gerekmez. _internal klasorunu
programin yaninda tutun. Qt kutuphaneleri bu klasordedir.
Ilk plastik analiz Numba derlemesi nedeniyle daha uzun surebilir.
Masaustu oturumu yoksa kontrol:
     QT_QPA_PLATFORM=offscreen ./SlipSurfaceIQ-FEA/SlipSurfaceIQ-FEA --smoke-test /tmp/ss-check

Sistemde su paylasilan kutuphaneler gerekir (Ubuntu masaustu kurulumunda vardir):
libglib2.0, libegl, libgl, libxkbcommon, libdbus, libfontconfig, libxcb-cursor.

Birimler: kN, m, kPa. Gerilmede cekme pozitif.
Sonuclar: kaplama, kazik veya ankraja tiklayinca N, V ve M birlikte yazilir.
Proje kaydi: .ssproj. CSV, VTU ve HTML disari aktarim desteklenir.

Lisans: _internal/LICENSE ve THIRD_PARTY_LICENSES/.
Surum notu: RELEASE-NOTES.md
