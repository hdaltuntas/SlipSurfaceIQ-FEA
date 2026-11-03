# F7/V5 — Kirsch elastic circular cavity benchmark

## Purpose

This benchmark evaluates **stress redistribution caused by a circular
excavation** against an independent elasticity solution. It is not based on
another SlipSurfaceIQ solver result, nor is it a plastic Mohr–Coulomb or
Hoek–Brown validation.

The initial principal stresses are hydrostatic and equal to -p0, where
positive stress means tension. The cavity radius is a and the support
pressure after excavation is pi, with p0 > pi. The exterior boundary
pressure remains p0.

For an infinite isotropic elastic body, the independent reference is

    G = E / (2*(1+nu))
    delta_p = p0-pi
    delta_sigma_rr = delta_p*a**2/r**2
    delta_sigma_tt = -delta_p*a**2/r**2
    ur = -delta_p*a**2/(2*G*r)

At the wall r=a, radial stress changes from -p0 to -pi, and radial
displacement is inward. Stress and displacement signs are essential:
compressive stress is negative, but pressure qn is entered positive inward.

## Finite-domain numerical approximation

The FE mesh is a quarter of a large square, outer half-width L=25*a.
Symmetry constraints are ux=0 on x=0 and uy=0 on y=0. Outer edges are
loaded at p0 and the cavity is loaded at pi. T6 element meshes are
generated with radial grading at (nr, nt) = (12,16), (20,24) and
(28,32) to evaluate discretization sensitivity.

Tests check:

- wall radial displacement against ur(a) on all three resolutions;
- circumferential uniformity of wall radial displacement;
- radial and hoop stress increments in an interior annulus against the
  independent polar elasticity solution;
- explicit use of initial hydrostatic effective stress in comparisons.

**Limitations:** the analytical equations assume an infinite body,
whereas the FE model is a finite square. Truncation and mapped-mesh
error therefore require a documented tolerance. The tests do not
establish monotone convergence order and do not claim that the plastic
zone, support forces, or excavation staging are verified.

The existing Salençon plastic cavity test remains a separate higher-level
reference. Follow-on numerical gates include plastic radius convergence,
nonlinear solver step acceptance, rollback after failed increments,
Mohr–Coulomb/Hoek–Brown stiffness sensitivity, and beam/bolt transfer.

A green CI run validates only this scoped elastic benchmark. Do not use
these results alone as an engineering release acceptance.
