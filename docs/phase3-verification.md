# Faz 3 yapısal doğrulamaları

## S1 — no-slip elastik tünel

Referans: Einstein, H.H. ve Schwartz, C.W. (1979), *Simplified Analysis for Tunnel
Supports*, ASCE 105(GT4), 499–518, [DOI](https://doi.org/10.1061/AJGEB6.0000786).
Denklemler ve parametreler ayrıca Itasca'nın kendi
[doğrulama örneğinde](https://docs.itascasoftware.com/itasca960/flac3d/zonesel/test3d/Liner/LinedCircularTunnel/LinedCircularTunnel.html)
yayımlanmıştır. `test_s1_lined_tunnel.py` bu kapalı formu çözücü kodundan bağımsız hesaplar.

Düzlem şekil değiştirme, çeyrek daire, yarıçap 5 m; düşey/yatay başlangıç gerilmesi
600/300 kPa. Zemin E=48 MPa, ν=0.34; liner E=25 GPa, ν=0.15, kalınlık 0.125 m.
Liner başlangıçta kuvvetsizdir; kazı gevşemesiyle aynı aşamada aktive edilir. Dış sınıra
başlangıç gerilmesini koruyan yüzey yükleri uygulanır. Simetri uçlarında dönme sıfırdır.
Ağırlık eklenmez. Liner ve zemin ortak düğümlüdür: **no-slip** koşulu.

Analitik basınç-pozitif T, çekme-pozitif çekirdekteki N ile ters işaretlidir. M'nin yönü,
liner kenarlarının mevcut yönüyle sabitlenir. Karşılaştırma yalnızca tepe değerlerle
değil, tüm çevre boyunca imzalı N ve M alanlarının maksimum mutlak farkıyla yapılır;
paydalar ilgili referans alanın maksimum mutlak değeridir. Eleman uç kuvvetleri orta
noktaya ortalanır. Kabul sınırı her iki alanda %5'tir.

| Ağ (radyal × çevresel) | Dış sınır | N alan hatası | M alan hatası |
|---|---|---|---|
| 8 × 16 | 20R | %0.391 | %1.023 |
| 16 × 32 | 20R | %0.268 | %0.157 |
| 24 × 48 | 20R | %0.234 | %0.043 |
| 40 × 80 | 40R | %0.082 | %0.723 |

20R'de ağ incelmesi her iki hatayı azaltır; 40R kontrolü de tolerans içindedir.
Dış sınır hatası ile eleman/ince halka idealizasyonu hatası birbirini kısmen
karşılayabildiği için 40R sonucunun daha küçük moment hatası vermesi şart koşulmaz.
Bu test full-slip liner çözümünü veya plastik liner davranışını doğrulamaz.

## Goodman ara yüzü

`test_interfaces.py`, hem IFACE4 hem IFACE6 için kuvvet dengesi, rijit hareket,
sonlu farkla eleman tanjantı, su basıncının iki yüze eşit/ters etkisi ve trial
entegrasyonunun commit durumunu değiştirmemesini denetler. T3/T6/Q4/Q8 ağlarda iki
kez düğüm çoğaltılması, liner'ın iki zemin yüzünden ayrılması ve içerideki açık
ara yüz uçlarının ortak kalması kontrol edilir.

Traction dönüşü üç doğrusal akma düzlemini birlikte ele alır. Her aday aktif kümede
plastik çarpanlar negatif olmamalı ve sonuç bütün akma koşullarını sağlamalıdır.
Tanjant aynı aktif kümenin türevinden hesaplanır. Ek testler:

- Pozitif/negatif kayma, elastik, çekme ve birleşik dönüşlerde sonlu fark tanjantı.
- Dilatanslı kaymanın çekmedeki bir trial'ı basınçtaki kayma yüzeyine döndürebilmesi.
- İlişkili akışta bağımsız kısıtlı optimizasyonla en yakın nokta karşılaştırması.
- Dört malzeme durumunda 1000'er rastgele trial'ın kabul edilebilirliği.
- ks=0, φ=0, c=0, doğal apeks, çekme sınırının kapatılması ve açılma sonrası kapanma.

Önceki çekme-öncelikli kırpma, dilatanslı kayma dönüşünü yanlış seçebiliyordu.
Artık önce trial çekmede diye doğrudan kırpılmaz. Tam açık/kaymış yöndeki sıfır
teğet yapay rijitlikle değiştirilmez; gerçekten desteksiz yapı fiziksel olarak tekil
olabilir. Ayrıntılı kırılma enerjisi, kalıcı açıklık ve çevrimsel hasar bu elastik–
mükemmel plastik Goodman modelinin kapsamına eklenmedi.

## S4 — ön doğrulama, tam kapı henüz açık

`test_s4_sheet_pile.py` iki ayrı **yapısal** referans kullanır. Sabitlenmiş, yüksüz
küçük sürekli ortam bloğu, mevcut karma eleman sürücüsünün sürekli ortam bloğu şartını
karşılar; palplanşa bağlı değildir ve referans zeminin yerine geçmez.

### Kiriş–yay referansı

5 m kazı, 10 m gömülme; EI=2×10⁶ kN·m²/m, GA=4×10⁶ kN/m, k=20000 kN/m³,
γ=18 kN/m³, Ka=1/3. Açık kısımda q(z)=Ka·γ·z, gömülü kısımda Winkler tepkisi vardır.
Duvarın iki ucu moment ve kesmeye karşı serbesttir. Referans, iki parçalı sabit
katsayılı Timoshenko diferansiyel sisteminin **matris üstel fonksiyonuyla** çözümüdür:

- u′ = θ − V/GA
- θ′ = M/EI
- M′ = V
- V′ = q − k·u

Dört alan kazı kotunda süreklidir; yük ve yay katsayısı orada değişir. Üstteki doğrusal
yük iki ek durumla tam olarak entegre edilir. Uç koşullarından iki bilinmeyen başlangıç
değeri bağımsız 2×2 sistemle bulunur; referans bir sonlu eleman ağı kullanmaz.

| Eleman sayısı | FE maksimum M (kN·m/m) | Referans maksimum M, eleman ortaları | M alan hatası |
|---|---|---|---|
| 60 | 192.784829 | 193.134170 | %0.207 |
| 120 | 193.101793 | 193.190126 | %0.052 |

Uç deplasmanı, tüm moment alanı, ağ yakınsaması, toplam yatay kuvvet ve toplam moment
dengesi kontrol edilir. BAR2 yaylar iki yönlü elastiktir; bunlar plastisitesi doğrulanmış
bir kohezyonsuz zemin modeli olarak yorumlanmaz.

### Rankine basınç diyagramı

φ=25°, 30°, 35°; H=5 m, γ=18 kN/m³. Ka=tan²(45°−φ/2), Kp=1/Ka.
Net basınç q(z)=γ[Ka·z−Kp·max(z−H,0)] ve idealize tekil bir uç tepkisi kullanılır.
Toe etrafında moment dengesi Ka(H+D)³=Kp·D³ ile D bulunur. Bağımsız integral:
M(z)=γ[Ka·z³−Kp·max(z−H,0)³]/6. Maksimum moment konumu kesmenin sıfırından bulunur.
FE alanı, maksimum moment, toplam kuvvet ve uç momentinin sıfırlanması %1 içinde
kontrol edilir. Bu diyagram Winkler sonucuna uydurulmaz; iki ayrı sınır-değer problemidir.

**Tam S4 henüz geçmedi:** bu kontroller, aşamalı kazı + sürekli ortam zemini + iki taraflı
ara yüz + palplanş modelini kullanıcının bağımsız palplanş aracıyla karşılaştırmaz.
Kalan %10 maksimum moment ölçütü bu eşdeğer senaryo üzerinde doğrulanmalıdır.
Bu nedenle Kapı 3 kapatılmadı, Faz 4'e geçilmedi.

## Python 3.10 CI referans testi

Önceki CI'da SciPy 1.15.3, spektral maksimum üzerinde sonlu fark kullanan SLSQP testinde
iterasyon sınırına ulaştı. Test başarısız/olurlu olmayan optimizasyonun amaç değerini
referans kabul ediyordu. Karşılaştırma, asal gerilme uzayında altı doğrusal MC kısıtlı,
ölçeklenmiş, analitik gradyanlı bir konveks QP'ye çevrildi. Optimizasyonun başarısı ve
kısıt artığı zorunlu kontrol edilir; üretim gerilme toleransları gevşetilmedi.

## Sürekli ortam palplanş örneği: eski kesmesiz koşular

Aşağıdaki başarısızlıklar eski, Rankine akışı olmayan modele aittir. Açık
Rankine-apex modeli tam kazıyı tamamlar. Güncel karşılaştırma girdileri, uç bağlantısı,
duvar alan çıktıları ve adım/aşama duyarlılığı [s4-comparison.md](s4-comparison.md)
içindedir. Dış referans eksik olduğundan tam S4 hâlâ açıktır.

`examples/sheet_pile_staged_excavation.py`, 40×20 m sand alanında, 10.5 m uzunluğunda
palplanş ve 5 m kazı içerir. MC: E=30000 kPa, ν=0.3, c=0, φ=30°, ψ=0, γ=18 kN/m³.
Duvar: E=2×10⁸ kPa, ν=0, A=0.1 m²/m, I=0.001 m⁴/m, As=0.08 m²/m. İki tarafta
R=1 ve sanal kalınlık 0.1 m ile Goodman ara yüzü; K0=0.5 başlangıç gerilmesi; önce
kuvvetsiz duvar kurulumu, ardından sağdaki 5 m zemin bölgesinin kaldırılması vardır.
Alt sınır iki yönde, yan sınırlar yatay yönde tutulur. Su yoktur.

```bash
PYTHONPATH=src python examples/sheet_pile_staged_excavation.py --size 0.5
# Yalnızca çözüm tamamlanırsa kayıt yapılır:
PYTHONPATH=src python examples/sheet_pile_staged_excavation.py --size 0.5 --output pile.ssproj
```

| Yerel ağ boyutu | Düğüm | Gözlem |
|---|---|---|
| 0.50 m | 3889 | Yerel MC dönüş korumasıyla default T6 kazı λ=0.98698'de durur |
| 0.25 m | 5380 | Aynı korumayla default T6 kazı λ=0.88966'da durur |

Önceki 165.280601 kN·m/m momenti ve λ=0.8938 kaydı, başarısız yerel dönüşü
elastik deneme gerilmesiyle sürdüren koddan geliyordu; doğrulanmış sonuç olarak
kullanılmıyor. Karma ağ/integrasyon tablosu [mixed-mesh.md](mixed-mesh.md),
yeniden üretim ve P4'teki etkisi [nonlinear-diagnostics.md](nonlinear-diagnostics.md) içinde.

Bu açık başarısızlık bir başarı toleransıyla örtülmedi. Göçme ile sayısal yakınsama
sorununu ayıran bağımsız kontrol ve ince ağ çözümü gereklidir. Bu nedenle örnek **S4
benchmark geçişi, güvenlik sayısı veya ağdan bağımsız tasarım sonucu değildir**.
Rankine/Winkler testleri farklı sınır-değer problemleridir; bu momentle doğrudan
%10 fark hesabı yapılmaz.

Örnek ilk çalıştırmada ayrıca eski bir hata ortaya çıkardı: blok adı değişmeden
kazı yapıldığında eski aktif Gauss noktalarına ait tanjant önbelleği yeniden
kullanılıyordu. Önbellek artık tam sistem/aktif küme anahtarıyla doğrulanır. Ayrı bir
bloğun tamamen devre dışı kalması için boş DOF ve rijitlik dizileri de düzeltildi.
`test_nonlinear_staging.py`, aynı ve ayrı bloklarda kazı, eşit sayıda farklı elemanların
aktivasyonu ve geri dolgunun elastik yoldaki MC çözümünü bağımsız elastik malzemeyle
karşılaştırır.
