# Verification — Gate 1 (Phase 1), Gate 2 (Phase 2), Gate 3 (Phase 3), and Gate 4 (Phase 4)

**Current review:** [Phase 4 fixes](phase4-review.md),
[Phase 5.1](phase5-desktop.md). There is no S4 external comparison ([format](s4-external.md)); Gate 5 is open.
The numerical tables below are records of earlier runs; the current regression result
is in the review record.

All tests run as pytest under `tests/verification/`; the performance criterion is under
`tests/benchmarks/` (`pytest -m benchmark`).

| Code | Test | Reference | Criterion | T6 result | T3 result |
|---|---|---|---|---|---|
| E1 | Patch test — displacement (distorted mesh, 2 seeds), traction (boundary stresses), axisymmetric; T3, T6, Q4 (B-bar), Q8 | Constant unit strain | < 1e-10 | ✔ machine precision | ✔ machine precision |
| E2 | Cantilever beam, with continuum elements | Exact Timoshenko–Goodier solution (Augarde & Deeks 2008); E′, ν′ for plane strain | Tip deflection < 1% | 0.0001% (40×4) | 0.87% (160×16) |
| E3 | Plate with a circular hole, biaxial far-field stress (σx = 1, σy = 0.4) | Kirsch; the exact traction is applied on the outer boundary | σθ on the rim < 1% | 0.27% | 2.1% (the criterion is 3% for T3) |
| E4 | Thick-walled cylinder, internal pressure, axisymmetric, εz = 0 | Lamé | σr, σθ < 1% | 0.03% | 0.01% |
| — | Elastic T6 model with 50k nodes (gravity + a load stage) | — | < 5 s | 1.9 s | — |
| — | Unstructured mesh: tunnel section, T6 with ~51k nodes (mesh generation + solve) | — | solve < 5 s | mesh 2.8 s, solve 3.2 s (55k, Phase 2 measurement); 4.9 s (51k, Phase 3, a slower 2-core environment) | — |

### Repeat on unstructured (Delaunay + Ruppert) meshes

| Code | Mesh | Result |
|---|---|---|
| E1 | Domain with a hole and an embedded line; T3 and T6 | machine precision |
| E3 | Quarter plate, a hole of 48 edges, a graded size field toward the hole; T6 | σθ error 0.20% |
| E4 | Annular section, h = 0.1; T6 | within 1%, u_r < 0.5% |

Measurement environment: Linux x86-64, Python 3.13, NumPy 2.5, SciPy 1.18 (SuperLU). If
`pypardiso` is installed, the solver switches to PARDISO automatically.

## Notes

* **E1 — Q4/Q8:** added in Phase 2; Q4 (B-bar) and Q8 pass all four patch tests.
  E2 (cantilever) is also within 1% with Q8 40×4 and Q4 80×8.
* **E2:** the exact displacement field is applied at the fixed end, and a parabolic
  shear stress at the free end; the comparison is therefore independent of the
  encastre idealisation. It is also checked to within 1% against Timoshenko beam theory with κ = 5/6.
* **E3:** the error is measured on the stress carried to the node (linear extrapolation
  to the corners + averaging); the field error is also checked at every Gauss point. SPR
  (Phase 2) will improve the T3 nodal values.
* **E4:** σr, σθ, σz are compared at the Gauss points and u_r at the nodes; the sum of
  the vertical reactions is zero.

## Mesh generator (Delaunay + Ruppert) unit tests

`tests/unit/test_unstructured_mesh.py` — the domain matching the input polygon exactly,
the minimum-angle target (28–30°), conformity to the size field and grading, T6 midside
nodes, region labelling (nested polygons, a hole, override by a seed, a polygon-based
domain boundary), embedded lines kept as a complete edge chain, a shared node of
intersecting lines, name union of shared edges, a T-junction and coincident segments,
termination at narrow input angles (3°–4°) with quality dropping only in the angle set,
determinism, and error cases.

## Additional unit tests

### Same-degree mixed meshes (experimental)

