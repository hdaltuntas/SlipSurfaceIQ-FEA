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
0.83% and 1.20%.

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
