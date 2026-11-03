# F7/V5 — Distributed structural force mesh comparison

The prior F7 audit compared only maximum support moments and bar axial
forces. Peak comparisons are insufficient for mesh convergence: a moment
peak can migrate as a mesh changes, and different element orderings
cannot be compared index-by-index.

## New procedure

For each available CAD liner/pile and bar/bolt support, the audit maps
beam end-force sections or bar element-midpoint forces to the CAD-defined
support line. The normalized station coordinate is

    s = dot(point-start, end-start) / ||end-start||²

The audit interpolates absolute magnitudes onto 51 common stations and
reports N, V, M magnitudes for beam elements and axial force magnitude
for bar elements. Duplicate end stations are averaged. A profile is
identified by the support's CAD tag and stage, not by element ID.

For two adjacent mesh resolutions, each component is compared with

    relative_RMS = RMS(f_fine - f_coarse) /
                   max(RMS(f_fine), RMS(f_coarse), 1e-12)

No automatic tolerance is imposed: localized point-load and attachment
singularities can prevent convergence of peaks or even profile RMS,
and numerical convergence by itself does not prove constitutive accuracy.

If a support is absent on one mesh, the report marks it as missing,
**never as a zero force**. Invalid coordinates, nonfinite section
forces, mismatched tags and element/result shape mismatches cause
explicit errors.

## Reproducible output

Execute the optional study:

    python examples/f7_excavation_mesh_audit.py --sizes 2.5 1.8 1.2 --output-dir f7_audit

New output: `excavation_force_distributions.json`, containing
per-stage/per-mesh support component profiles and RMS comparisons.

Existing outputs remain: `excavation_mesh_audit.csv`,
`excavation_mesh_audit.json` and
`excavation_support_comparison.csv`.

The three-resolution excavation solution is not part of routine CI
and must be run explicitly; short regression tests cover profile
reordering, comparisons, missing tags and invalid input.

## Critical limitations

- Absolute force magnitude avoids sign-convention differences between
  element orientations but **does not validate signed N/V/M diagrams**.
- Interpolation across jumps can hide concentrations. Separate local
  sampling and mesh refinement are required at pile heads, anchors,
  interfaces and excavation corners.
- Distributed beam and bar results are not independently balanced
  against full continuum nodal traction and interface forces here.
- Convergence of these profiles is only one F7 acceptance condition;
  physical benchmarks with identical constitutive inputs are still
  required.
