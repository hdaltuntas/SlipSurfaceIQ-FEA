# F7 actual FEM evidence review

- Mesh targets (m): [2.5, 1.8, 1.2]
- Completed stage rows: 9 / 9
- Coverage complete: True
- Solver failures: 0
- Independent physical validation: **not established**

## Force balance classification

| Check | Passed | Failed | Unsupported |
|---|---:|---:|---:|
| gravity_balance | 9 | 0 | 0 |
| dry_load_balance | 0 | 0 | 9 |
| excavation_balance | 0 | 0 | 9 |

## Bounded integrity checks

- support_coverage_acceptance: **passed**
- interface_moment_acceptance: **passed**
- interface_transfer_ledger: **passed**

## Why checks remain unsupported

- dry_load_balance (9): Structure activation is outside the loaded-domain contract
- excavation_balance (9): Coupled structures/interfaces need a separate force budget

## Peak sensitivity review priorities (not pass/fail)

- 1. Pile installation: beam_moments/cad_Pile (47.05% finest-pair change)

## Spatial structural profile comparison

Component relative RMS values are diagnostics only.
- 1. Pile installation at h=1.8 m, cad_Pile: 0.09656, 0.7914, 0.5718
- 2. Excavation lift 1 (-2 m) at h=1.8 m, cad_Pile: 0.04103, 0.006495, 0.005293
- 3. Anchor + excavation lift 2 (-4 m) at h=1.8 m, cad_Anchor1: 0.02092
- 3. Anchor + excavation lift 2 (-4 m) at h=1.8 m, cad_Pile: 0.03932, 0.02338, 0.01714
- 1. Pile installation at h=1.2 m, cad_Pile: 0.02331, 0.9355, 0.938
- 2. Excavation lift 1 (-2 m) at h=1.2 m, cad_Pile: 0.05966, 0.09928, 0.04518
- 3. Anchor + excavation lift 2 (-4 m) at h=1.2 m, cad_Anchor1: 0.01026
- 3. Anchor + excavation lift 2 (-4 m) at h=1.2 m, cad_Pile: 0.03892, 0.08511, 0.03306

Green workflow results establish bounded execution/integrity only. Unsupported force budgets and mesh sensitivities are not passed physical checks or independent RS2/PLAXIS benchmarks.
