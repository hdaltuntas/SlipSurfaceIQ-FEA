# Yerel malzeme hatası ve Newton tanısı

Mohr–Coulomb dönüşü kabul edilebilir bir aktif küme bulamadığında eski kod
elastik deneme gerilmesini `255` bayrağıyla geri veriyordu. Global kuvvet/enerji
kontrolü bu gerilmenin akma yüzeyinde olup olmadığını kontrol etmediğinden böyle
bir durum kabul edilebiliyordu. Bu davranış düzeltildi: tüm malzeme batch'i
`MaterialIntegrationError` ile reddedilir; giriş gerilme/geçmiş dizileri değişmez.
Newton bu denemeyi kabul etmez, son kabul edilen durumu korur ve adımı küçültür.
Minimum adıma ulaşıldığında `NonConvergence.history` tanı kaydını içerir.

## Yerel girdilerin bağımsız tekrarı

`MaterialIntegrationError.details` etkin malzeme parametrelerini, başarısız GP
sayısını ve ilk en çok sekiz noktanın `sig_n`, `deps`, `q_n`, deneme gerilmesi,
ortalama gerilme ve akma değerini taşır. Statik çözücü blok adı, blok içi eleman
indeksi, sıfır tabanlı GP indeksi ve fiziksel koordinat ekler. Newton'un reddedilen
`StepRecord.material_failure` kaydı bu veriyi ilgili λ/iterasyonla ilişkilendirir;
SRF istisnası da son yerel kaydı korur. Kabul edilen adımların alanı `null` olur.
Eski geçmiş dosyaları aynı `null` varsayılanıyla okunur.

Tanınan özel neden `zero_dilation_trial_above_apex`'tir. Gerilme işareti çekmede
pozitif olmak üzere, ψ=0 MC potansiyellerinin izi sıfırdır. İzotropik elastisiteyle
plastik düzeltme ortalama gerilmeyi değiştirmez. Öte yandan sıralı asal gerilmelerde
MC kabul edilebilirliği

\[
k\sigma_1-\sigma_3\le s_c,\quad \sigma_3\le\sigma_1
\quad\Rightarrow\quad
\bar\sigma\le\sigma_1\le\frac{s_c}{k-1}=c\cot\phi
\]

gerektirir (φ>0). Aktif Rankine potansiyeli yokken deneme ortalamasının bu apex'i
ölçeğe bağlı 1e-10 tanı toleransından fazla aşması, bu deneme artışı için seçilen
MC potansiyelleriyle kabul edilebilir dönüş bulunamayacağını gösterir. Üretim
akma/aktif-küme toleransları değiştirilmedi. Diğer retler `active_set_not_found`
olarak kalır; bunlara çözümsüzlük veya drift teşhisi otomatik konmaz.

Kaydedilmiş gerçek girdiler (`tests/verification/data/material_return_failures.json`):

| Koşu / son yerel ret | Blok / eleman / GP | Konum [m] | Deneme ortalaması [kPa] | Apex [kPa] |
|---|---|---|---:|---:|
| Palplanş h=0.5, karma/high, kesmesiz | soil:quad / 226 / 5 | (−0.235912, −0.028175) | 0.000927848 | 0 |
| P4, SRF F=1.5625, kesmesiz | soil / 433 / 2 | (11.406700, 3.801769) | 41.093091 | 27.474774 |

Palplanşta 15 başarısız yerel değerlendirmede toplam 21 GP ret kaydı var (tekrar
ziyaretler dahil); tümü bu özel koşulu sağlar. Her batch en çok beş nokta
reddettiğinden bu koşuda sekiz nokta sınırı veri kırpmadı. İlk ret beş Q8 noktasını,
son ret yukarıdaki tek noktayı içerir. Son ret denemesi λ=0.148418975,
iterasyon=1; son kabul edilen λ=0.148262548'dir. Son nokta kazı köşesinde değildir.
Farklı modellerde ilk sekiz örnek bütün başarısız noktaları temsil etmeyebilir.

Küresel çözücü olmadan, aynı başlangıç gerilmesi ve toplam deformasyon artışıyla
eşit yerel alt adımların tamamlanabilen sayısı:

| Toplam alt adım | Palplanşta tamamlanan | P4'te tamamlanan |
|---:|---:|---:|
| 1 | 0 | 0 |
| 2 | 0 | 1 |
| 8 | 1 | 4 |
| 32 | 5 | 19 |
| 128 | 21 | 76 |

Hiçbiri toplam artışı tamamlamaz. Birim testleri ilk gerilmenin kabul
edilebilirliğini, doğrudan/128 parçalı reddi ve kabul edilmiş alt adımların iz
dengesini kontrol eder. Bu, **kaydedilmiş deneme artışları** için sonuçtur;
küresel denge çözümünün bulunmadığını veya malzeme modelinin tüm yük yollarında
başarısız olduğunu göstermez. Açık Rankine akışı, farklı ψ veya yeni apex kuralı
ayrı bir bünye tanımıdır; tanı aracı bunları kendiliğinden eklemez.

```bash
PYTHONPATH=src OPENBLAS_NUM_THREADS=1 python examples/replay_material_failure.py /tmp/pile-diagnostic.json --which last
```

Araç ilk/son kaydın her noktasını 1/2/8/32/128 parçayla tekrarlar; yeni bir üretim
integratörü veya tutarlı tanjant sağlamaz.

