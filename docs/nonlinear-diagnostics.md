# Yerel malzeme hatası ve Newton tanısı

Mohr–Coulomb dönüşü kabul edilebilir bir aktif küme bulamadığında eski kod
elastik deneme gerilmesini `255` bayrağıyla geri veriyordu. Global kuvvet/enerji
kontrolü bu gerilmenin akma yüzeyinde olup olmadığını kontrol etmediğinden böyle
bir durum kabul edilebiliyordu. Bu davranış düzeltildi: tüm malzeme batch'i
`MaterialIntegrationError` ile reddedilir; giriş gerilme/geçmiş dizileri değişmez.
Newton bu denemeyi kabul etmez, son kabul edilen durumu korur ve adımı küçültür.
Minimum adıma ulaşıldığında `NonConvergence.history` tanı kaydını içerir.

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
