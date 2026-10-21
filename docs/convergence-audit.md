# Yakınsama tanısı: geometri, matris ve Newton seçenekleri

Bu çalışma, palplanş örneğinde tekillik, kilitlenme, yumuşama, eleman kalitesi ve
çözüm yöntemi önerilerini ayrı kontrollerle inceler. Üretim çözücüsünün yöntemi,
toleransları veya malzeme kuralları bu tanı çalışmasıyla değiştirilmedi.

## Mevcut model ve yöntemler

- Zemin ν=0.30, c=0, φ=30°, ψ=0; ideal elastoplastik MC. İç değişkene bağlı
  dayanım düşüşü yok. Noktasal dış yük yok; mesnetler alt ve yan kenar kümelerinde.
- Kazı köşesi (0, −5), palplanş ucu (0, −10.5) ve duvar üstü (0, 0) tanı noktalarıdır.
  Bunlar bu örneğe özgü bilinen konumlardır; genel otomatik köşe tespitçisi eklenmedi.
- Varsayılan NR + line search; alternatifler `mNR`, `hybrid`, `initial` zaten vardı.
  `initial`, mevcut aşama/aktif kümenin elastik rijitliğidir; kazıdan önceki tek bir
  global matrisi tüm aktif küme değişikliklerinde sabit tutmaz.
- Yakınsamayan adım geri alınır, Δλ yarıya iner; hızlı kabulden sonra 1.5 kat büyür.
  Kalıntı duraklaması bazı adımları max_iter dolmadan kesebilir.

