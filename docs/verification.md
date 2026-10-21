# Doğrulama — Kapı 1 (Faz 1)

Tüm testler `tests/verification/` altında pytest olarak koşar; performans ölçütü
`tests/benchmarks/` altındadır (`pytest -m benchmark`).

| Kod | Test | Referans | Ölçüt | T6 sonucu | T3 sonucu |
|---|---|---|---|---|---|
| E1 | Patch testi — yer değiştirme (çarpık ağ, 2 tohum), çekme (sınır gerilmeleri), eksenel simetrik | Sabit birim deformasyon | < 1e-10 | ✔ makine hassasiyeti | ✔ makine hassasiyeti |
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

* **E1 — Q4/Q8:** Mimari belgede E1 dört elemanı kapsıyor; Q4 (B-bar) ve Q8 yol
  haritasında Faz 2'de yer aldığından patch testleri o elemanlarla birlikte eklenecek.
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

`tests/unit/` — şekil fonksiyonu türevleri (sonlu farkla), kuadratür tamlığı, eleman
rijitliğinin simetrisi ve tam olarak 3 rijit cisim modu, ağ geometrisi (delikli levhada
alan, katman bölgeleri), ağırlık analizi ile K₀ alanının yanal olarak tutulu kolonda
çakışması (tek ve iki tabaka), aşama artımı/yer değiştirme sıfırlama, reaksiyon
dengesi, malzeme değişimi, zorlanmış yer değiştirme, tekil sistem tespiti, JSON gidiş-
dönüş ve VTU geçerliliği.
