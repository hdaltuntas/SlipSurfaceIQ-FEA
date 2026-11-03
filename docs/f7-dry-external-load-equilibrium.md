# F7/V5 — Dry straight-boundary pressure and point-load equilibrium

This extends the gravity-only load budget from PR #37 to independently
assembled **external** surface and point loads. It deliberately does not
claim full excavation stress-release, groundwater, structural pretension,
or nonlinear contact equilibrium.

## Independent exterior load calculation

For an external straight boundary segment with length L, outward unit
normal n and counterclockwise tangential unit vector s, a prescribed
pressure (qn, qt) contributes the exterior force

    F_edge = (-qn*n + qt*s)*L

Positive normal pressure acts into the material. The outward normal is
determined from the unique adjacent continuum-element centroid;
reversing input edge nodes must not change the force direction.
The audit rejects internal edges and curved quadratic edges because
the closed-form straight-segment reference is not valid there.

Point loads are summed directly from their specified (fx,fy) in kN/m,
not from the solver's assembled RHS. The independent soil and beam
weight budget is unchanged from F7/PR #37.

For cumulative static stages whose geometry and structure active sets
do not change, the applied exterior load progresses by

    F_applied_i = F_applied_(i-1) + lam_i*(F_target_i - F_applied_(i-1))

where lam_i is the stage's computed load factor. Therefore the expected
support-reaction resultant is

    R_expected = -F_applied + (0, W_soil + W_beam)

This sign convention is tension-positive for traction, while positive
weight acts downward and positive support reaction acts upward.

## Regression cases

- Uniform q=60 kPa pressure on a 4 m wide dry column with
  gamma=18 kN/m3, across T3, T6, Q4 and Q8.
- A sequence of 40%, 100%, and 200% loading. Stage load factors are
  applied to the *current minus previous applied load*, not repeatedly
  to the full target.
- A top shear traction plus independent horizontal and vertical point
  forces; X and Y reaction resultants are checked separately.
- Unsupported staged excavation and groundwater scenarios must never
  be reported as validated dry load cases.

## Strict scope exclusions

The function refuses a changed active finite-element set,
explicit region/structure activations, nonzero groundwater,
axisymmetric geometry, seismic inertia, prescribed displacements,
cumulative material overrides, pretension and changing shotcrete
maturity. Ground-contact pressure on nonexternal boundaries and
curved edges are also rejected.

The optional audit tool

    python examples/f7_excavation_mesh_audit.py --sizes 2.5 1.8 1.2 --output-dir f7_audit

now emits an additional `dry_load_balance` array with per-stage
`checked` or `unsupported` status. Earlier
`gravity_balance` remains unchanged.

**Next acceptance gate:** independently account for released
continuum-element forces during excavation, stage water pressures
and structural forces within a single global residual. A zero
exterior resultant alone cannot detect internal stress-transfer
errors, nonphysical concentration or mesh-dependent mechanisms.
