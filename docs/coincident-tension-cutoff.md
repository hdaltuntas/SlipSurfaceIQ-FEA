# Açık çekme kesmesi ve çakışan apex

`MaterialSpec.mohr_coulomb(..., sig_t=0.)` artık c=0 durumunda da açıkça verilen
Rankine çekme potansiyelini korur. Önceki `sig_t >= apex` koşulu, kesme düzlemi MC
apex'iyle çakıştığında bu seçimi devre dışı bırakıyordu. `sig_t=None` kesme
potansiyeli eklemez; bu varsayılan değiştirilmedi. Apex'in üstündeki kesme düzlemi
MC bölgesinde etkin olmadığından yine devre dışıdır.

`MaterialSpec.mohr_coulomb(..., rankine_at_apex=True)` aynı ilişkili Rankine
akışını mevcut MC apex'inde açıkça seçer. Sayısal `sig_t` ile birlikte verilmez;
φ>0 gerektirir. Bu seçenek her SRF modelinde sınırı yeniden hesaplar ve tam eşit
`sig_t=apex` kullanır. `c/F` ve `tanφ/F` aynı anda azaltıldığından analitik apex
değişmez; yine de iki ayrı kayan nokta hesabının karşılaştırılması gerekmez.
Varsayılan `False` eski MC akışını korur. Model/sonuç kaydında seçenek saklanır.

## Yöntem ve yerel kontroller

