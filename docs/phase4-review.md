# Faz 4 incelemesi ve Faz 5 geçişi

Başlangıç: `main` / `baeac4c`; önceki düzeltme dalı: PR #1 / `ac29dbd`.
Ana dalın değişiklik öncesi benchmark dışı testi: **190 geçti** (Linux, Python 3.12).
Bu geçiş tüm testlerin geçmesinin tek başına bünye doğruluğu kanıtı olmadığını gösterdi.

## Tespit edilen ve düzeltilen durumlar

| Bulgu | Sonuç / düzeltme | Kanıt |
|---|---|---|
| Ana dal MC dönüşü, akış yönleriyle ulaşılamayan denemeyi en yakın köşeye zorluyordu | PR #1'deki koni kontrolü ve `MaterialIntegrationError` taşındı; SRF yerel reddi göçme sınırı sayamaz | MC/apex/KKT ve P4 testleri |
| İki geliştirme dalı farklı kayıt API'leri taşıyordu | İki format ve iki proje çağrı sırası korundu; Faz 4 su alanları ve hata geçmişleri gidiş-dönüşte tutuldu | Kayıt ve phase4/progress regresyonları |
| Yakınsamayan sızma mekanik aşamaya aktarılıyordu | Mekanik çözüm başlamadan `SolverError`; akışın kendisi `converged=False` ile teşhis edilebilir | Zorlanmış başarısız Picard testi |
| Tekil/izole sızma, çakışan yük sınırları ve geçersiz kontrol değerleri | Bağlı her bölge için hidrolik referans, sonlu/pozitif iletkenlik ve değer kontrolleri; tekil/NaN çözüm reddi | Bağlantısız bölge, sınır ve kontrol testleri |
| Hız alanı bir sonraki Picard iletkenliğinden, debi önceki matristen hesaplanıyordu | Çıktıların tamamı çözülen aynı iletkenlik/matris durumuna bağlı | Hız/debi analitik karşılaştırması, W1–W3 |
| HB'de ψ=0 ve ortalama çekme apex üzerinde olsa bile gerilme apex'e kırpılıyordu | Altı MC tipi potansiyelin negatif olmayan konisi; bulunamayan dönüş batch'i reddeder. Geçerli sabit apex tanjantı tam sıfır | Hacimsel akış, girdi korunması, apex türevi; C3 |
| HB tekil iki-yüzey matrisinin belleği başlatılmadan kullanılabiliyordu | Matris sıfır başlatılır; tekil tanjant reddedilir | HB dönüş/tanjant testleri |
| MCC yerel `LinAlgError`, global adım geri alma yolunu atlayabiliyordu | Yerel Jacobian/tanjant tekilliği `LocalIntegrationError` olarak taşınır; ortak malzeme hata ailesi | MCC C1/C2 ve girdi regresyonları |
| Geçersiz Kw/n, hidrolik tuple ve MCC basınç ölçekleri kabul edilebiliyordu | Sonluluk/boyut/pozitiflik denetimi; yöntem B için φ=0 ve uygun dayanım modeli | Parametre regresyonları |
| Yeni kalıntı geri izleme kodu tam NR'yi sessizce committed matrise geçiriyordu | PR #1'in tam NR/adım kesme yolu korundu; isteğe bağlı line search mevcut. Toleranslar değişmedi | P5 çekme platosu önce başarısız, düzeltmeden sonra geçti; C1/C2/S4 korundu |
| Kazılmış hücreler görüntü/VTU'da kalıyor, NaN GP'ler komşu düğüm gerilmelerini bozuyordu | Aktif topoloji ile SPR/ortalama ve çıktı; kullanılmayan düğüm NaN'ı sıfıra çevrilmez | Kazı sınırında sonlu alan ve VTU/PyVista eşitliği |
| Tam sıfır satır/sütunlu plastik rijitlik SuperLU'da BLAS parametre iletileri üretiyordu | Sonlu değer ve sıfır satır/sütun kontrolü faktörizasyondan önce; giriş matrisi korunur | P4 tekrarında BLAS iletisi yok; doğrudan matris regresyonu |
| Sabit gerilme yuvarlaması ekranda sahte renk farkı oluşturuyordu | Bağıl 1e-10 altındaki renk aralığı tek renk; sayısal sonuç değiştirilmez | Native arayüz testi ve ekran kontrolü |

Hoek–Brown'a yeni çekme potansiyeli eklenmedi. ψ=0 altında hacim koruyan akışın
ulaşamadığı hidrostatik deneme artık açık hata verir; farklı akış isteniyorsa ayrıca
adlandırılıp doğrulanması gerekir. Dış programlardaki HB seçenekleriyle otomatik
özdeşlik iddiası yoktur.

## Doğrulama

**Nihai yerel koşu: 397 geçti, 1 strict xfail, 2 benchmark hariç; 86.42 s.**
PySide6 ve PyVista testleri çalıştı; atlanan modül yok. Ruff, `git diff --check`,
masaüstü `--help` komutu ve wheel derlemesi başarılı. BLAS parametre hata iletisi
çıkmadı. Benchmark kapısı ve Windows portable bu koşuda doğrulanmadı.
Test toleransları gevşetilmedi.
Eski hatalı MC testi, akış kuralının ihlal edilmesini zorunlu kılmak yerine açık
Rankine seçeneğini ve kesmesiz modelin reddini ayrı kontrol eder. ψ=0 HB rastgele
kabul testi ortalama basınçta çalışır; çekme engeli ayrı red testiyle korunur.

Ortam: Linux x86-64, Python 3.12, NumPy 2.3.5, SciPy 1.17.0, Numba 0.68.0,
h5py 3.16.0; Qt offscreen ve PyVista kurulu. Windows yerel çalıştırması bu ortamda
yapılmadı; CI matrisinin görevidir.

```bash
ruff check src tests
QT_QPA_PLATFORM=offscreen OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
  PYTHONPATH=src python -m pytest -q -m 'not benchmark'
python -m pip wheel --no-deps . -w /tmp/fea-dist
```

**S4 dış karşılaştırması ertelendi. Eski kesmesiz P4 strict xfail. Kapı 5 ve v1.0 açık.**
