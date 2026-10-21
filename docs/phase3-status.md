# Faz 3 — güncel durum

Referans: *SlipSurface 2D — Teknik Mimari ve Yol Haritası*, Faz 3 ve Ek A.

| Madde / doğrulama | Durum | Kanıt / kalan iş |
|---|---|---|
| Aktif küme, kazı, load split, aktivasyon ve u_ref | Mevcut, S3 doğrulandı | Tek/çok aşama, üç gevşeme oranı, geri dolgu |
| S1 liner'lı elastik tünel | No-slip kapsamı doğrulandı | Dört ağ/sınır denemesi, imzalı N/M alanları %5 içinde |
| S2 ön germeli ankraj | Doğrulandı | Üç ankraj aralığında bağımsız seri yay dengesi |
| Goodman ara yüzü | Tanımlı kapsamda doğrulandı | Akma/çekme/birleşik dönüş, tanjant, iki taraflı düğüm ayrılması, su kuvveti ve durum korunması |
| Aşama bazlı piezometrik su, malzeme değişimi | Mevcut | Su ve statik birim testleri |
| HDF5 ve .ssproj | Mevcut, kayıt testleri var | Aşama bazlı okuma, karma eleman/plastik çıktı gidiş-dönüşü, atomik kayıt |
| S4 konsol palplanş | **Ön yapısal kontroller geçti; tam doğrulama açık** | Bağımsız Timoshenko/Winkler ve idealize Rankine diyagramı geçti; zeminli örnek 0.50 m ağda çözülüyor, 0.25 m ağda λ=0.8938’de yakınsamıyor; bağımsız araç karşılaştırması eksik |
| Kapı 3 | **Açık** | Tam S4 geçmeden Faz 4'e geçme |
| T3+Q4 / T6+Q8 karma ağ | Deneysel | Patch, konsol, plastik basınç, aşama, su, ara yüz ve kayıt kontrolleri geçti; nonlinear palplanş integrasyon/ağ duyarlılığı açık |

Yöntem, referans bağlantıları, sayısal hata tabloları ve sınırlar:
[phase3-verification.md](phase3-verification.md).
Proje/sonuç API'si: [project-files.md](project-files.md).
Karma ağ API'si ve aynı palplanş modeliyle karşılaştırma: [mixed-mesh.md](mixed-mesh.md).

## Düzeltilen hatalar

- Ön germenin tutulduğu yüksüz aşamada makine hassasiyetindeki kalıntının sahte
  yakınsamamaya yol açması: kuvvet ölçeğine bağlı yuvarlama eşiği.
- Karma VTU'da plastik hücre verisinin uzunluğunun yapısal hücrelerle uyuşmaması:
  tüm dışa aktarılan hücreleri kapsayan dizi ve veri uzunluğu kontrolleri.
- Ara yüzde dilatanslı kayma ile çekme kesmesinin sıralı kırpılması: kabul edilebilirlik
  ve plastik çarpan işaretini birlikte kontrol eden aktif küme dönüşü ve tam türevi.
- Python 3.10 CI'daki güvenilmez SLSQP referansı: başarısı/kısıtları kontrol edilen,
  doğrusal kısıtlı bağımsız QP. Üretim malzeme toleransları değiştirilmedi.
- Ağ katmanının sınır düğümleri için post-processing katmanına ters bağımlılığı:
  ortak topoloji işlevi L2'ye taşındı; mevcut post-processing import'u korundu.

- Plastik aşamalarda blok adı aynı kalırken aktif eleman tanjantlarının yanlış yeniden
  kullanılması: tam sistem anahtarına bağlı önbellek.
- Ayrı bir eleman bloğunun bütünüyle kaldırılmasında boş DOF dizisinin yeniden
  şekillendirilmesi ve tanjant anahtarının bulunamaması: boş blok desteği düzeltildi.

## Sıradaki iş

Önce ince ağ ve integrasyon duyarlılığının nedenini bağımsız kontrollerle ayır:
default ile 0.25 m T6 λ=0.8938, T6+Q8 λ=0.9961'de duruyor;
high ile karma 0.50 m ağ da kazıyı tamamlamıyor. Karma ağda daha yüksek λ,
tek başına doğrulama veya güvenilirlik kanıtı değildir.
Ardından bağımsız palplanş aracıyla aynı geometri, sınır koşulu, zemin, su ve kazı aşamalarını
kullanan sürekli ortam FEM senaryosunu karşılaştır. Maksimum moment farkını %10 içinde
ve ağ yakınsamasıyla doğrula; ardından S1–S4 ve aşama bölme değişmezliğiyle Kapı 3'ü kapat.

Kayıt dosyaları post-processing snapshot'ıdır; nonlinear solver restart biçimi değildir.
GUI ve donanıma bağlı performans kapısı bu çalışma kapsamının dışındadır.

## Son doğrulama

- Linux / Python 3.12: benchmark dışı tam koşuda **220 geçti**, PyVista eksikliği
  nedeniyle görüntüleyici modülü **1 atlandı**, performans testleri **2 hariç**.
- NumPy 2.2.6 / SciPy 1.15.3 ile malzeme, ara yüz, S1, S4 ön kontrolleri ve değişen
  aktif kümelerin hedefli koşusunda **46 geçti** (ana toplamla örtüşür).
- Aynı NumPy/SciPy sürümleriyle karma ağ, karma patch/aşama ve E2 konsol
  dosyalarında **39 geçti** (ana toplamla örtüşür).
- Ruff, `git diff --check`, wheel derlemesi ve ayrı klasöre kurulu wheel'den API/topoloji
  import kontrolü başarılı.
- Zeminli örneğin ince ağdaki başarısızlığı bu test toplamlarına başarı olarak eklenmedi;
  yukarıda ve doğrulama raporunda açık sorun olarak tutuldu.