T3+Q4 and T6+Q8 transitions are checked with shared nodes. Plane and axisymmetric patch
tests on a distorted mesh, traction with default/high integration, and the E2 cantilever
solution pass. The scope of the plastic Tresca compression, excavation/backfill,
liner/interface, water, and record tests, and the failures that remain on the nonlinear
sheet pile, are described in [mixed-mesh.md](mixed-mesh.md). This addition does not close Gate 3.

`tests/unit/` — shape-function derivatives (by finite difference), quadrature exactness,
symmetry of the element stiffness and exactly 3 rigid-body modes, mesh geometry (area of
a plate with a hole, layer regions), coincidence of a gravity analysis with the K₀ field
in a laterally restrained column (one and two layers), stage increment/displacement reset,
reaction balance, material change, prescribed displacement, detection of a singular
system, JSON round trip, and VTU validity.

## Gate 2 — elasto-plastic solver (Phase 2)

| Code | Test | Reference | Criterion | Result |
|---|---|---|---|---|
| P1 | Rigid smooth strip footing, undrained (φ = 0), displacement-controlled, weightless | Prandtl, q_ult = (2 + π) su | < 3% | 0.97% (h_min = 0.05); 1.35% / 0.53% (0.1 / 0.025) — converging from above |
| P2 | Thick-walled cylinder, internal pressure, Tresca, εz = 0 | Hill (1950): p(r_c), u_b = 2(1−ν²)k r_c²/(E b) | Pressure–expansion < 2% | T6 0.004%; Q8 and Q4 (B-bar) also within 2%; plastic radius by GP flags |
| P3 | Circular tunnel in hydrostatic stress, MC, ψ = 0 / 15° / 30° | Salençon (1969) plastic radius; wall displacement from the flow-rule ODE | < 3% | u_a 0.43–0.57%, R_pl 0.4% |
| P4 | Homogeneous slope 2:1, c/γH = 0.05, φ = 20°, ψ = 0, SRF; explicit Rankine-apex flow | Griffiths & Lane (1999) Ex. 1; Bishop (circular search in the test: 1.378) | FS difference < 3% | Passed with the explicit model completion: h=1.5 F=1.396484, h=1.0 F=1.376953; the legacy uncut model is a separate strict xfail |
| P5 | Single-element (axisymmetric) triaxial compression, a tension path, tension cut-off; MC ψ ≠ φ | Closed-form stress trace and volumetric behaviour | < 0.1% | at rounding-error level |
| — | Full NR quadratic convergence (associated Tresca; non-associated MC → unsymmetric LU) | slope of log r_{i+1} – log r_i ≈ 2 | slope > 1.6 | ✔ (e.g. 1.8e-2 → 8.8e-7 → 3e-13); mNR linear (slope ≈ 1) |

Also: NR, mNR, hybrid, initial stiffness, and NR + line search reach the same solution
to a relative difference of 1e-5 (`test_newton_convergence.py`).

The 3% criterion and the mechanism check of P4 are kept on the explicit Rankine-apex
model. On the legacy model without a cut-off, a strict xfail is applied only for the
local material error; that is not a pass. This limit inside the general Gate 2 scope is
kept. Method, the exact/approximate tangent split, and the comparison:
[coincident-tension-cutoff.md](coincident-tension-cutoff.md).

### Constitutive-model unit tests (`tests/unit/test_materials.py`)

* Mohr-Coulomb (+ tension cut-off, non-associated flow, φ = 0, c = 0): every return is
  admissible; for associated flow the nearest point in the energy norm is checked with
  SLSQP; the consistent tangent is within a relative 1e-5 of finite difference on plane
  and edge returns.
* Drucker-Prager / von Mises: tangent by finite difference; von Mises hardening against
  the closed form.
* Sloan substepping: within 0.5% of the closed-form return on a fine path, converges to
  the reference as STOL is reduced on a large single increment, elasto-plastic unloading–reloading.

### Stress recovery (SPR)

SPR reproduces polynomial fields of its own degree (T3/Q4 linear–bilinear, T6/Q8
quadratic), including at boundaries, to machine precision; it does not smear a jump at
a region boundary. On the Kirsch (T6) problem the RMS error in the interior is about
25–30% lower than averaging; because extrapolation-averaging is more accurate on the
outer boundary of the mesh, the default hybrid method uses it there.

