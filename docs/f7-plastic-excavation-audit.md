# F7/V5 — Plastic-path and staged-excavation mesh-sensitivity audit

This package extends F7 numerical verification without claiming that the
nonlinear excavation benchmark is complete or independently calibrated.

## V4: independently derived perfect-plastic shear response

A homogeneous Mohr-Coulomb material with phi=psi=0 is Tresca in principal
stress space. Under a purely deviatoric engineering shear strain gamma_xy,

    G = E/[2(1+nu)]
    tau_trial = G * gamma_xy
    f_MC = sigma1 - sigma3 - 2c = 2*(|tau|-c)

When gamma exceeds c/G, the returned shear stress is expected to lie on
the perfect-plastic plateau |tau|=c and mean stress must be conserved
for zero-dilation flow. A negative incremental shear strain of magnitude
less than c/G must then unload elastically. The test checks state
immutability and consistency of single versus multiple increments.

This test does **not** validate all Mohr-Coulomb active-set transitions,
zero-dilation apex obstructions, or 3D principal stress reorderings;
those have separate tests or remain engineering verification gates.

## V5: reproducible excavation mesh refinement audit

Run explicitly in a desktop-capable development environment:

    python examples/f7_excavation_mesh_audit.py --sizes 2.5 1.8 1.2 --output-dir f7_audit

The driver regenerates the existing example pile wall and anchor excavation
for three target mesh sizes. The material, construction stages, initial K0
stress, boundary definitions, pile/anchor configuration and solver settings
are kept the same at each resolution. It computes and records:

- nodes / continuum elements and mesh target h;
- per-stage maximum displacement, reaction force resultants and load factor;
- number of active plastic Gauss points;
- accepted and rejected increments, Newton iteration count and final accepted
  residual, when a stage history is available;
- consecutive-mesh *relative displacement changes per stage*;
- mesh generation, invalid-Jacobian or solver failures, without discarding
  failed cases.

Files: `excavation_mesh_audit.csv` and `excavation_mesh_audit.json`.

The audit intentionally does not assert that displacement must be monotonic
under refinement, or compare dissimilar singular points. Agreement of two
discretizations alone is not a benchmark acceptance criterion.

## Remaining verification before F7 acceptance

1. Run the mesh audit and examine actual reaction equilibrium *per stage*.
   The reaction resultant is a reported diagnostic, not yet compared with
   an independently assembled excavation traction balance.
2. Quantify the differences in lining/bulon forces and deformation, especially
   at excavation corners, across at least three refined meshes.
3. Perform mesh-converged plastic cavity comparisons to an analytical tunnel
   solution and published external data using identical sign conventions.
4. Add automated rollback and failure-retry acceptance criteria under nonlinear
   stage increments; rejected steps must not modify committed plastic history.
5. Verify sensitivity to Newton, modified Newton, line search and load-step
   tolerances, without tuning material inputs to match desired results.

Only a completed CI run and documented numerical audits can support later
F7 acceptance. A green test suite alone is not sufficient for release.