Clausen–Damkilde (2006), *A simple and efficient FEM-implementation of the Modified
Mohr-Coulomb criterion*, MC ile Rankine yüzeylerinin birleşimini; MC için ilişkisiz,
Rankine için ilişkili akışla tarif eder. Dönüş ve tanjant asal gerilme uzayında
hesaplanır. [Yazarların üniversitesindeki kaynak PDF](https://vbn.aau.dk/ws/portalfiles/portal/5145833/ClausenDamkilde.pdf),
özellikle Eş. 1–6 ve 16. Aşağıdaki çakışma kontrolü bu denklemlerden türetilen
yerel uygulama kontrolüdür; makalede bu yazılımın doğrulandığı iddia edilmez.

σt = c·cotφ noktasında altı MC ve üç Rankine potansiyeli birlikte etkindir.
Köşe dönüşünde kabul edilebilir düzeltme konisi bu dokuz yönü kapsar. Yalnızca
üç Rankine yönünü denemek, karışık kayma/çekme düzeltmelerini kaçırabilir.
Çakışma testi deneme gerilmesinin büyüklüğüne göre değil yüzey parametrelerinin
makine hassasiyetindeki farkına göre yapılır.

ψ=0 için MC düzeltmeleri eş-hacimlidir. Ortalama deneme gerilmesi ortak apex'in
üstündeyse Rankine hacimsel akışı gerekir. σ1=σt=apex ve MC kabul edilebilirliği
birlikte σ2=σ3=apex gerektirir. Bu bölgenin gerilmesi sabittir; tanjantı tam sıfırdır.
Eski 1e-8·D köşe rijitliği kaldırıldı. Bu sıfır tanjanttan boşaltmaya başlarken
önceki durumun matrisi tekilse ilk Newton tahmini elastik matrisle yapılır.
Sonraki NR iterasyonlarında gerçek malzeme tanjantı kullanılır; tekil iterasyon
tanjantı varsayılan olarak elastik matrisle değiştirilmez.

## Erken apex dönüşü ve isteğe bağlı iterasyon rijitliği

Çekirdekte yerel Newton döngüsü yerine asal gerilmelerde analitik aktif-küme
adayları denenir. Standart düzlem/kenar adaylarından önce şu özel kontrol vardır:
ψ=0, φ>0, açık Rankine sınırı MC apex'iyle çakışıyor, deneme akmış ve deneme
ortalaması apex'e eşit veya üstünde. Düzeltmenin altı MC ve üç Rankine
potansiyelinin negatif olmayan birleşimi olduğu ayrıca kontrol edilir. Kabul
edilirse dört bileşenli gerilme `(apex, apex, apex, 0)` ve tam sıfır tanjant
döner. İzotropik sabit gerilmenin dönüşümünde `cos²+sin²` yuvarlaması da önlenir.

Yalnız ortalama gerilme koşulu genel bir apex testi değildir: örneğin c=10,
φ=30°, ψ=5°/30° ve deneme asal gerilmeleri (300,−100,−110) kPa iken ortalama
apex üzerindedir ama kabul edilebilir dönüş kayma yüzeyinedir. Regresyon testi
bu durumlarda yanlış apex kırpmasını engeller. Daha düşük bir Rankine kesmesi
de bu erken bloğu kullanmaz. Akış seçilmemişse yerel hata korunur.

Sabit dönüş bölgesinin içinde `dσ/dε=0`'dır; yüzey geçişinde klasik türev tek
olmayabilir. `ε·D_elastic`, bu sabit dönüşün **tutarlı türevi değildir**. İstenen
sayısal seçenek `SolverSettings(apex_stiffness_ratio=1e-6)` ile ayrı tutulur:

- Yalnız MC apex'inde, plastik bayraklı ve tam sıfır tanjantlı GP'lerin Newton
  faktörleme matrisi için `ratio·D_elastic` kullanılır. Diğer GP'ler/yapılar korunur.
- Gerilme, iç değişken, iç kuvvet, kabul ölçütleri ve kaydedilen gerçek malzeme
  tanjantı değişmez. Elastik veya daha düşük Rankine köşeleri etkilenmez.
- `0` varsayılandır; kapalı durumda tam tanjant kullanılır. Etkin seçenek yaklaşık
  Newton matrisidir; global tekilliği, iyi koşullanmayı veya dengeyi garanti etmez.
- `--audit` içindeki son kabul edilen tanjant raporu gerçek tanjanta aittir;
  seçenek açıkken faktörlenen yaklaşık matrisle aynı olduğu varsayılmamalıdır.

Kayıtlı P4/palplanş girdileri açık seçenekle kabul edilebilir apex gerilmesine
döner. Bağımsız NNLS ayrıştırması, MC/Rankine potansiyellerinde negatif olmayan
çarpanlar ve gereken pozitif toplam Rankine çarpanını doğrular. Gerçek tanjant
sonlu farkla; yaklaşık matrisin kapsamı, giriş dizilerinin değişmezliği ve
0/1e-8/1e-6/1e-4 ile yükleme–boşaltma–yeniden yükleme yolu ayrıca kontrol edilir.

## P4: açık Rankine-apex modeli

```bash
PYTHONPATH=src OPENBLAS_NUM_THREADS=1 python examples/slope_strength_reduction.py --rankine-at-apex --output /tmp/p4-exact.json
PYTHONPATH=src OPENBLAS_NUM_THREADS=1 python examples/slope_strength_reduction.py --rankine-at-apex --apex-stiffness-ratio 1e-6 --output /tmp/p4-approximate.json
```

E=100000 kPa, ν=0.3, c=10 kPa, φ=20°, ψ=0, γ=20 kN/m³; önceki geometri,
mesnetler ve toleranslar korunur. Başarısız yerel dönüş SRF göçme sınırı sayılamaz.
Burada eklenen akış yalnız MC apex'indedir; MC'nin elastik gerilme bölgesi
daralmaz. Sıfır çekme dayanımlı farklı bir zemin seçilmemiştir.

| h [m] | Düğüm | Apex iterasyon katsayısı | Kabul edilen F | Başarısız üst F |
|---:|---:|---:|---:|---:|
| 1.5 | 1259 | 0 | 1.396484 | 1.406250 |
| 1.5 | 1259 | 1e-8 | 1.396484 | 1.406250 |
| 1.5 | 1259 | 1e-6 | 1.396484 | 1.406250 |
| 1.0 | 2539 | 0 | 1.376953 | 1.386719 |

Bu koşularda yerel ret yoktur. Kaba ağın tam tanjant koşusunda üst denemelerde
tekil global matris retleri görüldü; 1e-6 koşusunda retler kalıntı duraklamasıydı.
Her iki yaklaşım aynı alt/üst aralığı verdi. Süreler performans ölçütü değildir.
İki ağ seviyesi tam ağ yakınsaması veya bütün modellerde katsayı bağımsızlığı
kanıtı değildir.

`test_slope_factor_of_safety`, h=1.5 tam/1e-6 ve h=1.0 tam tanjant için önceki
%3 Bishop, ≤0.01 aralık ve mekanizma-konumu ölçütlerini korur; kabul edilen
gerilmelerin azaltılmış akma yüzeyine uygunluğu ayrıca kontrol edilir.
[Griffiths–Lane (1999), yazarın kaynağı](https://inside.mines.edu/~vgriffit/slope64/Griffiths%20and%20Lane%201999)
Örnek 1'de Bishop 1.38 ve FE 1.4 civarındaki geçişi verir. Bu, orijinal yazarların
aynı apex akışını kullandığı iddiası değildir; bizim açıkça belgelenmiş model
tamamlamamızın karşılaştırmasıdır. Eski kesmesiz test
`test_legacy_slope_without_rankine_apex_flow` adıyla strict xfail kalır.

`test_mc_coincident_cutoff.py`: c=0/10 kPa, hidrostatik ve karışık çekme/kayma
yollarında analitik apex gerilmesi, kabul edilebilirlik ve sonlu farkla sıfır
tanjant; kesme verilmediğinde hatanın korunması; ilişkili MC köşe tanjantı.
`test_coincident_tension_path.py`: T3/T6/Q4/Q8 ile başlangıç basıncından çekmeye,
elastik boşaltmaya ve yeniden yüklemeye analitik gerilme yolu ve kuvvet dengesi.
Bu testte homojen deformasyonu dayatan düğüm değerleri, merkezde bir serbest
yatay DOF bırakılarak uygulanır; genel serbest plastik çekme alanının tekilliği
gizlenmez. Newton tahmini için geri dönüş kapsamı ayrı birim testleriyle sınırlanır.

## Palplanşta açık malzeme seçimi

```bash
PYTHONPATH=src OPENBLAS_NUM_THREADS=1 python examples/compare_sheet_pile_meshes.py --sizes 0.5 0.25 --gauss-order high --soil-tension 0 --csv /tmp/pile-cutoff-high.csv
```

`--soil-tension 0` kullanıcı tarafından seçilen ilişkili çekme akışını etkinleştirir;
parametre atlanırsa eski kesmesiz model korunur. CLI bu seçimi CSV/JSON tanısına
kaydeder. Zemin E, ν, c, φ, ψ ve γ değerleri, ara yüz, sınırlar ve toleranslar
değişmez. Buna rağmen çekme akışı farklı bir malzeme tanımıdır; önceki kesmesiz
modelin doğrulanmış çözümü olarak sunulamaz.

Son kodla high integrasyonda dört koşu da kazıyı λ=1'e kadar tamamladı:

| h (m) | Ağ | Maksimum \|M\| (kNm/m) | Maksimum düğüm \|u\| (m) |
|---|---|---:|---:|
| 0.50 | T6 | 164.401016 | 0.04105281 |
| 0.50 | T6+Q8 | 163.801169 | 0.03965327 |
| 0.25 | T6 | 167.731475 | 0.04239181 |
| 0.25 | T6+Q8 | 167.943773 | 0.04199557 |

İnce ağda moment farkı %0.127, maksimum yer değiştirme normu farkı %0.935'tir.
Kaba/ince moment değişimi T6 için %2.03, karma ağ için %2.53'tür. İki ağ
seviyesinin bu uyumu tam ağ yakınsaması veya bağımsız doğrulama değildir.
Tek ortamın süreleri performans garantisi olarak kullanılmaz.

S4'ün bağımsız araç referansı ve P4'ün eski kesmesiz yük yolu hâlâ açıktır.
P4'ün açık Rankine-apex kapsamı yukarıda ayrıdır; Kapı 3 kapatılmadı.

Yeni açık apex seçimi ve 1e-6 iterasyon katsayısıyla h=0.5 karma/high palplanş
kontrolü de λ=1'e ulaştı: maksimum |M|=163.801169 kNm/m, maksimum düğüm normu
0.039653270 m, yerel ret sayısı 0. Bu c=0 modelinde apex zaten 0'dır; sonuç
yukarıdaki açık σt=0 koşusuyla uyuşur. Bu tekrar bağımsız S4 referansı değildir.

```bash
PYTHONPATH=src OPENBLAS_NUM_THREADS=1 python examples/diagnose_sheet_pile.py --size 0.5 --mixed --gauss-order high --rankine-at-apex --apex-stiffness-ratio 1e-6 --output /tmp/pile-apex.json
```
