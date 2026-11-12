# External RS2 / PLAXIS benchmark suite

This suite reproduces **official published tutorial or validation problems** with
SlipSurfaceIQ-FEA. It is deliberately separate from internal patch tests. A benchmark
may pass only when its published geometry/material/staging assumptions are reproduced;
unsupported constitutive models are not silently replaced.

Passing individual benchmarks supports the stated feature domains. It does **not** mean
that SlipSurfaceIQ-FEA is globally equivalent to or certified by RS2 or PLAXIS.

## B1 — RS2 Introduction / Surface Excavation

Official source: Rocscience RS2 Introduction tutorial.

Coverage:
- plane strain;
- elastic continuum;
- K0/self-weight equilibrium;
- staged tunnel excavation;
- staged surface trench excavation;
- surface pressure;
- displacement field and mesh convergence.

Published approximate maximum total displacements are 3.0, 4.7 and 18 mm for the
three tutorial stages.

Acceptance:
- each finest-mesh maximum within 5% of the published approximate value;
- medium-to-fine change within 2%;
- maximum locations remain in the documented tunnel/trench/load regions.

Current verified CI result: **PASS**. Finest differences are approximately 2.76%,
0.83% and 1.20%. This benchmark is a strict `--require-pass` CI gate; a numerical
regression in the published-value, mesh-convergence or location checks fails the
`external-benchmarks` workflow.

## B2 — PLAXIS Tutorial 01A / Rigid circular footing

Official source: Bentley PLAXIS Tutorial 01, Case A.

Coverage:
- axisymmetric mechanics;
- drained Mohr-Coulomb plasticity;
- hydrostatic water line and K0 initial state;
- prescribed rigid footing displacement;
- support reactions and axisymmetric per-radian-to-full-circle conversion;
- nonlinear mesh convergence.

The tutorial prescribes 50 mm indentation and publishes a total reaction of about
588 kN.

Acceptance:
- finest reaction within 10% of the published approximate value;
- medium-to-fine reaction change within 2%;
- the prescribed 50 mm settlement is retained uniformly over the rigid footing.

Current verified CI result: **PASS**. Finest reaction is about 632.74 kN
(7.61% difference); medium-to-fine change is about 0.36%.

The model explicitly uses zero tensile strength because the PLAXIS Mohr-Coulomb
tension cut-off is active for this tutorial/default material behaviour. The first
attempt without this equivalence did not converge and is not counted as a pass.

## B3 — PLAXIS phi-c reduction / Bishop validation

Official source: Bentley PLAXIS Validation & Verification, “Phi-c reduction and
comparison with Bishop's method”.

Coverage:
- plane-strain Mohr-Coulomb slope;
- associated flow;
- gravity initialization;
- surcharge;
- shear-strength reduction;
- failure bracket and mesh convergence.

Published references:
- unloaded PLAXIS FoS = 1.57;
- loaded (30 kPa) PLAXIS FoS = 1.25;
- unloaded Bishop FoS = 1.564.

Acceptance:
- finest FoS within 5% of both applicable published references;
- medium-to-fine FoS change within 2%;
- SRF bracket width <= 0.011.

Current verified CI result: **PASS**.

Coarse / medium / fine FoS values are:
- unloaded: 1.566 / 1.557 / 1.548;
- loaded 30 kPa: 1.2375 / 1.230 / 1.230.

The finest differences are approximately 1.40% from PLAXIS 1.57, 1.02% from
Bishop 1.564, and 1.60% from loaded PLAXIS 1.25. Medium-to-fine change is about
0.58% unloaded and 0% loaded.

This benchmark also exposed an SRF initialization defect: on a fine plastic mesh,
F=1.0 (no strength change) was being re-projected and re-solved, allowing tiny
projection imbalance to create a false failure bracket below 1.0. F=1 is now treated
as the already accepted identity base state; reduced-strength trials still execute
normally for F>1. The full standard/F7 regression suite remains required.

## B4 — PLAXIS Drain / Dupuit groundwater flow