Bağımsız küçük yeniden üretim: E=30000 kPa, ν=0.3, c=0, φ=30°, ψ=0 ve sıfır
başlangıç gerilmesi altında üç normal bileşende 1e-5 çekme deformasyonu eski kodda
σ=(0.75, 0.75, 0.75, 0) kPa ve f_MC=1.5 kPa veriyordu. Bu, kabul edilebilir bir
dönüş değildir. ψ=0 MC kayma potansiyellerinin normal bileşenleri toplamı sıfırdır;
bu özel hidrostatik çekme denemesini apex'e taşımak için gereken hacimsel düzeltmeyi
sağlayamaz. Kod artık bu yerel başarısızlığı açıkça bildirir. Fiziksel malzeme modeli
değiştirilmedi: yapay kohezyon, dilatans veya yeni çekme/apex kuralı eklenmedi.

## Palplanşta gözlem

Koruma öncesi h=0.50 m, karma T6+Q8, high integrasyon koşusunda son kabul edilen
λ=0.19426956 durumunda **6 GP `255`** taşıyordu. Toplam 406 gerilme değerlendirmesinde
bu başarısızlık gözlendi (tek değerlendirmede en çok 8 GP). Kalıntı sıçramalarının
bir kaynağı böylece doğrudan belirlendi; bunun bütün ağ duyarlılığını açıkladığı veya
fiziksel göçme olduğu sonucuna varılmadı.

Koruma ile aynı koşu λ=0.14826255'te durur; son kabul edilen durumda `255` yoktur.
Son kesilen adımın nedeni `material_return` olur. Yalnızca zemini aynı E, ν ve γ ile
elastik yapıp ara yüzleri değiştirmeyen ayırıcı koşu tamamlanır. Bu bir tanı deneyidir;
elasto-plastik S4 yerine geçmez. Güncel ağ/integrasyon sonuçları [mixed-mesh.md](mixed-mesh.md).

## P4 yeniden açıldı

SRF'de yerel dönüş başarısızlığını bir göçme üst sınırı saymak yasaklandı. Son
reddedilen adım `material_return` ise SRF güvenlik sayısı döndürmez, açıklayıcı
`MaterialIntegrationError` verir. Mevcut P4 şevinde F=1.5625 üst sınır denemesi bu
hatayı üretir (c_F=6.4 kPa, φ_F=13.112699°, ψ=0).

Önceden bildirilen P4 FS/ağ yakınsaması sayıları bu nedenle doğrulanmış kabul
edilmez. Asıl testin %3 Bishop ölçütü ve mekanizma kontrolleri korunur; yalnızca
`MaterialIntegrationError` için **strict xfail** işaretlidir. Diğer hatalar test
başarısızlığıdır; beklenmedik başarı da işareti kaldırıp yeniden doğrulamayı gerektirir.
Bağımsız Bishop kontrolü geçmeye devam eder. P4 ve Kapı 2'nin ilgili doğrulaması yeniden
açıktır; Kapı 3 de açık kalır.

## Kullanım

```bash
PYTHONPATH=src OPENBLAS_NUM_THREADS=1 python examples/diagnose_sheet_pile.py --size 0.5 --mixed --gauss-order high --output /tmp/pile-diagnostic.json
PYTHONPATH=src OPENBLAS_NUM_THREADS=1 python examples/diagnose_sheet_pile.py --size 0.5 --mixed --gauss-order high --elastic-soil --output /tmp/pile-elastic.json
```

Başarısız çözüm çıkış kodu 1 verir. JSON; kabul/ret adımlarını, normalize kuvvet
kalıntılarını, mutlak kuvvet normlarını, enerji oranlarını, durma nedenini ve hata
metnini içerir. Enerji oranı ilk iterasyonda `null` olur. Son kabul edilen kısmi
durumun serbest DOF kuvvet dengesi, büyük kalıntılı düğümler ve malzeme/ara yüz
bayrakları da verilir. Bunlar tamamlanmış aşama sonucu veya restart dosyası değildir.
`--no-line-search` ayırıcı bir koşu sunar; toleransları değiştirmez.

`StepRecord` yeni alanları HDF5 geçmiş JSON'una kaydeder. Eski dosyalarda bulunmayan
tanı alanları boş varsayılanlarla okunur. L0 hata sınıfı L3'e bağımlı olmadan isteğe
bağlı geçmiş nesnesini taşır. Doğrudan malzeme dönüşü başarısızlığı da çağırana
istisna olarak bildirilir.

Sıradaki iş: bu yük yolları için fiziksel olarak tanımlı çekme/apex davranışını
belirleyip bağımsız yerel gerilme/tanjant kontrolleriyle doğrulamak; sonra P4 ve
palplanş ağ/integrasyon karşılaştırmalarını yeniden çalıştırmak.

Bu adımın ilk eklemesi tamamlandı: açıkça verilen Rankine kesmesi ortak MC apex'inde
korunuyor, sabit köşe tanjantı tam sıfır ve boşaltma tahmini kontrol ediliyor.
`--soil-tension 0` parametresi tanı aracında da kullanılabilir.
[Yöntem, sınırlar ve yeni palplanş koşuları](coincident-tension-cutoff.md).
Kesmesiz P4/S4 için yukarıdaki açık doğrulama durumu korunur.

`--audit`, `--excavation-factor`, `--method`, `--max-iterations` ve
`--elastic-interfaces` seçenekleriyle aynı yükte yöntem/koşullanma ve elastik köşe
referansı incelenebilir. [Sayısal bulgular ve sınırlar](convergence-audit.md).
