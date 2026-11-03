# F7 — Hydrostatic joint-water face-force verification

This increment verifies the *external joint-water* contribution of zero-thickness
soil–support interfaces. It is separate from the effective-stress interface
tractions already covered by the F7 interface action/reaction audits.

For a vertical joint with hydrostatic head h and water unit weight
gamma_w=9.81 kN/m³, the independent pressure integral on a segment
with endpoints y_low and y_high is:

    F = gamma_w/2 * (
        max(h-y_low, 0)^2 - max(h-y_high, 0)^2
    )

The direction is the interface element's face-2 normal. The assembled
force on face 1 must be equal and opposite. The test compares the
closed-form force against the result of the actual
`InterfaceGroup.pore_force` operator.

## Acceptance scenarios

- IFACE4 and IFACE6 under fully submerged linear hydrostatic pressure
  must match the analytical signed force.
- Two IFACE4 elements meeting exactly at the water table must reproduce
  the partially wetted segment without quadrature error.
- One IFACE6 element *cut by a water table inside its length* has a
  pressure kink. Simpson nodal quadrature need not integrate the kink
  exactly; this case must report `failed`, rather than accept mere
  face action/reaction cancellation.
- Reversed element orientation reverses the signed force direction.
  Mixed element orientations along one joint and overlapping segments
  are rejected rather than silently cancelling or double-counting loads.

For a 4 m wall with h=0, the independent resultant is
78.48 kN/m. If the water table is at -2 m, only the lower 2 m
is wetted and the analytical force is 19.62 kN/m.

## Limitations

This benchmark tests the externally applied water force of a straight
vertical joint in plane strain. It does not validate the global
groundwater balance of a fully supported excavation, effective-stress
tractions, deformation, nonlinear return mapping, steady seepage,
interface pressure discontinuities, or the combined continuum–beam–bar
nodal residual.

In particular, exact action/reaction cancellation by itself cannot
establish that interface integration is physically accurate.
