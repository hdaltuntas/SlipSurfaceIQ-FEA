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
| S4 konsol palplanş | **Ön yapısal kontroller geçti; tam doğrulama açık** | Bağımsız Timoshenko/Winkler ve Rankine kontrolleri geçti; yerel MC dönüş korumasıyla ağ/integrasyon karşılaştırmaları yenilendi, tam doğrulama yok |
| S4 dış karşılaştırma hazırlığı | Model ve duvar alan çıktıları hazır | 0.5/0.25/0.125 m karma ağda M=163.801/167.944/169.190; adım/aşama duyarlılığı ölçüldü; uçtaki ortak zemin düğümü tanımlandı; dış referans bekleniyor |
| P4 açık Rankine-apex | **Tanımlı model kapsamı doğrulandı** | h=1.5 tam/1e-6 ve h=1.0 tam tanjant: %3 Bishop, aralık, mekanizma ve gerilme kabul edilebilirliği; model tamamlaması açıkça seçilir |
| P4 eski kesmesiz model / genel Kapı 2 kapsamı | **Açık sınır korunuyor** | Eski test strict xfail; yerel ret göçme sınırı sayılamıyor, eski korumasız FE faktörleri geri çekilmiş durumda |
| Yerel ret girdilerinin tekrarı | İki kayıt için neden ayrıştırıldı | Palplanş/P4: ψ=0, Rankine yok, deneme ortalaması apex üzerinde; 128 yerel parçayla da toplam artış tamamlanmıyor; küresel çözümsüzlük iddiası yok |
| Açık Rankine kesmesi / ortak apex | Yerel kapsam doğrulandı | Analitik gerilme/tanjant ve T3/T6/Q4/Q8 yükleme-boşaltma; açık σt=0 ile dört high palplanş koşusu tamamlandı, bağımsız S4 hâlâ açık |
| Kapı 3 | **Açık** | Tam S4 geçmeden Faz 4'e geçme |
| T3+Q4 / T6+Q8 karma ağ | Deneysel | Patch, konsol, plastik basınç, aşama, su, ara yüz ve kayıt kontrolleri geçti; nonlinear palplanş integrasyon/ağ duyarlılığı açık |

Yöntem, referans bağlantıları, sayısal hata tabloları ve sınırlar:
[phase3-verification.md](phase3-verification.md).
Proje/sonuç API'si: [project-files.md](project-files.md).
Karma ağ API'si ve aynı palplanş modeliyle karşılaştırma: [mixed-mesh.md](mixed-mesh.md).
Yerel malzeme hatası ve tanı API'si: [nonlinear-diagnostics.md](nonlinear-diagnostics.md).
Çakışan çekme/apex davranışı: [coincident-tension-cutoff.md](coincident-tension-cutoff.md).
S4 girdileri ve imzalı duvar çıktıları: [s4-comparison.md](s4-comparison.md).
Geometri, koşullanma ve Newton yöntemlerinin aynı yükte karşılaştırması:
[convergence-audit.md](convergence-audit.md).

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
- MC dönüşünün bulunamamasında `255` bayraklı elastik denemenin kabul edilmesi:
  artık yerel hata, geri alma ve adım küçültme; SRF'de bu hata göçme sayılmıyor.
- Açık `sig_t=apex` değerinin yok sayılması: ilişkili Rankine potansiyeli korunur;
  ortak köşede dokuz potansiyel kontrol edilir. Sabit köşe tanjantı tam sıfırdır.
  Tekil önceki tanjanttan boşaltma ilk tahmini elastik matrisle yapılabilir;
  sonraki Newton tanjantı varsayılan olarak değiştirilmez. İsteğe bağlı
  `apex_stiffness_ratio` yalnız iterasyon matrisine uygulanır.

## Sıradaki iş

Çekme/apex akışı `rankine_at_apex=True` ile açıkça tamamlandı; bağımsız yerel
çarpan/tanjant ve P4 karşılaştırması geçti. `apex_stiffness_ratio` ayrıca seçilen
yaklaşık Newton matrisidir; varsayılan 0 ile gerçek tanjant korunur. Eski kesmesiz
P4 doğrulaması hâlâ çözülmedi.
Zeminli palplanşta σt=0 seçimiyle high koşuları tamamlandı. Bu seçim ayrı bir akış
tanımıdır; eski kesmesiz modelin yerine sessizce konmadı. Toleranslar gevşetilmedi.
Bağımsız palplanş aracıyla aynı geometri, sınır koşulu, uç bağlantısı, zemin, su ve kazı
aşamalarını kullanan sürekli ortam FEM senaryosunu karşılaştır. Aktarım paketi ve
tekrar komutları S4 karşılaştırma belgesinde hazır; dış programın kimliği/modeli ve
sonuç dosyası henüz sağlanmadı. Maksimum moment farkını %10 içinde
ve ağ yakınsamasıyla doğrula; ardından S1–S4 ve aşama bölme değişmezliğiyle Kapı 3'ü kapat.

Kayıt dosyaları post-processing snapshot'ıdır; nonlinear solver restart biçimi değildir.
GUI ve donanıma bağlı performans kapısı bu çalışma kapsamının dışındadır.

## Son doğrulama

- S4 aktarım, S3 aşama ve S4 yapısal referans dosyalarında **14 hedefli test geçti**.
  Yeni aktarım testleri aşağıdaki önceki tam koşuya dahil değildir. Beş zeminli
  duyarlılık koşusu λ=1'e ulaştı; tümünde yerel ret sayısı 0. Dış referans bekleniyor.
- Linux / Python 3.12: benchmark dışı tam koşuda **303 geçti**, **eski kesmesiz P4 1 strict xfail**;
  bu beklenen başarısızlık geçiş olarak sayılmıyor. PyVista eksikliği
  nedeniyle görüntüleyici modülü **1 atlandı**, performans testleri **2 hariç**.
- Önceki NumPy 2.2.6 / SciPy 1.15.3 koşusunda malzeme, ortak apex, Newton tanısı,
  analitik yük yolu, Newton yakınsaması ve P4 dosyalarında **50 geçti, P4 1 strict xfail**
  (ana toplamla örtüşür).
- Ek tanı/matris/geri alma kontrolleri aynı eski NumPy/SciPy ortamında **23 geçti**
  (ana toplamla örtüşür).
- Global algoritmik tanjantın sekiz karma continuum/beam/interface durumu ile
  Newton yakınsaması aynı eski ortamda **12 geçti** (ana toplamla örtüşür).
- Açık Rankine-apex, negatif olmayan çarpanlar, yaklaşık iterasyon matrisi ve
  yükleme–boşaltma kontrolleri eski NumPy/SciPy ortamında **39 geçti**
  (ana toplamla örtüşür).
- Gerçek palplanş/P4 ret girdileri, 128 parçalı yerel tekrar, fiziksel GP eşlemesi,
  geçmiş/SRF hata verisi ve eski HDF5 varsayılanları kontrol edildi.
- Ruff, `git diff --check`, wheel derlemesi ve ayrı klasöre kurulu wheel'den API/topoloji
  import kontrolü başarılı.
- Zeminli örneğin başarısızlıkları bu test toplamlarına başarı olarak eklenmedi;
  yukarıda ve doğrulama raporunda açık sorun olarak tutuldu.