## Gate 3 — staged construction and structural elements (Phase 3)

| Code | Test | Reference | Criterion | Result |
|---|---|---|---|---|
| S1 | Lined circular tunnel in elastic soil, K = 0.5, liner simultaneous with excavation (no relaxation); Timoshenko BEAM2 liner, a Goodman interface in the full-slip case | Einstein & Schwartz (1979) interaction solution (derived explicitly in the test) | Liner N and M < 5% | no-slip: N₀ 0.02%, N₂ 0.18%, M₂ 0.11%; full slip: N₀ 0.13%, M₂ 0.07% |
| S2 | Pretensioned end-anchored bolt, elastic block, out-of-plane spacing s = 1, 2 | Series-spring equilibrium N = T₀/s · k_s/(k_s + k_b) | < 0.5% | 1e-9 (exact for linear springs); yield limit and deactivation |
| S3 | 3-stage excavation in an elastic layer; load split α = 0.25 / 0.4 / 0.9 + completion | Equivalent single-stage solution | Difference < 10⁻⁸ | 5e-15 (multi-stage), 2e-15 – 6e-15 (load split); first stage α·u |
| S4 | Cantilever sheet pile in sand (H = 4 m, D = 6 m, two-stage excavation, an interface with R = 0.67 on both faces) | Its own beam–spring (Winkler, K₀ → Ka/Kp, Lancellotta 2002, staged) and LE (Blum, free tip) | M_max < 10% | FE 71.8 / 72.2 / 73.8 kNm/m (h = 0.5 / 0.35 / 0.25), beam–spring 78.5, LE 78.2 → 6–9%; M_max depth 5.1 m (beam–spring 5.2 m); head displacement −30 mm (beam–spring −32 mm) |
| S5 | Equivalent shotcrete+mesh+steel-set beam, nu = 0, cantilever tip load and axial tension | Timoshenko: w = PL³/(3EI) + PL/(GAs), u = NL/EA | relative 1e-8 | rounding |
| S6 | A row of piles, two faces, c = T_skin/(2s), rigid axial translation | Holding force = (T_skin/s)·L | relative 1e-3 | closed form |

The Winkler/LE model in the S4 row is an **internal comparison**. There is no RS2/PLAXIS
result in the repository; this gate is not considered passed until the file arrives
([s4-external.md](s4-external.md)).

**Stage-split invariance** (extra Gate 3 requirement): in S3, one stage = n stages and
one stage = load split + completion, at rounding-error level in an elastic material.

### Regression tests (`tests/unit/test_stage_regressions.py`)

* A passive interface = full continuity: duplicated nodes are tied; models with and
  without an interface agree to within 1e-9; reactions are not double-counted on tied
  nodes. On a wall with an interface on both faces, the tie is transitive through the
  unused wall nodes.
* An activated interface inherits the traction of the neighbouring soil (no stress release).
* In a load-split stage the reactions are in balance with `λ f_ext + (1 − λ) f_previous`.
* SRF also reduces the interface strength: on a block above a c = 0 interface on a 20°
  inclined plane, FS = tan φ / tan β, within 2% (φ = 30°, 35°).

### HDF5 and the project file (`tests/unit/test_io_project.py`)

A model that contains every Phase 3 feature (a wall, two interfaces, a pretensioned
anchor, a change of water level, load split, a load on a partly excavated surface): the
HDF5 round trip of the results is bit-identical; the analysis of the model loaded from
`.ssproj` repeats to within 1e-12.

### Known limitations

* **Smooth wall + nearly cohesionless soil:** the S4 model does not converge in sand with
  an R → 0 (frictionless) interface and c ≤ 1 kPa: a near-surface soil strip whose
  strength is ~0 can slide along the frictionless wall (a local mechanism). It solves
  with R ≥ 0.3 or c ≈ 5 kPa. To separate interface stiffness from strength,
  `InterfaceSpec.from_soil(R_stiffness=1)` should be used; otherwise the stiffness scales
  with R² and at R = 0.01 the wall floats in the soil.
* Plastic excavation stages can need 5–8 iterations per step in full NR;
  `SolverSettings(line_search=True)` speeds this up noticeably (S4: 44 s → 22 s).
