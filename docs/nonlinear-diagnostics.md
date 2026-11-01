# Local material failure and Newton diagnostics

When the Mohr–Coulomb return could not find an admissible active set, the old code
returned the elastic trial stress with flag `255`. The global force/energy check did
not test whether that stress lay on the yield surface, so such a state could be
accepted. That behaviour was fixed: the whole material batch is rejected with
`MaterialIntegrationError`; the input stress/history arrays are unchanged. Newton does
not accept that trial, keeps the last accepted state, and cuts the step. When the
minimum step is reached, `NonConvergence.history` contains the diagnostic record.

## Independent replay of the local inputs

The sheet-pile numerical records in this document were taken before the embedded-tip
connection of the two-sided interface was fixed. The old model split the tip on the
second side that was added; the current code keeps the tip shared on both sides. The
old values are diagnostic history; the current model and the replays are in the
[S4 protocol](s4-comparison.md).

`MaterialIntegrationError.details` carries the active material parameters, the number
of failed Gauss points, and, for the first eight points at most, `sig_n`, `deps`,
`q_n`, the trial stress, the mean stress, and the yield value. The static solver adds
the block name, the element index inside the block, the zero-based Gauss-point index,
and the physical coordinate. Newton’s rejected `StepRecord.material_failure` record
ties this data to the relevant λ/iteration; the SRF exception also keeps the last
local record. The field of accepted steps is `null`. Old history files are read with
the same `null` default.

The recognised special cause is `zero_dilation_trial_above_apex`. With tension positive,
the trace of the ψ=0 MC potentials is zero. With isotropic elasticity the plastic
correction does not change the mean stress. Admissibility of MC in ordered principal
stresses, on the other hand, requires

\[
k\sigma_1-\sigma_3\le s_c,\quad \sigma_3\le\sigma_1
\quad\Rightarrow\quad
\bar\sigma\le\sigma_1\le\frac{s_c}{k-1}=c\cot\phi
\]

(φ>0). If there is no active Rankine potential and the trial mean exceeds this apex by
more than the scale-dependent 1e-10 diagnostic tolerance, no admissible return can be
found with the MC potentials selected for that trial increment. The production
yield/active-set tolerances were not changed. Other rejections stay
`active_set_not_found`; no automatic diagnosis of non-existence or drift is attached to them.

Recorded real inputs (`tests/verification/data/material_return_failures.json`):

| Run / last local rejection | Block / element / GP | Location [m] | Trial mean [kPa] | Apex [kPa] |
|---|---|---|---:|---:|
| Sheet pile h=0.5, mixed/high, no cut-off | soil:quad / 226 / 5 | (−0.235912, −0.028175) | 0.000927848 | 0 |
| P4, SRF F=1.5625, no cut-off | soil / 433 / 2 | (11.406700, 3.801769) | 41.093091 | 27.474774 |

On the sheet pile there are 21 Gauss-point rejection records across 15 failed local
evaluations (repeat visits included); all of them satisfy this special condition.
Because each batch rejected at most five points, the eight-point limit did not truncate
data in this run. The first rejection contains five Q8 points; the last rejection
contains the single point above. The last rejected trial is λ=0.148418975,
iteration=1; the last accepted λ is 0.148262548. The last point is not at the
excavation corner. In other models the first eight samples may not represent every failed point.

Without the global solver, the number of equal local substeps that can be completed
from the same initial stress and the same total strain increment:

| Total substeps | Completed on the sheet pile | Completed on P4 |
|---:|---:|---:|
| 1 | 0 | 0 |
| 2 | 0 | 1 |
| 8 | 1 | 4 |
| 32 | 5 | 19 |
| 128 | 21 | 76 |

None of them completes the total increment. The unit tests check admissibility of the
initial stress, rejection of the direct and of the 128-piece increment, and trace
balance of the accepted substeps. This is a result for the **recorded trial increments**;
it does not show that no global equilibrium solution exists, or that the material model
fails on every load path. Explicit Rankine flow, a different ψ, or a new apex rule is
a separate constitutive definition; the diagnostic tool does not add them by itself.

```bash
PYTHONPATH=src OPENBLAS_NUM_THREADS=1 python examples/replay_material_failure.py /tmp/pile-diagnostic.json --which last
```

The tool replays every point of the first/last record in 1/2/8/32/128 pieces; it does
not provide a new production integrator or a consistent tangent.

