# F7 — Numerical verification acceptance matrix

**Status:** F7 is in progress. This is an independent numerical-verification
workstream, not a claim of RS2/PLAXIS agreement. A green CI is necessary but
does not establish engineering accuracy on its own.

## Verification levels

| Level | Purpose | Acceptance |
| --- | --- | --- |
| V1: element/patch | Constant-strain response, quadrature and Jacobian | Exact within floating-point tolerance, every supported element |
| V2: continuum analytic | Constrained elastic column, surface load, settlement | Agreement with constrained modulus and global reaction balance |
| V3: staged elastic | Load accumulation and displacement reset | Superposition, reactions and reset semantics |
| V4: constitutive | Mohr–Coulomb, Rankine, Hoek–Brown, Modified Cam-Clay | Analytic yield states, return mapping, algorithmic tangent; loading/unloading |
| V5: excavation/support | Tunnel/bench/invert, anchors, liners, point and interface loads | Stage activation and equilibrium, mesh independence |
| V6: external comparison | Published RS2/PLAXIS, sheet pile, tunnel and slope benchmarks | Inputs and conventions documented; differences quantified and explained |

## New benchmark: constrained elastic column

Width W=4 m, height H=8 m, E=20,000 kPa, nu=0.30,
and uniform vertical compression q=120 kPa. This is **not** a
consolidation settlement computation; it is a drained linear elastic
plane-strain continuum with zero body force.

Side rollers imply epsilon_x=0; plane strain implies epsilon_z=0. Therefore

    M = E (1 - nu) / ((1 + nu) (1 - 2 nu))
    uz(top) = -q H / M
    Ry(bottom) = q W

The reference displacement is approximately -0.035657142857 m
(check the expression, not a rounded hard-coded target). A second load
stage increases the prescribed surface pressure to 240 kPa and should
double both the response and reactions.

The new verification suite covers T3, T6, Q4 and Q8 with two mesh
resolutions (2x4 and 4x8 mapped cells), plus incremental loading
checks for T6 and Q8. It uses explicit, independent analytical
formulas rather than comparing two outputs of the same numerical solver.

## Engineering release gate (not yet satisfied)

The following must be demonstrated independently:

- Convergence diagnostics for plasticity under excavation and staged loads,
  including explicit residual norms and plastic strain state rollback.
- Reference geotechnical cases with documented material parameters, initial
  stress and groundwater assumptions; no undocumented calibration to outputs.
- Mesh refinement at least three levels per problem, with support forces,
  displacements and stresses assessed separately.
- Distinction between mathematical singularities/point loads and true
  element inversion.
- Verification of effective stress vs total stress, load units, axisymmetric
  scaling and drainage conventions.
- Results checked on Windows and Linux and stored as reproducible reports.

F7 completion is separate from merging a partial verification PR.