* Arc-length was not implemented. Non-convergence at the step lower bound is only a
  numerical failure; it is not, by itself, proof of physical collapse.

## Gate 4 — seepage, undrained analysis, and advanced constitutive models (Phase 4)

| Code | Test | Reference | Criterion | Result |
|---|---|---|---|---|
| W1 | Confined flow under a sheet pile, a layer of T = 10 m, S/T = 0.3 / 0.6 / 0.8 | Harr (1962) conformal mapping, q/(kH) = K(m′)/2K(m) | Discharge < 2% | 0.2% – 0.6% |
| W2 | Rectangular dam, free surface + seepage face, two van Genuchten sets | Dupuit–Forchheimer discharge (Charny 1951, exact for the discharge) | < 3% | 1.2% – 2.0% (flow in the unsaturated zone; it decreases on a steep vG curve) |
| W3 | Zero-gradient seepage (the same head everywhere) | Hydrostatic pressure of the equivalent phreatic line; the whole staged analysis | < 10⁻⁸ | < 10⁻⁸ (pore water, stress, displacement) |
| C1 | MCC drained triaxial compression, NC, p₀ = 200 kPa, εa → 15% | Tight-tolerance ODE integration of the MCC rate equations on the drained path | q–εa < 1% | largest 0.48% (first steps), 0.06% at εa = 15% |
| C2 | MCC undrained triaxial compression, method A (Kw/n = 100 K′) | Closed-form effective stress path p′/p₀ = (M²/(M²+η²))^Λ (including the logarithmic elastic shear) | p′–q < 2% | 0.13%; total mean stress p′ + p_excess = p₀ + q/3 (10⁻⁸) |
| C3 | Circular tunnel in a generalised Hoek–Brown rock mass (GSI 40, mi 10, σci 20 MPa, p₀ 10 MPa, pᵢ 0.5 MPa), ψ = 0 / 10° / 20° | A Carranza-Torres (2004) type solution, derived explicitly in the test (closed form in the plastic zone, displacement from the flow-rule ODE) | Wall displacement < 3% | 1.1% / 1.3% / 1.6%; plastic radius 0.3–0.4% |

The drift in C1 is a first-order time-integration error from freezing the hypoelastic
shear modulus at the start of the step (it halves when the step is halved). Most of the
drift in C3 comes from the finite (traction-loaded) outer boundary at 25a: with 50a and
pᵢ = 0 it goes from 2.5% to 1.8%.

### Undrained analysis (`tests/unit/test_undrained.py`)

* Oedometer loading, methods A and B, default and given Kw/n: excess pore pressure
  Q·Kw/(Kw + Dc), effective stress, and settlement within 10⁻⁸ of the closed form; then,
  with `Stage(drained=True)`, the excess pore pressure dissipates and the drained
  settlement Q·H/Dc is obtained.
* Method C: no pore pressure, total vertical stress γ_sat·z (+Q).
* Excess pore pressure is written to HDF5; `Stage.drained` is kept in the project JSON.

### Constitutive-model unit tests (Phase 4)

* MCC: on the yield surface after the return (10⁻⁸), consistent tangent within 10⁻⁵ of
  finite differences, hardening frozen on elastic unloading.
* Hoek–Brown: three parameter sets (ψ = 0, 5°, 10°), returns on the main surface, two
  edges, and the apex (tensile strength); yield condition 10⁻⁸·σci, σ1 ≤ σt, consistent
  tangent within 10⁻⁴ of finite differences, the return is idempotent.

### Phase 4 known limitations

* In undrained MCC, near the surface where p′ ≈ 0 the undrained strength is also ≈ 0;
  a surface footing may not converge at small loads; physical collapse needs separate evidence.
  The small shear in logarithmic elasticity gives a finite stiffness at p′ = 0 only through
  `p_min` (default 1 kPa).
* SRF (strength reduction) is applied to MC/DP and to interfaces; Hoek–Brown and MCC are not reduced.
* Consolidation (time-dependent) is in the v2 scope; in v1, undrained → a `drained=True`
  stage gives only the end states.
