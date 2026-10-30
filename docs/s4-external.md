# S4 dış karşılaştırma — yapılmadı

Bu bir ertelenmiş iş maddesi değil. Ürün sınırıdır.

İç kiriş-yay (Winkler) ve Blum limiti `tests/verification/test_s4_winkler_comparison.py`
içinde durur. O uyum RS2 veya PLAXIS karşılaştırması değildir ve öyle yazılmaz.

Karşılaştırma ancak `docs/data/s4/external.csv` repoya konursa başlar. Dosya yokken
`tests/verification/test_s4_external.py` **atlanır**; atlamak geçmek değildir.

Sütunlar:

```text
depth_m,M_kNm_per_m,u_top_mm,source
```

* `depth_m`: duvar tepesinden aşağı, metre.
* `M_kNm_per_m`: eğilme momenti, kNm/m. İşaret protokollü [S4 kaydı](s4-comparison.md) ile aynı olsun.
* `u_top_mm`: sadece tepe satırında dolu olabilir; duvar başı yatay deplasman, mm.
* `source`: `PLAXIS` veya `RS2`. İç Winkler sayıları bu dosyaya yazılmaz.

Girdi `docs/data/s4/case.json` ve `examples/sheet_pile_staged.py` ile kilitlidir.
Aynı ağ, aynı R = 0.67, aynı iki kademe kazı. Farklı palplanş ayrı bir iştir.
