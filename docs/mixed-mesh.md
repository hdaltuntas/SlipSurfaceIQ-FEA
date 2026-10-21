# Karma üçgen/dörtgen ağ (deneysel)

`recombine_mesh` mevcut bir sürekli ortam ağındaki uygun üçgen çiftlerini birleştirir:
T3 → Q4 veya T6 → Q8. Aynı ağda yalnızca tek interpolasyon derecesi kullanılır.
Üçgen/dörtgen geçişi ortak köşe ve (kuadratikte) ortak orta düğüm kimlikleriyle
uyumludur; hanging node/MPC kullanılmaz. scikit-fem bağımlılığı eklenmedi.

```python
from slipsurface.fe2d.mesh import rectangle, recombine_mesh, mesh_quality

tri = rectangle(20., 10., 40, 20)  # T6
mixed = recombine_mesh(tri, where=lambda xy: xy[:, 0] < 10.)
print(mesh_quality(mixed))
```

Bu işlemi Model, yük, malzeme ataması ve beam/bar/interface elemanlarını oluşturmadan
önce yapın. Düğüm numaraları değişebilir; düğüm/kenar kümeleri yeniden eşlenir.
Çözülmüş durumun veya geçmiş değişkenlerinin yeni ağa aktarılması desteklenmez.

## Korunan sınırlar ve kalite

- Çiftler aynı blok ve bölgeden seçilir; adlandırılmış kenarlar silinmez.
- Adlandırılmış düğüm kümesindeki kuadratik köşegen orta düğümü korunur (`all` hariç).
- Eğri T6 çiftleri üçgen kalır. Yalnızca düz kenarlı, dışbükey çiftler birleştirilir.
- Varsayılan iç açı aralığı 45–135°, en büyük kenar karesi/en küçük köşe çapraz
  çarpımı oranı en çok 5'tir; `min_angle` ve `max_aspect` ile değiştirilebilir.
- Kaliteye göre deterministik açgözlü eşleştirme yapılır. Düzenli, duvara paralel
  dörtgen katman veya belirli bir dörtgen yüzdesi garanti edilmez.

`validate_conformity` yinelenen kullanılan düğüm koordinatlarını, ikiden fazla
elemanın paylaştığı kenarları, uyumsuz orta düğümleri ve düz kenarlardaki hanging
köşeleri reddeder. Genel eğri kenar kesişimi ve eleman içi örtüşme denetimi yapmaz.
`mesh_quality` artık üçgen/dörtgen sayısını ve dörtgen köşelerinde ölçekli Jacobian'ı
raporlar. Yarıçap/kenar oranı yalnızca üçgenler içindir; eğri elemanların iç Jacobian
kontrolünün yerini köşe geometrisi ölçütleri almaz.

## Doğrulanan kapsam

`test_mixed_mesh.py`, `test_mixed_patch.py` ve `test_e2_cantilever.py` içinde:
geometri/küme korunması ve determinizm; çarpık ağda düzlem/eksenel simetrik sabit
deformasyon; asgari rijit cisim kısıtlarıyla çekme; analitik konsol sehimi ve reaksiyon;
analitik Tresca plastik basınç; elastik yolda kazı/geri dolgu; iki taraflı liner/ara yüz;
hidrostatik basınç ve kuvvet dengesi; HDF5/.ssproj/VTU gidiş-dönüşü kontrol edilir.
Yüksek dereceli ağda hidrostatik efektif gerilme alanı da analitik kontrol edilir.
Bu kapsam, zeminli nonlinear palplanşın doğrulandığı anlamına gelmez.

## Aynı palplanş modeliyle karşılaştırma

```bash
PYTHONPATH=src OPENBLAS_NUM_THREADS=1 python examples/compare_sheet_pile_meshes.py --sizes 0.5 0.25 --gauss-order default --csv /tmp/pile-default.csv
PYTHONPATH=src OPENBLAS_NUM_THREADS=1 python examples/compare_sheet_pile_meshes.py --sizes 0.5 0.25 --gauss-order high --csv /tmp/pile-high.csv
```

Her iki model aynı geometri, malzeme, sınır ve yük aşamalarını kullanır. Karma
modelde yalnızca |x| < 4 m içindeki uygun çiftler birleştirilir. Başarısız koşu
çıkış kodu 1 verir; son yakınsayan yük çarpanı raporlanır, tamamlanmış aşama
momenti/yer değiştirmesi üretilmez.

| h (m) | Ağ | Düğüm | T6 / Q8 | GP (default / high) |
|---|---|---:|---:|---:|
| 0.50 | T6 | 3889 | 1829 / 0 | 5487 / 10974 |
| 0.50 | T6+Q8 | 3658 | 1367 / 231 | 5025 / 10281 |
| 0.25 | T6 | 5380 | 2520 / 0 | 7560 / 15120 |
| 0.25 | T6+Q8 | 4917 | 1594 / 463 | 6634 / 13731 |

`default`: T6 3 GP, Q8 2×2 azaltılmış integrasyon; `high`: T6 6 GP, Q8 3×3.
Kaba ağda düğüm sayısı %5.94, default GP sayısı %8.42 azalır. Bu, hızlanma veya
nonlinear yakınsama garantisi değildir. Yerel MC dönüşünün başarısızlığını `255`
bayraklı elastik denemeyle gizleyen hatanın ilk düzeltmesinde (`b5dfcbe`) aynı sekiz
koşu tekrar çalıştırıldı; aşağıdaki kayıtlar çekme kesmesi seçilmemiş o kod içindir.

| h (m) | Ağ | Integrasyon | Kazı son yük çarpanı | Tamamlandı mı? |
|---|---|---|---:|---|
| 0.50 | T6 | default | 0.98698 | Hayır |
| 0.50 | T6+Q8 | default | 1.00000 | Evet |
| 0.25 | T6 | default | 0.88966 | Hayır |
| 0.25 | T6+Q8 | default | 0.57445 | Hayır |
| 0.50 | T6 | high | 0.96729 | Hayır |
| 0.50 | T6+Q8 | high | 0.14826 | Hayır |
| 0.25 | T6 | high | 0.42167 | Hayır |
| 0.25 | T6+Q8 | high | 0.06509 | Hayır |

Tamamlanan tek koşuda |M|max = 168.278009 kNm/m ve maksimum düğüm yer değiştirme
normu 0.04217045 m. Eşdeğer T6 koşusu tamamlanmadığından doğrulanmış bir moment
farkı veya ağ yakınsaması hesabı yapılamaz. Önceden bildirilen %1.80 fark ve diğer
yük çarpanları korumasız koda aittir; doğrulama kanıtı olarak geri çekilmiştir.

High karma kaba ağ tanısı, eski kabul edilmiş durumdaki 6 adet `255` GP'yi
gösterdi; koruma sonrasında bu durum kabul edilmiyor. Ayırıcı elastik-zemin
koşusu tamamlandı. Yerel hata, P4'e etkisi ve tanı komutları:
[nonlinear-diagnostics.md](nonlinear-diagnostics.md).
Toleranslar ve fiziksel malzeme parametreleri bu karşılaştırmada değiştirilmedi.
İnce ağ yakınsaması, P4 ve bağımsız S4 referansı çözülmeden kapılar açık kalır.

Açık `--soil-tension 0` seçimiyle güncel high integrasyon koşullarının dördü de
tamamlanır; bu farklı çekme akışının tanımı, yerel testler ve yeni sonuç tablosu
[coincident-tension-cutoff.md](coincident-tension-cutoff.md) içindedir.
