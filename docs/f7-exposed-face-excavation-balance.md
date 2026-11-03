# F7 — Independent force budget for newly exposed excavation faces

This package extends the dry gravity and surface-load balances beyond a
fixed active continuum. It verifies that excavation removes the dead
weight of deactivated soil, and that a formerly internal edge can receive
an external pressure once its adjacent upper continuum has been removed.

## Acceptance case

A plane-strain column is 4 m wide and 6 m deep, with an upper
and lower 3 m region, both with gamma=18 kN/m3.

* Stage 1: both soil layers present, no applied pressure.
  The analytical vertical reaction is 4 x 6 x 18 = 432 kN/m.
* Stage 2: upper layer excavated, the exposed lower-layer top is
  subjected to 20 kPa normal pressure. The analytical reaction is
  4 x 3 x 18 + 20 x 4 = 296 kN/m.

The test compares independently computed area-weight and straight-edge
pressure resultants against the FEM reaction. T3/T6 element variants are
included.

## Boundary classification

The benchmark uses the *current active continuum*, not the original
unexcavated mesh, to find the sole interior owner of a loaded edge.
A shared internal edge is not an external load boundary before its
neighbor is excavated. Its outward normal is determined from the
remaining element centroid, independently of the edge node direction.

## Deliberate restrictions

Only completed dry, plane-strain stages without structural supports,
groundwater, material changes, seismic loading, prescribed
displacements, additional tractions or partial-stage load factors
are supported. All earlier stages must have load factor 1.

A passing resultant balance is **not** proof of stress-field accuracy,
interface traction continuity, realistic yield zones, or nonlinear
excavation convergence. It can conceal compensating local errors.

The optional three-mesh staged excavation tool now reports
`excavation_balance` for every stage, with an explicit
`unsupported` status when supports, water or partial stages take
the model beyond this verification scope. The existing supported
pile/anchor demo is expected to remain unsupported by this restricted
budget. The next step is independently accounting for the mechanical
contributions of activated structures and groundwater.

CI must pass before accepting this change as a valid scoped test.