ν≈0.5 kaynaklı elastik kilitlenme bu model için öncelikli bulgu değildir; bu,
plastik kilitlenmenin tüm yük yollarında dışlandığı anlamına gelmez. Q4'te B-bar,
Q8'de default 2×2 ve high 3×3 integrasyon vardır. T3+Q4/T6+Q8 karma ağ, u–p
karma formülasyonu değildir; basınç için ayrı bilinmeyen henüz yoktur. Sıkışmazlık
için u–p seçimi stabil bir eleman çifti/formülasyon gerektirir
([MoFEM birincil dokümantasyonu](https://mofem.eng.gla.ac.uk/elasticity_mixed_formulation.html)).

Yumuşama parametresi bulunmaması ağ bağımlılığını kesin dışlamaz: ilişkisiz akışta
ideal plastisiteyle de yapısal yumuşama ve eliptiklik kaybı görülebilir.
[Sabet–de Borst (2019), yazar kurumu arşivi](https://eprints.whiterose.ac.uk/id/eprint/148931/).
Bu modelde akustik tensör/eliptiklik analizi yapılmadı; lokalizasyon teşhisi konmadı.

## Aynı yük düzeyinde yöntem karşılaştırması

T6+Q8, h=0.50 m, high, açık σt=0, kazı λ=0.05; aynı kuvvet/enerji toleransları,
line search ve max_iter=30. Aşağıdaki iterasyonlar yalnız kazı aşamasınındır;
reddedilen denemeleri de içerir.

| Yöntem | İterasyon | Kabul / ret adımı | Son normalize kuvvet kalıntısı |
|---|---:|---:|---:|
| NR | 6 | 1 / 0 | 1.15e-5 |
| hybrid | 6 | 1 / 0 | 3.47e-6 |
| mNR | 129 | 4 / 3 | 9.08e-5 |
| initial | 172 | 4 / 3 | 9.96e-5 |

Dört koşu da hedef λ=0.05'i tamamlar. mNR/initial için üç kesme nedeni iterasyon
sınırıdır; bu örnekte NR/hybrid daha az iterasyonla tamamladı. Bu, tam kazının
bütün yöntemlerle doğrulandığı veya NR'nin her modelde daha iyi olduğu iddiası değildir.
`test_nonlinear_diagnostics.py`, yerel hata sonrası ilk 0.5 adımın iki kez kesilip
0.125'te kabulünü ve sonraki hızlı adımın 0.1875'e büyümesini de kontrol eder.

Modified Newton bir adımın matrisiyle iterasyon yapar
([OpenSees](https://opensees.github.io/OpenSeesDocumentation/user/manual/analysis/algorithm/ModifiedNewton.html)).
Bu işlem tek başına pozitif tanımlılık veya tekillik hatalarının ortadan kalkmasını
garanti etmez. Başlangıç elastik matrisi de eksik mesnet veya kopuk DOF varsa tekildir.
İlişkisiz MC için simetrik olmayan LU zaten kullanılmaktadır; SPD şartı aranmaz.

## Elastik referansta köşe ve ağ kalitesi

Yalnız tanı için aynı geometri ve elastik sabitlerle zemin elastik yapıldı;
ara yüzün kn/ks değerleri korundu, kayma/açılma 1e20 dayanımla bastırıldı (φ=ψ=0).
Bu farklı referans modeli, gerçek MC/ara yüz çözümünün yerine kullanılmaz.
Üç ağ da aynı tam kazı λ=1 durumunda karşılaştırıldı. Gerilme ölçütü Gauss
noktalarındaki 3B tensör Frobenius normudur; kayma bileşeni normda iki kez sayılır.

| h (m) | En büyük cond₂(J) | En küçük ölçekli J | Köşeye en yakın GP (m) | Köşe r≤0.75 m tepe norm (kPa) | 0.5≤r≤1 m ağırlıklı ortalama (kPa) |
|---|---:|---:|---:|---:|---:|
| 0.50 | 4.706 | 0.4736 | 0.05036 | 349.87 | 100.96 |
| 0.25 | 4.190 | 0.4721 | 0.02333 | 485.66 | 100.75 |
| 0.125 | 4.148 | 0.4707 | 0.00996 | 907.60 | 100.95 |

Örneklenen tüm detJ değerleri pozitif. En küçük köşe açısı 28.08–28.27°,
en büyük mevcut aspect ölçütü 4.73–4.98. İncelenme sırasında J'nin şekil
koşullanması kötüleşmiyor. detJ'nin h² ile küçülmesi tek başına kötü eleman değildir.
T6/Q8 orta düğümleri J hesabına dahildir. Gauss örneklemesi eğri hücrenin her
noktasında pozitif J garantisi vermez.

GP köşeye yaklaşırken tepenin büyümesi, sabit uzaklıktaki alanın kararlı kalması
elastik köşe tekilliğiyle **uyumludur**; üç ağ bunu matematiksel olarak kanıtlamaz.
Elastik gerilme tekilliği, plastik malzemenin her durumda sonsuz gerilme üretmesi
veya Newton'un asla yakınsayamaması demek değildir
([COMSOL geometri dokümantasyonu](https://doc.comsol.com/6.3/doc/com.comsol.help.comsol/comsol_ref_geometry.23.003.html)).
Fiziksel bir köşe yarıçapı varsa hassasiyet çalışmasında kullanılmalı; sayısal
başarı elde etmek için geometri sessizce yuvarlatılmamalıdır.

## Rijitlik matrisinin koşullanması

Serbest DOF matrisi K_ff için deterministik t=1 bir-norm koşul sayısı alt tahmini,
ham ve S K_ff S (S_ii=1/sqrt(|K_ii|)) ölçeklemesiyle raporlanır. Bu tahminler
SPD testi, kesin koşul sayısı veya göçme ölçütü değildir. Ham değerler dönme ve
öteleme DOF birimlerinden etkilenir. Global NumPy RNG durumu değiştirilmez.

| Elastik referans h (m) | Ham κ₁ tahmini | Ölçekli κ₁ tahmini | LU U büyümesi |
|---|---:|---:|---:|
| 0.50 | 3.120e7 | 4.680e6 | 1.000 |
| 0.25 | 7.646e7 | 1.664e7 | 1.000 |
| 0.125 | 3.418e8 | 6.603e7 | 1.000 |

Ağ incelince global koşul sayısı artıyor; üç koşuda da LU faktörlemesi ve denge
çözümü tamamlandı. Bu yüzden artışı doğrudan sliver/zero-pivot tanısı saymıyoruz.
Kesmesiz karma/high h=0.50 m başarısız koşusunda son kabul λ=0.14826255:
son kabul edilen tanjant κ₁≈3.288e7, ölçekli≈6.195e6 ve LU başarılı.
Son ret nedeni `material_return`; `singular_tangent` değil. Bu matris **son kabul
edilen duruma** aittir; reddedilen bütün iterasyonların spektrumu incelendi denmiyor.

## Arc-length durumu ve doğrulama sınırı

Arc-length bu değişiklikte eklenmedi. Bir yük/deplasman ölçeği ve ek yol denklemiyle
limit noktasının ötesini izlemek için ayrı bir devam yöntemidir
([OpenSees](https://opensees.github.io/OpenSeesDocumentation/user/manual/analysis/integrator/ArcLength.html)).
Snap-through/snap-back göstermek için analitik bir denge eğrisinde yön seçimi,
yükün azalması, artık denge ve yol kısıtı hatası; ardından geçmiş değişkenlerinin
geri alınması ve FEM köprüsü bağımsız test edilmelidir. Arc-length yerel dönüşün
kabul edilemezliğini, köşe tekilliğini veya ağ bağımlılığını kendiliğinden gidermez.
Mevcut tanı fiziksel bir limit noktası kanıtı vermiyor. P4 ve bağımsız S4 açık kalır.

## Tekrar üretim

```bash
PYTHONPATH=src OPENBLAS_NUM_THREADS=1 python examples/diagnose_sheet_pile.py --size 0.5 --mixed --gauss-order high --soil-tension 0 --excavation-factor 0.05 --method mNR --audit --output /tmp/pile-mnr.json
PYTHONPATH=src OPENBLAS_NUM_THREADS=1 python examples/diagnose_sheet_pile.py --size 0.125 --mixed --gauss-order high --elastic-soil --elastic-interfaces --audit --output /tmp/pile-elastic.json
PYTHONPATH=src OPENBLAS_NUM_THREADS=1 python examples/diagnose_sheet_pile.py --size 0.5 --mixed --gauss-order high --audit --output /tmp/pile-failed.json
```

İlk komutta yöntem NR/hybrid/mNR/initial, ikinci komutta boyut 0.5/0.25/0.125
olarak değiştirilir. Üçüncü komutun çıkış kodu 1'dir; bu beklenen açık başarısızlık
gizlenmez. `--audit` ek LU faktörlemeleri yapar; performans zamanlaması için kullanılmaz.
Tanı verisi JSON'dadır, solver restart dosyası değildir.

## Algoritmik tanjant ve regülarizasyon önerileri

MC'nin asal gerilme dönüş/tanjantı ve Goodman dönüşü için yerel sonlu fark testleri
zaten mevcuttur. `test_newton_convergence.py` ilişkili Tresca ve ilişkisiz MC'de
asimptotik log-kalıntı eğimini >1.6, mNR için daha düşük eğimi kontrol eder.
Klasik kuadratik yakınsama düzenlilik ve tekil olmayan tanjant gerektirir;
köşe/aktif küme değişiminde her iterasyon için garanti değildir.
Algoritmik türev yerine elastik/uyumsuz tanjant kullanmak yakınsamayı bozabilir;
bu ayrım [MOOSE birincil dokümantasyonunda](https://mooseframework.inl.gov/moose/source/materials/ComputeMultipleInelasticStress.html)
da açıkça yapılır.

Ek global kontrol: `test_global_algorithmic_tangent.py` T3+Q4 ve T6+Q8,
default/high, kayma/açılma durumlarında sekiz koşu çalıştırır. MC, beam ve
iki taraflı dilatanslı ara yüz monte edilir; üç serbest DOF yönünde iki pertürbasyon
büyüklüğüyle

    K_ff v ≈ [f_int(du+h v) − f_int(du−h v)]_free / (2h)

karşılaştırılır. Bağıl hata <2e-6; elastoplastik ve ara yüz bayrakları pertürbasyonda
değişmez; giriş gerilme/geçmiş dizileri korunur. Tanjantın ilişkisiz akıştan gelen
simetrik olmayan kısmı da korunur. Bunlar sıfırdan farklı deneme artımında cebirsel
türev testleridir; model denge benchmark'ı veya olası bütün köşe yollarının kanıtı
değildir. Bayrakların aynı kalması, bütün MC alt-aktif kümelerinin aynı kaldığını
tek başına kanıtlamaz; iki h değerindeki türev uyumu bu nedenle ayrıca kontrol edilir.

**Dinamik gevşeme:** Açık zaman integrasyonu global K faktörlemesini gerektirmeyebilir;
var olmayan statik dengeyi oluşturmaz. Yapay kütle, sönüm ve kritik zaman adımı
seçimi; kuvvet kalıntısı, hız ve kinetik enerji kriterleriyle doğrulanmalıdır.
Kritik sönüm bütün modlar için tek bir sayı değildir. Süren göçmede kuvvet kalıntısı
ve hareket sönmeyebilir; [Itasca'nın denge dokümantasyonu](https://docs.itascacg.com/itasca900/flac3d/docproject/source/modeling/problemsolving/equilibrium.html)
bu ayrımı tartışır. Henüz eklenmedi.

**Perzyna / Duvaut–Lions:** Ayrı, zamana bağlı bir malzeme tanımı gerektirir.
Kendi gerilme güncellemesi ve algoritmik türevi türetilmeli; viskozite/gevşeme
zamanı, Δt ve yükleme hızı duyarlılığı, disipasyon ve uygun hızdan bağımsız referans
kontrol edilmelidir. Tek bir küçük viskozite koşusu η→0 limitinin doğrulanması
değildir; limitin ağdan bağımsız/tekil olmayan bir çözüm verdiği ayrıca gösterilmelidir.
Yeni modelde izin verilen overstress, mevcut hızdan bağımsız modelin `255` dönüş
hatasını kabul etmekle aynı şey değildir.
[Wang–Sluys–de Borst (1997), birincil kaynak](https://pure.tue.nl/ws/portalfiles/portal/4389528/605201.pdf).
Viskoplastik model bu değişiklikte eklenmedi; üretim davranışına yapay viskozite konmadı.

**Non-local / gradient / Cosserat:** İçsel uzunluk ve malzeme kalibrasyonu gerektirir;
çıktı plastik deformasyonunu sonradan komşu GP'lerle ortalamak yeterli değildir.
Non-local bir iç değişkenin türevi komşu eleman DOF'larını da bağlar; mevcut yerel
CSR deseni/assembly buna göre genişletilmelidir. Sınır ağırlıkları ve h/içsel-uzunluk
duyarlılığı doğrulanmalıdır. Cosserat ayrıca bağımsız dönme ve çift-gerilme içerir;
skaler GP ortalamasıyla aynı formülasyon değildir. Bu yöntemler lokalizasyon/ağ
nesnelliğini hedefler; u–p hacimsel kilitlenme çözümünden ayrı bir konudur.
İdeal, ilişkisiz plastisitede de regülarizasyon ihtiyacına ilişkin birincil örnek:
[Sabet–de Borst (2019)](https://eprints.whiterose.ac.uk/id/eprint/148931/).
Bu formülasyonlar henüz uygulanmadı.

Öncelik: doğrulanmış yerel güncelleme/tanjant ve bağımsız P4/S4 referansı korunarak,
denge yolu izleme ile hız/uzunluk içeren yeni malzeme modelleri ayrı seçenekler olarak
geliştirilmeli. Birden çok yapay mekanizmayı aynı anda açıp yakınsamayı başarı
saymak yerine her yeni seçenek kendi denge, zaman ve ağ sınamalarıyla doğrulanmalı.
