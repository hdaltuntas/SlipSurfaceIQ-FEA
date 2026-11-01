# S4 external comparison — not done

This is not a deferred work item. It is a product boundary.

The internal beam–spring (Winkler) and Blum limit checks live in
`tests/verification/test_s4_winkler_comparison.py`. That agreement is not an RS2 or
PLAXIS comparison, and it must not be written as one.

A comparison starts only if `docs/data/s4/external.csv` is committed. While the file
is absent, `tests/verification/test_s4_external.py` is **skipped**; skipping is not passing.

Columns:

```text
depth_m,M_kNm_per_m,u_top_mm,source
```

* `depth_m`: downward from the top of the wall, metres.
* `M_kNm_per_m`: bending moment, kNm/m. The sign must match the [S4 record](s4-comparison.md).
* `u_top_mm`: may be filled only on the top row; horizontal displacement of the wall head, mm.
* `source`: `PLAXIS` or `RS2`. Internal Winkler numbers are not written to this file.

The input is locked by `docs/data/s4/case.json` and `examples/sheet_pile_staged.py`.
Same mesh, same R = 0.67, same two-stage excavation. A different sheet pile is a separate task.
