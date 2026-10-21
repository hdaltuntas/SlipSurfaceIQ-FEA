# Çalışma devri ve ileride yapılacaklar

Son güncelleme: **21 Ekim 2026**. Depo: **SlipSurfaceIQ-FEA**, Python
`slipsurface.fe2d` çekirdeği. Çalışma PR #1 / `codex/phase3-project-results`
dalındadır; main'e birleştirme veya sürüm yayımlama bu kaydın kapsamında değildir.

## Kullanıcının son kararı

- S4 iş kaydı kapatıldı. RS2/PLAXIS gibi bağımsız bir programla eşdeğer model
  karşılaştırması sonraya ertelendi; doğrulama testi geçmiş sayılmadı.
- **Faz 4'e geçilmeyecek.** Bu oturum mevcut düzeltmeler, son sonuçlar ve gelecek
  işlerin kaydıyla bırakıldı. Faz 4 deneme uygulaması bu dala dahil edilmedi.
- Aşağıdaki plan gelecekteki çalışmanın sırasıdır; uygulanmış özellik listesi değildir.

## Mevcut çalışan kapsam

| Konu | Kaydedilen durum |
|---|---|
| MC yerel dönüş | Başarısız dönüş hata verir; geçersiz elastik deneme kabul edilmez, adım geri alınır |
| Apex | Açık `rankine_at_apex=True` seçimi ilişkili Rankine akışını ekler; varsayılan kesmesiz model korunur |
| Newton | Gerçek algoritmik tanjant varsayılandır; `apex_stiffness_ratio` isteğe bağlı yaklaşık iterasyon matrisi |
| P4 | Açık Rankine-apex modeli %3 Bishop ölçütünü geçti; eski kesmesiz model strict xfail |
| İki taraflı ara yüz | Gömülü uç her iki tarafta ortak; ekleme sırası sonucu değiştirmiyor |
| S4 iç koşuları | Üç ağ, yarı adım, bölünmüş serbest bırakma ve ters ekleme sırası: altısı da λ=1, yerel ret 0 |
| Son ağ inceltmesi | h=0.25→0.125 m: tepe moment farkı %0.508, duvar ux farkı %1.8238 |
| Kalıcı çıktılar | `docs/data/s4/`: fiziksel girdiler, altı koşunun CSV'leri, sayısal özet, model ve profil görselleri |
| Testler | Benchmark dışı tam koşu: 318 geçti, 1 strict xfail, PyVista yokluğuyla 1 modül atlandı, 2 benchmark hariç |

Üç ağda maksimum moment sırasıyla 163.729759 / 168.058175 / 168.911600 kNm/m;
duvar üstü ux 31.624986 / 32.793317 / 33.391392 mm. Sonuçlar high integrasyon,
tam NR ve `apex_stiffness_ratio=0` içindir. Uzak alan ağ boyutu sabittir; genel
ağ bağımsızlığı veya dış doğrulama olarak yorumlanmaz.

[Ayrıntılı durum](phase3-status.md) · [S4 modeli ve tekrar komutları](s4-comparison.md)
· [Apex modeli ve sınırları](coincident-tension-cutoff.md).

## Ertelenen doğrulama ve bakım işleri

1. **Bağımsız S4 karşılaştırması:** aynı geometri, kazı aşamaları, sınırlar,
   iki tarafta kapalı gömülü uç, malzeme/çekme akışı ve ara yüz rijitlikleriyle
   dış model kur. Program/sürüm, model dosyası ve yakınsama kaydıyla son aşamanın
   moment–derinlik ve ux–derinlik çıktısını sakla. İşaretleri ortak eksene çevir;
   maksimum moment farkını dış referansa bölerek %10 ölçütünü değerlendir.
2. **Eski kesmesiz P4:** mevcut yerel dönüş hatasını fiziksel göçme sayma.
   Bu modelin yük yolunu ele alacak ayrı çalışma gerekirse, yeni akış modeli
   seçimini açıkça belirt; mevcut strict xfail'i kanıt olmadan kaldırma.
3. **BLAS tanıları:** başarılı tam test koşusunun sonunda gelen `DTRSV`/`DGEMV`
   parametre iletilerini hangi tekil sistem denemesinin ürettiğini ayrıştır.
   İletiler önceki apex tam koşularında da mevcut; test sonucu ile aynı şey değildir.
4. **Görüntüleme/performans:** PyVista bulunan ortamda atlanan görüntüleyici
   testini çalıştır; donanıma bağlı benchmark kapısını ayrı ölç. Bu oturumun
   318 test sonucu bu iki kapsamı doğrulamış sayılmaz.

## Faz 4 için plan — henüz başlanmadı

Özgün yol haritasındaki sıra: **sızma eşlemesi ve ileri bünye modelleri**.

| Sıra | Yapılacak iş | İlk doğrulama / teslim |
|---|---|---|
| 4.1 | Kararlı doymuş Darcy sızması; kx/ky, hidrolik yük ve debi sınırları | Analitik yük alanı, debi dengesi, katmanlı/anizotrop zemin ve karma ağ kontrolleri |
| 4.2 | Doymamış iletkenlik, van Genuchten, Picard ve sızma yüzeyi | Kütle dengesi, iterasyon/adım tanısı, sızma yüzeyi etkin kümesi |
| 4.3 | Sızma → boşluk suyu basıncı → efektif gerilme eşlemesi | Aşama bazlı aktarım, kazı/aktivasyon, su yükleri ve kayıt gidiş-dönüşü |
| 4.4 | Genelleştirilmiş Hoek–Brown (GSI, mi, D) | Yerel gerilme dönüşü, tutarlı tanjant ve bağımsız referans |
| 4.5 | Modified Cam-Clay | İzotropik/üç eksenli yollar, iç değişkenler ve tutarlı tanjant |
| 4.6 | Drenajsız A/B/C ve aşırı boşluk suyu basıncı | Her yöntemin varsayımı, çıktısı ve bağımsız kontrolü |

`HeadBC`, `FluxBC`, `WaterCondition(mode="seepage")` ve malzemenin `k_sat`
alanı mevcut veri tanımlarıdır. **Kararlı sızma çözücüsü henüz uygulanmadı**;
mekanik model `seepage` aşamasını `NotImplementedError` ile reddeder.
Mevcut piyezometrik çizgi seçimi bir sızma çözümü değildir. T3+Q4/T6+Q8 karma
ağ da u–p karışık formülasyonu değildir.

Yol haritasındaki Kapı 4 hedefleri: W1 debi <%2, W2 debi <%3, W3 basınç farkı
<10⁻⁸; C1 q–εa <%1, C2 p′–q <%2, C3 çeper deplasmanı <%3. Uygulamaya başlarken
her testin özgün sınır-değer problemi, normalizasyonu ve referans girdisi test
dosyasında açıkça tanımlanmalı; yalnız temel Darcy testleriyle Kapı 4 kapatılmamalı.

Arc-length, dinamik gevşeme, viskoplastik ve non-local/gradient/Cosserat yöntemleri
uygulanmadı. Mevcut yakınsama düzeltmeleri bu yöntemlerin eklendiği anlamına gelmez.
