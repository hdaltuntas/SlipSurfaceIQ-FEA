# Doğrulama — Kapı 1 (Faz 1) ve Kapı 2 (Faz 2)

Tüm testler `tests/verification/` altında pytest olarak koşar; performans ölçütü
`tests/benchmarks/` altındadır (`pytest -m benchmark`).

| Kod | Test | Referans | Ölçüt | T6 sonucu | T3 sonucu |
|---|---|---|---|---|---|
| E1 | Patch testi — yer değiştirme (çarpık ağ, 2 tohum), çekme (sınır gerilmeleri), eksenel simetrik; T3, T6, Q4 (B-bar), Q8 | Sabit birim deformasyon | < 1e-10 | ✔ makine hassasiyeti | ✔ makine hassasiyeti |
| E2 | Konsol kiriş, sürekli ortam elemanlarıyla | Timoshenko–Goodier kesin çözümü (Augarde & Deeks 2008); plane strain için E′, ν′ | Uç sehimi < %1 | %0.0001 (40×4) | %0.87 (160×16) |
| E3 | Dairesel boşluklu levha, iki eksenli uzak gerilme (σx = 1, σy = 0.4) | Kirsch; dış sınıra kesin çekme uygulanır | Çeperde σθ < %1 | %0.27 | %2.1 (ölçüt T3 için %3) |
| E4 | Kalın cidarlı silindir, iç basınç, eksenel simetrik, εz = 0 | Lamé | σr, σθ < %1 | %0.03 | %0.01 |
| — | 50k düğümlü T6 elastik model (ağırlık + yük aşaması) | — | < 5 s | 1.9 s | — |
| — | Yapısal olmayan ağ: tünel kesiti, 55k düğümlü T6 (ağ üretimi + çözüm) | — | çözüm < 5 s | ağ 2.8 s, çözüm 3.2 s | — |

### Yapısal olmayan (Delaunay + Ruppert) ağlarda tekrar

| Kod | Ağ | Sonuç |
|---|---|---|
| E1 | Delikli, gömülü çizgili alan; T3 ve T6 | makine hassasiyeti |
| E3 | Çeyrek levha, 48 kirişli delik, deliğe doğru kademeli boyut alanı; T6 | σθ hatası %0.20 |
| E4 | Halka kesit, h = 0.1; T6 | %1 içinde, u_r < %0.5 |

Ölçüm ortamı: Linux x86-64, Python 3.13, NumPy 2.5, SciPy 1.18 (SuperLU). `pypardiso`
kuruluysa çözücü otomatik olarak PARDISO'ya geçer.

## Notlar

* **E1 — Q4/Q8:** Faz 2'de eklendi; Q4 (B-bar) ve Q8 dört patch testinin tamamını
  geçiyor. E2 (konsol) Q8 40×4 ve Q4 80×8 ile de %1 içinde.
* **E2:** Ankastre uçta kesin yer değiştirme alanı, serbest uçta parabolik kayma
  gerilmesi uygulanır; böylece karşılaştırma ankastrelik idealizasyonundan bağımsızdır.
  Ayrıca κ = 5/6 Timoshenko kiriş teorisiyle de %1 içinde kontrol edilir.
* **E3:** Hata, düğüme taşınmış (köşelere lineer ekstrapolasyon + ortalama) gerilmeyle
  ölçülür; ayrıca tüm Gauss noktalarında alan hatası kontrol edilir. SPR (Faz 2) T3
  düğüm değerlerini iyileştirecektir.
* **E4:** Gauss noktalarında σr, σθ, σz ve düğümlerde u_r karşılaştırılır; düşey
  reaksiyonların toplamı sıfırdır.

## Ağ üreteci (Delaunay + Ruppert) birim testleri

`tests/unit/test_unstructured_mesh.py` — alanın girdi poligonuyla birebir eşleşmesi,
minimum açı hedefi (28–30°), boyut alanına uyum ve kademelendirme, T6 orta düğümleri,
bölge etiketleme (iç içe poligonlar, delik, tohumla geçersiz kılma, poligon bazlı alan
sınırı), gömülü çizgilerin eksiksiz kenar zinciri olarak korunması, kesişen çizgilerin
ortak düğümü, ortak kenarların ad birleşimi, T-kavşak ve çakışan segmentler, dar girdi
açılarında (3°–4°) sonlanma ve kalitenin yalnızca açı kümesinde düşmesi, determinizm ve
hata durumları.

## Ek birim testleri

### Aynı dereceli karma ağlar (deneysel)

