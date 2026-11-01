# Explicit tension cut-off and a coincident apex

`MaterialSpec.mohr_coulomb(..., sig_t=0.)` now keeps an explicitly given Rankine
tension potential even when c=0. The previous `sig_t >= apex` condition disabled that
choice when the cut-off plane coincided with the MC apex. `sig_t=None` does not add a
cut-off potential; that default was not changed. A cut-off plane above the apex is
still disabled, because it is not active inside the MC region.

`MaterialSpec.mohr_coulomb(..., rankine_at_apex=True)` explicitly selects the same
associated Rankine flow at the existing MC apex. It is not given together with a
numerical `sig_t`; it requires φ>0. This option recomputes the limit on every SRF
model and uses exact equality `sig_t=apex`. Because `c/F` and `tanφ/F` are reduced
together, the analytical apex does not change; a comparison of two separate
floating-point evaluations is still not required. The default `False` keeps the old
MC flow. The option is stored in the model/result record.

## Method and local checks

Clausen–Damkilde (2006), *A simple and efficient FEM-implementation of the Modified
Mohr-Coulomb criterion*, describes the union of the MC and Rankine surfaces, with
non-associated flow for MC and associated flow for Rankine. The return and the tangent
are computed in principal-stress space. [Source PDF at the authors’ university](https://vbn.aau.dk/ws/portalfiles/portal/5145833/ClausenDamkilde.pdf),
in particular Eqs. 1–6 and 16. The coincidence check below is a local implementation
check derived from those equations; the paper is not claimed to have verified this software.

At the point σt = c·cotφ, six MC potentials and three Rankine potentials are active
together. In a corner return, the admissible correction cone spans these nine
directions. Trying only the three Rankine directions can miss mixed shear/tension
corrections. The coincidence test is based on the difference of the surface parameters
at machine precision, not on the magnitude of the trial stress.

For ψ=0 the MC corrections are isochoric. If the mean trial stress is above the common
apex, Rankine volumetric flow is required. σ1=σt=apex together with MC admissibility
requires σ2=σ3=apex. The stress in this region is constant; its tangent is exactly zero.
The old 1e-8·D corner stiffness was removed. When unloading starts from this zero
tangent, the first Newton predictor uses the elastic matrix if the previous state’s
matrix is singular. In later NR iterations the real material tangent is used; a singular
iteration tangent is not replaced by the elastic matrix by default.

## Early apex return and optional iteration stiffness

In the core, analytical active-set candidates in principal stress are tried instead of
a local Newton loop. Before the standard plane/edge candidates there is this special
check: ψ=0, φ>0, the explicit Rankine limit coincides with the MC apex, the trial has
yielded, and the trial mean is at or above the apex. It is also checked that the
correction is a non-negative combination of the six MC and three Rankine potentials.
If it is accepted, the four-component stress `(apex, apex, apex, 0)` and an exactly
zero tangent are returned. Rounding of `cos²+sin²` in the transformation of an
isotropic constant stress is also avoided.

The mean-stress condition alone is not a general apex test: for example, with c=10,
φ=30°, ψ=5°/30° and trial principal stresses (300,−100,−110) kPa, the mean is above
the apex but the admissible return is onto the shear surface. A regression test
prevents a wrong apex clip in these cases. A lower Rankine cut-off does not use this
early block either. If the flow was not selected, the local error is kept.

Inside the fixed return region `dσ/dε=0`; at a surface transition the classical
derivative may not be unique. `ε·D_elastic` is **not** the consistent derivative of
this fixed return. The requested numerical option is kept separate with
`SolverSettings(apex_stiffness_ratio=1e-6)`:

- Only for Gauss points at the MC apex, with the plastic flag set and an exactly zero
  tangent, `ratio·D_elastic` is used for the Newton factorisation matrix. Other Gauss
  points/structures are unchanged.
- Stress, internal variables, internal force, the acceptance criteria, and the stored
  real material tangent do not change. Elastic corners, or lower Rankine corners, are
  not affected.
- `0` is the default; when it is off, the exact tangent is used. The active option is
  an approximate Newton matrix; it does not guarantee global non-singularity, good
  conditioning, or equilibrium.
- The last accepted tangent report inside `--audit` belongs to the real tangent; when
  the option is on it must not be assumed to be the same as the approximate matrix
  that was factored.

The recorded P4/sheet-pile inputs return to an admissible apex stress with the explicit
option. An independent NNLS decomposition confirms non-negative multipliers on the
MC/Rankine potentials and the required positive total Rankine multiplier. The real
tangent is checked by finite difference; the scope of the approximate matrix, invariance
of the input arrays, and the load–unload–reload path at 0/1e-8/1e-6/1e-4 are checked
separately.

## P4: explicit Rankine-apex model

```bash
PYTHONPATH=src OPENBLAS_NUM_THREADS=1 python examples/slope_strength_reduction.py --rankine-at-apex --output /tmp/p4-exact.json
PYTHONPATH=src OPENBLAS_NUM_THREADS=1 python examples/slope_strength_reduction.py --rankine-at-apex --apex-stiffness-ratio 1e-6 --output /tmp/p4-approximate.json
```

E=100000 kPa, ν=0.3, c=10 kPa, φ=20°, ψ=0, γ=20 kN/m³; the previous geometry,
supports, and tolerances are kept. A failed local return cannot be counted as an SRF
collapse bound. The flow added here is only at the MC apex; the elastic stress region
of MC is not narrowed. A different soil with zero tensile strength was not selected.

| h [m] | Nodes | Apex iteration factor | Accepted F | Failed upper F |
|---:|---:|---:|---:|---:|
| 1.5 | 1259 | 0 | 1.396484 | 1.406250 |
| 1.5 | 1259 | 1e-8 | 1.396484 | 1.406250 |
| 1.5 | 1259 | 1e-6 | 1.396484 | 1.406250 |
| 1.0 | 2539 | 0 | 1.376953 | 1.386719 |

There is no local rejection in these runs. On the coarse mesh with the exact tangent,
singular global-matrix rejections were seen on the upper trials; at 1e-6 the rejections
were residual stall. Both approaches gave the same lower/upper bracket. The timings
are not a performance criterion. Two mesh levels are not proof of full mesh
convergence, or of factor independence on every model.

`test_slope_factor_of_safety` keeps the previous 3% Bishop, ≤0.01 bracket, and
mechanism-location criteria for h=1.5 exact/1e-6 and h=1.0 exact tangent; admissibility
of the accepted stresses on the reduced yield surface is checked as well.
[Griffiths–Lane (1999), the author’s source](https://inside.mines.edu/~vgriffit/slope64/Griffiths%20and%20Lane%201999)
Example 1 reports a Bishop value of 1.38 and an FE pass around 1.4. This is not a claim
that the original authors used the same apex flow; it is a comparison of our explicitly
documented model completion. The legacy test without a cut-off remains a strict xfail
under the name `test_legacy_slope_without_rankine_apex_flow`.

`test_mc_coincident_cutoff.py`: analytical apex stress, admissibility, and a zero
tangent by finite difference on c=0/10 kPa, hydrostatic, and mixed tension/shear
paths; the error is kept when no cut-off is given; associated MC corner tangent.
`test_coincident_tension_path.py`: analytical stress path and force balance with
T3/T6/Q4/Q8 from initial compression into tension, elastic unloading, and reloading.
In this test the nodal values that impose a homogeneous strain are applied while
leaving one free horizontal DOF at the centre; the singularity of a general free
plastic tension field is not hidden. The scope of the return for the Newton predictor
is limited by separate unit tests.

## Explicit material choice on the sheet pile

The sheet-pile numerical records in this document were taken before the embedded-tip
connection of the two-sided interface was fixed. The old model split the tip on the
second side that was added; the current code keeps the tip shared on both sides. The
old values are diagnostic history; the current model and the replays are in the
[S4 protocol](s4-comparison.md).

```bash
PYTHONPATH=src OPENBLAS_NUM_THREADS=1 python examples/compare_sheet_pile_meshes.py --sizes 0.5 0.25 --gauss-order high --soil-tension 0 --csv /tmp/pile-cutoff-high.csv
```

`--soil-tension 0` enables the associated tensile flow chosen by the user; if the
parameter is omitted, the legacy model without a cut-off is kept. The CLI records this
choice in the CSV/JSON diagnosis. The soil E, ν, c, φ, ψ, and γ, the interface, the
boundaries, and the tolerances do not change. Even so, tensile flow is a different
material definition; it cannot be presented as the verified solution of the previous
model without a cut-off.

Before the tip fix, all four high-integration runs completed the excavation up to λ=1:

| h (m) | Mesh | Maximum \|M\| (kNm/m) | Maximum nodal \|u\| (m) |
|---|---|---:|---:|
| 0.50 | T6 | 164.401016 | 0.04105281 |
| 0.50 | T6+Q8 | 163.801169 | 0.03965327 |
| 0.25 | T6 | 167.731475 | 0.04239181 |
| 0.25 | T6+Q8 | 167.943773 | 0.04199557 |

On the fine mesh the moment difference is 0.127% and the maximum displacement-norm
difference is 0.935%. The coarse/fine moment change is 2.03% for T6 and 2.53% for the
mixed mesh. Agreement of two mesh levels is not full mesh convergence or independent
verification. Runtimes of a single machine are not used as a performance guarantee.

The independent-tool reference for S4, and the legacy uncut load path for P4, are still
open. The explicit Rankine-apex scope of P4 is separate above; Gate 3 was not closed.

The new explicit apex choice, with an iteration factor of 1e-6, also reached λ=1 on
the h=0.5 mixed/high sheet pile: maximum |M|=163.801169 kNm/m, maximum nodal norm
0.039653270 m, local rejection count 0. In this c=0 model the apex is already 0; the
result agrees with the explicit σt=0 run above. This repeat is not an independent S4 reference.

```bash
PYTHONPATH=src OPENBLAS_NUM_THREADS=1 python examples/diagnose_sheet_pile.py --size 0.5 --mixed --gauss-order high --rankine-at-apex --apex-stiffness-ratio 1e-6 --output /tmp/pile-apex.json
```
