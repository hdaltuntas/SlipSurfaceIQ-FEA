# F7 — Hydrostatic pressure centre and force moment

Previous F7 checks established the resultant hydrostatic force and
the transfer of water loads into IFACE4/IFACE6 interface nodes.
Neither check verifies the **line of action** of that force.

An incorrect nodal distribution can produce the right global force
but an incorrect moment, which is especially relevant to retaining
walls and piles.

## Independent reference

For a straight vertical segment between elevations `low` and `high`,
and a horizontal piezometric elevation `head`, let

    wet_high = min(high, head)

The analytical hydrostatic resultant is the integral of
`gamma_w*(head-y)` between `low` and `wet_high`, when wet_high > low.
Its independent first moment is the integral of
`y*gamma_w*(head-y)` on the same interval.

The signed z moment about the origin is `Mz = x*Fy-y*Fx`.
The reference pressure-centre elevation is obtained from the ratio
of first moment to force. Actual nodal moment is assembled from the
solver's `InterfaceGroup.pore_force` and the original physical node
coordinates on **face 2**. The previous exact force gate is also
required to pass.

For a 4 m high submerged vertical wall with free water at its top:

    |F| = gamma_w*4²/2 = 78.48 kN/m
    |Mz| = gamma_w*4³/3 = 209.28 kN m/m
    y_pressure_centre = -8/3 m, from surface elevation 0

## Expected discretization behaviour

An IFACE6 element with Simpson nodal integration reproduces the
linear pressure's force and first moment exactly in this case.

A single IFACE4 element with trapezoidal nodal integration
reproduces the total force of linear pressure exactly but places
its discrete resultant at the bottom node, producing an incorrect
moment (and pressure-centre elevation -4 m). The moment gate
**must fail**, even though the force gate passes.

A water table cutting a quadratic element introduces a piecewise
pressure kink and can likewise fail the independent physical check.

## Engineering scope

These are verification references for external hydrostatic loading of
straight, vertical, zero-thickness interfaces under plane strain.
They do not establish accurate structural wall bending, soil/structure
stiffness, interface plasticity, seepage or full supported-excavation
equilibrium. The raw difference between a discrete load vector's
moment and the continuous pressure moment is reported and never
silently corrected by this audit.