T3+Q4 ve T6+Q8 geçişleri ortak düğümlerle kontrol edilir. Çarpık ağda düzlem ve
eksenel simetrik patch testleri, default/high integrasyonla çekme ve E2 konsol
çözümü geçer. Plastik Tresca basınç, kazı/geri dolgu, liner/ara yüz, su ve kayıt
testlerinin kapsamı ile nonlinear palplanşta kalan başarısızlıklar
[mixed-mesh.md](mixed-mesh.md) içinde açıklanır. Bu ek, Kapı 3'ü kapatmaz.

`tests/unit/` — şekil fonksiyonu türevleri (sonlu farkla), kuadratür tamlığı, eleman
rijitliğinin simetrisi ve tam olarak 3 rijit cisim modu, ağ geometrisi (delikli levhada
alan, katman bölgeleri), ağırlık analizi ile K₀ alanının yanal olarak tutulu kolonda
çakışması (tek ve iki tabaka), aşama artımı/yer değiştirme sıfırlama, reaksiyon
dengesi, malzeme değişimi, zorlanmış yer değiştirme, tekil sistem tespiti, JSON gidiş-
dönüş ve VTU geçerliliği.

## Kapı 2 — elasto-plastik çözücü (Faz 2)

| Kod | Test | Referans | Ölçüt | Sonuç |
|---|---|---|---|---|
| P1 | Rijit düzgün şerit temel, drenajsız (φ = 0), yer değiştirme kontrollü, ağırlıksız | Prandtl, q_ult = (2 + π) su | < %3 | %0.97 (h_min = 0.05); %1.35 / %0.53 (0.1 / 0.025) — yukarıdan yakınsıyor |
| P2 | Kalın cidarlı silindir, iç basınç, Tresca, εz = 0 | Hill (1950): p(r_c), u_b = 2(1−ν²)k r_c²/(E b) | Basınç–genişleme < %2 | T6 %0.004, Q8 ve Q4 (B-bar) de %2 içinde; plastik yarıçap GP bayraklarıyla |
| P3 | Hidrostatik gerilmede dairesel tünel, MC, ψ = 0 / 15° / 30° | Salençon (1969) plastik yarıçap; çeper deplasmanı akış kuralı ODE'si | < %3 | u_a %0.43–0.57, R_pl %0.4 |
| P4 | Homojen şev 2:1, c/γH = 0.05, φ = 20°, ψ = 0, SRF | Griffiths & Lane (1999) Örn. 1; Bishop (testte dairesel arama: 1.378) | FS farkı < %3 | h = 1.5: 1.396 (%1.3); ağ yakınsaması 1.416 / 1.396 / 1.377 / 1.367 (h = 2 / 1.5 / 1 / 0.7) |
| P5 | Tek eleman (eksenel simetrik) üç eksenli basınç, çekme yolu, çekme kesmesi; MC ψ ≠ φ | Kapalı form gerilme izi ve hacimsel davranış | < %0.1 | yuvarlama hatası düzeyinde |
| — | Tam NR kuadratik yakınsama (Tresca ilişkili; MC ilişkisiz → simetrik olmayan LU) | log r_{i+1} – log r_i eğimi ≈ 2 | eğim > 1.6 | ✔ (ör. 1.8e-2 → 8.8e-7 → 3e-13); mNR doğrusal (eğim ≈ 1) |

Ek: NR, mNR, hibrit, başlangıç rijitliği ve NR + line search aynı çözüme 1e-5 göreli
farkla ulaşır (`test_newton_convergence.py`).

### Bünye modeli birim testleri (`tests/unit/test_materials.py`)

* Mohr-Coulomb (+ çekme kesmesi, ilişkisiz akış, φ = 0, c = 0): tüm geri dönüşler kabul
  edilebilir; ilişkili akışta enerji normunda en yakın nokta SLSQP ile doğrulanır;
  düzlem ve kenar dönüşlerinde tutarlı tanjant sonlu farkla 1e-5 göreli içinde.
* Drucker-Prager / von Mises: tanjant sonlu farkla; von Mises pekleşmesi kapalı formla.
* Sloan alt-adımlama: ince yolda kapalı form dönüşle %0.5 içinde, büyük tek artımda STOL
  küçüldükçe referansa yakınsar, elasto-plastik boşalma–yeniden yükleme.

### Gerilme taşıma (SPR)

SPR kendi derecesindeki (T3/Q4 doğrusal–bilineer, T6/Q8 kuadratik) polinom alanları
sınırlar dahil makine hassasiyetinde yeniden üretir; bölge sınırlarındaki sıçramayı
yaymaz. Kirsch (T6) probleminde iç bölgede RMS hatası ortalamaya göre ~%25–30 daha
düşüktür; ağın dış sınırında ekstrapolasyon ortalaması daha doğru olduğundan varsayılan
hibrit yöntem sınırda onu kullanır.

