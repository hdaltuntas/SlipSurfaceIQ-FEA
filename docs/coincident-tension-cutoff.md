# Açık çekme kesmesi ve çakışan apex

`MaterialSpec.mohr_coulomb(..., sig_t=0.)` artık c=0 durumunda da açıkça verilen
Rankine çekme potansiyelini korur. Önceki `sig_t >= apex` koşulu, kesme düzlemi MC
apex'iyle çakıştığında bu seçimi devre dışı bırakıyordu. `sig_t=None` kesme
potansiyeli eklemez; bu varsayılan değiştirilmedi. Apex'in üstündeki kesme düzlemi
MC bölgesinde etkin olmadığından yine devre dışıdır.

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
tanjantı elastik matrisle değiştirilmez.

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

S4'ün bağımsız araç referansı ve P4'ün kesmesiz yük yolu hâlâ açıktır. P4 strict
xfail işareti korunur; bu ek Kapı 2/3'ü kapatmaz.
