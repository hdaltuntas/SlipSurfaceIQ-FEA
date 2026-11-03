# F7 — Closed-form hydrostatic wall force benchmark

This verification increment starts the independent water-pressure benchmarks
without extending the earlier *dry* total-force acceptance gates beyond
their documented scope.

## Reference solution

For a straight vertical wall from elevation y_low to y_high, and a
horizontal piezometric head h (metres), water pressure is

    p(y) = gamma_w * max(h - y, 0) [kPa]

The exact integrated force per out-of-plane metre is

    P = gamma_w/2 * (
        max(h - y_low, 0)^2 - max(h - y_high, 0)^2
    ) [kN/m]

The force acts into the ground, opposite to the outward wall normal.
It handles a dry wall, a partially submerged wall, a water level
at an element junction, and a fully submerged wall without numerical
quadrature.

The independent analytical resultant is compared with the FEM
`pressure_edge_forces` boundary integration. Both 2-node and straight
3-node quadratic edges are covered. A water table cutting *through*
an element can introduce quadrature error at the pressure kink:
the discrepancy is deliberately returned, not rounded away.

## Standalone reproduction

    python examples/f7_hydrostatic_wall_audit.py --output f7_hydrostatic_wall.json

The example uses a 4 m vertical wall, ground to the right, and a
water table at -2 m aligned with a mesh node. The analytical result
on the lower 2 m wet segment is

    P = 9.81 * 2^2 / 2 = 19.62 kN/m

The upper dry segment carries no pressure. Each segment's signed
X/Y resultant, error and acceptance status is saved as JSON.

## Rejected inputs and limitations

Only vertical straight segments in **plane strain** with a horizontal
piezometric level are currently benchmarked. Oblique walls, curved
quadratic edges, varying hydraulic head, seepage gradients, interface
joint pore pressures and axisymmetric loading need separate formulas.

This benchmark verifies the water-pressure **boundary integration**.
It does *not* validate total soil effective stress, buoyant/saturated
self-weight, seepage force integration or global reaction equilibrium
in a coupled excavated domain. Those remain open F7 gates, even if all
standalone hydrostatic tests pass.