Independent small reproduction: under E=30000 kPa, ν=0.3, c=0, φ=30°, ψ=0 and zero
initial stress, a tensile strain of 1e-5 in the three normal components gave, in the
old code, σ=(0.75, 0.75, 0.75, 0) kPa and f_MC=1.5 kPa. That is not an admissible
return. The sum of the normal components of the ψ=0 MC shear potentials is zero; they
cannot supply the volumetric correction needed to move this particular hydrostatic
tension trial onto the apex. The code now reports this local failure explicitly. The
physical material model was not changed: no artificial cohesion, dilatancy, or new
tension/apex rule was added.

## Observation on the sheet pile

Before the guard, in the h=0.50 m, mixed T6+Q8, high-integration case, the last
accepted state at λ=0.19426956 carried **6 GP `255`**. This failure was seen in 406
stress evaluations in total (at most 8 GP in a single evaluation). One source of the
residual jumps was thereby identified directly; it was not concluded that this explains
the whole mesh sensitivity, or that it is physical collapse.

With the guard, the same run stops at λ=0.14826255; the last accepted state has no
`255`. The reason of the last cut step is `material_return`. A separating run that
makes only the soil elastic, with the same E, ν, and γ, and does not change the
interfaces, completes. This is a diagnostic experiment; it does not replace the
elasto-plastic S4. Current mesh/integration results: [mixed-mesh.md](mixed-mesh.md).

## Open verification limit of the legacy uncut P4

Counting a local return failure as a collapse upper bound in SRF was forbidden. If the
last rejected step is `material_return`, SRF does not return a factor of safety; it
raises a descriptive `MaterialIntegrationError`. On the legacy uncut P4 slope, the
F=1.5625 upper-bound trial produces this error (c_F=6.4 kPa, φ_F=13.112699°, ψ=0).

The previously reported P4 FS/mesh-convergence numbers are therefore not accepted as
verified. The original test’s 3% Bishop criterion and the mechanism checks are kept;
only `MaterialIntegrationError` is marked **strict xfail**. Other errors are test
failures; an unexpected pass also requires the mark to be removed and the case to be
re-verified. The independent Bishop check continues to pass. Verification of the legacy
uncut model is open. The later explicit `rankine_at_apex=True` model passed the 3%
Bishop criterion; the [new scope and numbers](coincident-tension-cutoff.md#p4-explicit-rankine-apex-model)
do not make the old unguarded results valid again. Gate 3 remains open.

## Use

```bash
PYTHONPATH=src OPENBLAS_NUM_THREADS=1 python examples/diagnose_sheet_pile.py --size 0.5 --mixed --gauss-order high --output /tmp/pile-diagnostic.json
PYTHONPATH=src OPENBLAS_NUM_THREADS=1 python examples/diagnose_sheet_pile.py --size 0.5 --mixed --gauss-order high --elastic-soil --output /tmp/pile-elastic.json
```

A failed solve returns exit code 1. The JSON contains accepted/rejected steps,
normalised force residuals, absolute force norms, energy ratios, the stopping reason,
and the error text. The energy ratio is `null` on the first iteration. Force balance
of the free DOFs of the last accepted partial state, the nodes with a large residual,
and the material/interface flags are also given. These are not a completed stage result
or a restart file. `--no-line-search` offers a separating run; it does not change the tolerances.

New `StepRecord` fields are saved in the HDF5 history JSON. Diagnostic fields that are
missing from old files are read as empty defaults. The L0 error class carries an
optional history object without depending on L3. A direct material-return failure is
also reported to the caller as an exception.

This step is done: an explicitly given Rankine cut-off is kept at the common MC apex,
the fixed corner tangent is exactly zero, and the unloading predictor is checked.
The `--soil-tension 0` parameter can also be used in the diagnostic tool.
[Method, limits, and the new sheet-pile runs](coincident-tension-cutoff.md).
The open verification status above is kept for uncut P4/S4.

`--rankine-at-apex` explicitly selects associated tensile flow at the active apex;
it is not given together with `--soil-tension`. `--apex-stiffness-ratio 1e-6` selects
the approximate Newton matrix without changing the stress update; the default is 0.

With `--audit`, `--excavation-factor`, `--method`, `--max-iterations`, and
`--elastic-interfaces`, the method/conditioning and the elastic corner reference can
be examined at the same load. [Numerical findings and limits](convergence-audit.md).
