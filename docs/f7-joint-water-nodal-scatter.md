# F7 — Independent joint-water nodal force verification

PR #48 established a closed-form hydrostatic force check for vertical
IFACE4/IFACE6 joints and confirmed the equal/opposite face resultants.
That check alone cannot detect an incorrect distribution of the same
total force between adjacent finite-element nodes.

## Two independent acceptance gates

The first gate reconstructs expected signed water loads at each original
mesh node using the interface's tributary integration weights:

- IFACE4: length multipliers 1/2 and 1/2 (trapezoidal)
- IFACE6: length multipliers 1/6, 1/6 and 2/3 (Simpson)

Each expected face-2 force is the hydrostatic nodal pressure multiplied
by the element tributary length and face normal. Face-1 force is its
negative. These forces are independently scattered onto the actual
mesh node IDs, without using the solver's finite-element load vector.
The result is compared against the actual
`InterfaceGroup.pore_force` nodal distribution, with a normalized
norm and maximum/RMS nodal errors.

The second gate is the **closed-form** hydrostatic pressure integral
along the entire vertical wall. It detects errors that discrete
nodal tributary interpolation may share with the FEM quadrature.

Consequently:

- A fully submerged linear-pressure IFACE4 or IFACE6 joint should pass
  both nodal mapping and physical integral checks.
- A water table exactly at a subdivision between two IFACE4 elements
  should pass both gates.
- When the water table *cuts through* a single IFACE6 element, discrete
  Simpson nodal mapping may be internally correct while its resultant
  differs from the piecewise hydrostatic integral. The nodal mapping
  gate passes, but the physical integral gate must fail.
- Incorrect redistribution among nodes that preserves a zero global
  force sum must fail the nodal check.

The joint orientation is preserved and tested in both directions.
Both gates use plane-strain units (kN/m).

## Limits

These checks cover the external water term of a straight, vertical
zero-thickness interface. They do not independently validate curved
interfaces, seepage pressure gradients, internal effective-stress
tractions, soil/liner/anchor deformation, or the assembled nonlinear
global equilibrium of a supported excavation. The full supported
excavation acceptance study remains an open F7 requirement.
