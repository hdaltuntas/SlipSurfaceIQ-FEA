# Phase 4 review and the move to Phase 5

Start: `main` / `baeac4c`; previous fix branch: PR #1 / `ac29dbd`.
Benchmark-excluded test of the main branch before the change: **190 passed** (Linux, Python 3.12).
This transition showed that passing every test is not, by itself, proof of constitutive correctness.

## Findings that were identified and fixed

| Finding | Result / fix | Evidence |
|---|---|---|
| On main, the MC return forced a trial that the flow directions could not reach onto the nearest corner | The cone check and `MaterialIntegrationError` from PR #1 were carried over; an SRF local rejection cannot be a collapse bound | MC/apex/KKT and P4 tests |
| The two development branches carried different record APIs | Both formats and both project call orders were kept; Phase 4 water fields and error histories survive a round trip | Record and phase4/progress regressions |
| Unconverged seepage was passed into the mechanical stage | `SolverError` before the mechanical solve starts; the flow itself can be diagnosed with `converged=False` | Forced failed Picard test |
| Singular/isolated seepage, conflicting head boundaries, and invalid control values | A hydraulic reference for every connected region, finite/positive conductivity, and value checks; singular/NaN solutions are rejected | Disconnected-region, boundary, and control tests |
| The velocity field was taken from the next Picard conductivity, the discharge from the previous matrix | Every output is tied to the same solved conductivity/matrix state | Analytical velocity/discharge comparison, W1–W3 |
| In HB, stress was clipped to the apex even when ψ=0 and the mean tension was above the apex | Non-negative cone of the six MC-type potentials; a return that cannot be found rejects the batch. A valid fixed-apex tangent is exactly zero | Volumetric flow, input preservation, apex derivative; C3 |
| The memory of a singular HB two-surface matrix could be used before it was initialised | The matrix is zero-initialised; a singular tangent is rejected | HB return/tangent tests |
| A local MCC `LinAlgError` could skip the global step-rollback path | Local Jacobian/tangent singularity is raised as `LocalIntegrationError`; shared material error family | MCC C1/C2 and input regressions |
| Invalid Kw/n, hydraulic tuples, and MCC pressure scales could be accepted | Finiteness/size/positivity checks; for method B, φ=0 and a suitable strength model | Parameter regressions |
| New residual backtracking silently switched full NR onto the committed matrix | The full NR/step-cut path from PR #1 was kept; optional line search is present. Tolerances were not changed | P5 tension plateau failed before the fix and passed after; C1/C2/S4 kept |
| Excavated cells remained in the view/VTU, and NaN Gauss points corrupted neighbouring nodal stresses | SPR/averaging and output use the active topology; an unused-node NaN is not turned into zero | Finite field at the excavation boundary and VTU/PyVista equality |
| A plastic stiffness with an entirely zero row/column produced BLAS parameter messages in SuperLU | Finite-value and zero row/column checks before factorisation; the input matrix is preserved | No BLAS message on the P4 repeat; direct matrix regression |
| Rounding of a constant stress produced a false colour difference on screen | A colour range below a relative 1e-10 is a single colour; the numerical result is not changed | Native interface test and screen check |

No new tension potential was added to Hoek–Brown. A hydrostatic trial that volume-preserving
flow at ψ=0 cannot reach now raises an explicit error; a different flow, if wanted, has to
be named and verified separately. There is no claim of automatic identity with the HB
options of external programs.

## Verification

**Final local run: 397 passed, 1 strict xfail, 2 benchmarks excluded; 86.42 s.**
The PySide6 and PyVista tests ran; no module was skipped. Ruff, `git diff --check`,
the desktop `--help` command, and the wheel build succeeded. No BLAS parameter error
message appeared. The benchmark gate and the Windows portable build were not verified
in this run.
Test tolerances were not relaxed.
The old incorrect MC test checks the explicit Rankine option and the rejection of the
model without a tension cut-off separately, instead of requiring the flow rule to be
violated. The ψ=0 HB random acceptance test runs in mean compression; the tension
barrier is protected by a separate rejection test.

Environment: Linux x86-64, Python 3.12, NumPy 2.3.5, SciPy 1.17.0, Numba 0.68.0,
h5py 3.16.0; Qt offscreen and PyVista installed. A local Windows run was not done in
this environment; that is the CI matrix’s job.

```bash
ruff check src tests
QT_QPA_PLATFORM=offscreen OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
  PYTHONPATH=src python -m pytest -q -m 'not benchmark'
python -m pip wheel --no-deps . -w /tmp/fea-dist
```

**The S4 external comparison was deferred. Legacy uncut P4 is a strict xfail. Gate 5 and v1.0 are open.**
