# F7/V4 — Mohr–Coulomb and Hoek–Brown constitutive verification

This package does not claim that nonlinear excavation or strength reduction
analyses are validated.

## Independent yield-surface checks

Tension-positive principal stresses are sorted as sigma1 >= sigma3.
The reference Mohr-Coulomb equation is evaluated independently:

    k = (1+sin(phi))/(1-sin(phi))
    f_MC = k*sigma1 - sigma3 - 2*c*sqrt(k)

Boundary points are derived analytically. Increasing minor-principal
compression moves outside the yield surface. The hydrostatic apex is
separately checked against c/tan(phi). All stresses are kPa and angles
are degrees.

For generalized Hoek–Brown (2002), independent reference parameters:

    mb = mi*exp((GSI-100)/(28-14D))
    s  = exp((GSI-100)/(9-3D))
    a  = 0.5 + (exp(-GSI/15)-exp(-20/3))/6

The tension-positive implicit yield boundary is

    sigma1 - sigma3 = sigci*(s-mb*sigma1/sigci)^a

GSI, disturbance D and intact mi are varied. Compressive capacity at
sigma1=0 is independently calculated as sigci*s^a. These are yield
criterion tests, not laboratory specimen simulations.

## Independent continuum elastic-limit test

For high-strength MC/HB models under small loads, plastic algorithms must
recover isotropic linear elasticity. For a laterally confined rectangular
column:

    M = E*(1-nu)/((1+nu)*(1-2nu))
    uy(top) = -q*H/M

The vertical global reaction is Ry=q*W per out-of-plane metre and
vertical stress syy=-q. Test cases cover T3 and T6, with both
Mohr–Coulomb and Hoek–Brown constitutive models.

## Existing verification

- Return mapping and consistent algorithmic tangent finite differences:
  tests/unit/test_materials.py
- MC apex rejection diagnostics and numerical solver matrix contract:
  tests/unit/test_apex_iteration_matrix.py
- Staged slope and tunnel examples: tests/verification

## Remaining numerical gates

1. Independent plastic stress/strain loading-unloading trajectories,
   especially active-set switches and non-associated flow.
2. Excavation stages: equilibrium, rollback and convergence under three
   mesh resolutions and Newton/line-search variants.
3. Beam, bolt, and liner force-transfer and capacity benchmarks.
4. Published external RS2/PLAXIS comparisons with documented conventions.

Green CI is necessary for these changes but not a claim of full
engineering validity.