Official source: Bentley PLAXIS Drain verification, with Dupuit's analytical
unconfined-flow solution as an independent closed-form reference.

Coverage:
- steady plane-strain saturated/unsaturated seepage;
- prescribed external head and internal drain head;
- seepage/open boundaries;
- integrated discharge;
- global mass balance;
- hydraulic mesh convergence.

Published/reference one-side discharge:
- Dupuit analytical: **4.480 m3/day/m**;
- PLAXIS 2D: approximately **4.489 m3/day/m**.

Acceptance:
- finest one-side discharge within 1% of Dupuit;
- finest one-side discharge within 1% of PLAXIS 2D;
- medium-to-fine discharge change within 1%;
- relative global flow-balance residual <= 1e-8;
- solved total-head extrema remain 10 m and 18 m.

Current verified result: **PASS**. Fine-mesh discharge is approximately
**4.49162 m3/day/m**, differing by about 0.259% from Dupuit and 0.058% from
PLAXIS 2D. Medium-to-fine change is about 0.083%; the fine relative global
flow-balance residual is of order 1e-15.

This benchmark is enforced by the dedicated `plaxis-drain-benchmark` workflow
with `--require-pass`.

## B5 candidate — RS2 Anchored Sheet Pile Wall

Official source: Rocscience RS2 Anchored Sheet Pile Wall tutorial and its scripting
variant. The public input lock is maintained in
[rs2-anchored-sheet-pile-b5.md](rs2-anchored-sheet-pile-b5.md).

Published response checks include approximately **59 kN** maximum axial force in the
lower tieback and approximately **71 kNm** maximum wall bending moment in the current
online tutorial. Geometry, stages, wall/joint properties and tieback properties are now
recorded from the official pages, including the 40% bonded length and the specified
bond shear stiffness/strength.

A new mesh helper can represent the free length followed by a *perfectly bonded* tail
without falsely treating the full tieback as grouted. That is a topology prerequisite,
not RS2 equivalence: the official tieback uses finite grout bond-slip stiffness and
strength, while the current shared-node bonded tail imposes zero slip.

The scalar finite axial grout bond-slip **constitutive law is now independently
verified** and protected by the dedicated `b5-bond-slip` workflow. This closes the
local material-law prerequisite only; it does not make the shared-node perfect-bond
topology equivalent to the RS2 tieback.

The bonded-length solver formulation is now independently verified by the strict
`b5-embedded-bond` workflow. Its BOND4 formulation uses host-continuum motion plus an
internal axial-slip field and matches a closed-form elastic shear-lag reference with
monotone mesh convergence; the 32-segment head-reaction error is about 0.0217%.

This case is therefore **not yet a benchmark pass**. Two strict blockers remain:

- Material 1 Young's modulus and friction angle are inherited from the installed
  tutorial starting model and are not set by the current public scripting page.
- The RS2 tieback's unbonded length and pretensioned wall-head connection still need a
  solver-level series formulation and independent verification with the bonded BOND4 tail.

B5 becomes a strict external gate only after those inputs and the complete tieback series
system are captured. The 59 kN / 71 kNm values must not be used to tune guessed soil
properties or an incomplete support model.

## Advanced S4 — exact custom sheet-pile comparison

The existing S4 problem remains an advanced external comparison. It is not replaced
by the tutorial suite. Real RS2/PLAXIS results for the locked S4 case must still be
provided through `docs/data/s4/external.csv` and `external-meta.json`. The current
10% independent maximum-moment criterion is unchanged.

## Explicit exclusions

PLAXIS Tutorial 02 (road embankment) is **not** currently a like-for-like benchmark:
the official tutorial uses the Hardening Soil model, which is outside the present v1
constitutive scope. Replacing Hardening Soil with Mohr-Coulomb would create a different
problem and must not be reported as reproduction of that tutorial.

Future suite additions should prefer published cases whose constitutive law and staging
can be reproduced directly, e.g. supported excavation, seepage and tunnel support.
