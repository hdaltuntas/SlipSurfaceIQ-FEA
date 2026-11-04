# F7 — Continuous interface-water node topology

PR #49 compares the solver's water-pressure load vector to independently
derived nodal tributary weights and an exact hydrostatic resultant. These
checks operate on the connectivity supplied to the FEM. They cannot
establish that adjacent physical interface segments were actually joined
by identical mesh node IDs.

This optional topology audit addresses that separate limitation.

## Two-face connectivity gate

For a straight vertical zero-thickness IFACE4 or IFACE6 joint with two
or more segments, a junction must have:

- Exactly the same node ID at the adjacent segment endpoint on face 1
- Exactly the same node ID at the same endpoint on face 2
- **Different** node IDs on the two coincident faces, so the interface
  retains its displacement jump

A duplicated node with exactly the same coordinates is **not** treated as
a physically connected node. Gaps, overlaps, separated faces, and
degenerate segments are rejected. Reversed, consistently ordered
elements remain valid.

Only after this topology check passes does the audit run the separate
nodal force and independent analytical hydrostatic gates from PR #49.
The combined `all_passed` field requires both load checks to pass.

## Regression scenarios

Real IFACE4 and IFACE6 two-element meshes with shared endpoint node IDs
are checked in both directions. The tests deliberately duplicate the
junction node on each face separately (without changing geometry) and
require rejection. Another regression collapses both faces onto the
same node IDs, which must also be rejected.

For a 4 m submerged wall the exact pressure integral is 78.48 kN/m;
a two-element wall with the water table at -2 m has a 19.62 kN/m
analytical resultant.

## Limits

This is a topology and load-vector verification for a continuous
vertical zero-thickness joint. It is not a stiffness, displacement,
interface plasticity, seepage or whole-excavation equilibrium benchmark.
Disconnected segments may be physically intentional; this opt-in
function should not be used to reject discontinuous joint models.
