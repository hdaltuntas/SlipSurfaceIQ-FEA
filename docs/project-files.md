# Proje ve sonuç dosyaları

```python
from slipsurface.fe2d import api

result = api.run(model)
api.save_results(result, 'results.h5')
api.save_project(model, 'analysis.ssproj', results=result)

project = api.load_project('analysis.ssproj')
model = project.model
result = project.results           # sonuçsuz projede None
api.export_vtu(result, 'last.vtu')  # yeniden çözmeden post-processing

# Sadece model: sonuç dizileri okunmaz.
model = api.load_project('analysis.ssproj', include_results=False).model

# Büyük HDF5 dosyası: model/ağ açılışta; yalnızca istenen aşama okunduğunda yüklenir.
with api.ResultsReader('results.h5') as reader:
    print(reader.stage_names)
    stage = reader.stage(-1)
# stage dizileri artık dosyadan bağımsızdır.

# Tüm sonuçları ve post-processing geometrisini belleğe alır.
result = api.load_results('results.h5')
```

`save_model` / `load_model` önceki düz JSON biçimini korur. Yeni API'ler ayrı adlarla
sunulur. Mevcut proje JSON şeması değiştirilmedi.

`.ssproj`, `model.json`, `mesh.h5` ve isteğe bağlı `results.h5` içeren ZIP dosyasıdır.
Model JSON'unda `project_version=1`, mevcut `schema_version` ve `mesh_file` bulunur;
koordinat ve bağlantı listeleri JSON içinde tekrarlanmaz. Model ile kaydedilen sonuç
modelinin farklı olması reddedilir. Okuyucu yalnızca sabit isimli üyeleri okur; dosya
sistemine serbest ZIP çıkarımı yapmaz.

HDF5 sonuç biçimi v1, `/mesh`, `/model`, `/initial`, `/stages/<i>` içerir. Ağ blokları
ve alan sözlükleri numaralı gruplar halinde saklanır, kullanıcı etiketleri attribute'tur.
Böylece `/` içeren adlar ve aynı adlı aşamalar kayıpsız korunur. Adla erişim ilk eşleşmeyi,
indeksle erişim tam aşamayı verir. Blok sırası sayısal indeks sırasıdır.

Her aşamada `u`, `rotation`, `reactions`, `sig`, `q`, `plastic`, `active`, `pore`,
`beams`, `bars`, `interfaces`, `struct_flags`, yük faktörü, zamanlamalar ve tüm adım
kayıtları (başarısız denemeler dahil) korunur. Diziler NumPy dtype'ı ve NaN değerleriyle
saklanır; boş diziler desteklenir; dolu diziler gzip ile sıkıştırılır. Metadata; birim,
çekme-pozitif işaret, eksenel simetride radyan başına ölçü ve solver sürümünü içerir.
İleri şema sürümleri sessizce yorumlanmaz, reddedilir.

Dosyalar aynı klasörde geçici bir dosyaya yazılıp başarılı kapanıştan sonra atomik
olarak değiştirilir. Yazma hatasında mevcut dosya korunur. Sonuç dosyaları post-processing
snapshot'ıdır; nonlinear solver restart desteği içermez. Desteklenen tam model/sonuç
kayıtlarıdır; SRF deneme geçmişi ve kısmi/başarısız solver oturumları bu biçimin dışında.
