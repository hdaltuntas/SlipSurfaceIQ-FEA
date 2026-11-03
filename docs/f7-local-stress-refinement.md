# F7 — Local hydrostatic stress mesh-refinement audit

The earlier F7 hydrostatic studies established independent total-reaction
and Gauss-point effective-stress references. In particular, the T3
constant-strain approximation produced a nonzero stress error even where
the exact one-dimensional geostatic stress varies linearly with depth.

This audit compares **actual local Gauss-point errors** at multiple mesh
resolutions for the same physical model, without changing the analytical
reference, suppressing failed cases or assuming monotonic convergence.

A 2 m × 10 m laterally restrained drained elastic soil column has
gamma_unsat=17 kN/m³ and gamma_sat=20 kN/m³. Initial groundwater
head is 0 m and a second stage lowers it to -4 m. T3 and T6 are
available; the default CLI is T3 to expose its genuine discretization
error. Each mesh is evaluated against closed-form pore pressure and
effective sigma_yy at the actual Gauss-point elevations.

Run:

    python examples/f7_local_stress_refinement.py --rows 2 4 8 --element T3 --output f7_local_stress.json

The output includes per-stage maximum and RMS pore and effective-stress
errors, mesh resolution and counts, acceptance classification against
the stated relative tolerance, and whether stress errors are
non-increasing. The CLI returns a nonzero exit code if any mesh/stage
fails its acceptance tolerance. Thus a physically expected T3 error
is visible as `failed`, not disguised as a verification success.

A lightweight CI benchmark actually solves two T3 resolutions and
requires the initial-stress error to decrease. Separate synthetic
tests ensure nonmonotonic changes and inconsistent stage/head
references cannot be reported as converged.

These are **local** verification metrics for a simple hydrostatic
column. They do not validate a nonlinear coupled excavation with
seepage, pile, anchors, interfaces, or excavation-induced stress
redistribution. That remains an open F7 engineering acceptance gate.
