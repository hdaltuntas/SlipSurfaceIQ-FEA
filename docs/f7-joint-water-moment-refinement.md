# F7 — Hydrostatic interface moment versus mesh refinement

PR #51 introduced an independent benchmark for the hydrostatic water
resultant, first moment and pressure-centre elevation of a straight,
vertical IFACE4/IFACE6 interface. This study keeps the same physical
wall and water head while refining the **actual interface mesh**.

## Reproducible reference

The modelled wall extends from y=-4 m to y=0 m, with water head y=0 m
and gamma_w=9.81 kN/m³. On the ascending interface face, the normal
points in negative x:

- Signed total face-2 force: -78.48 kN/m
- Signed first moment about y=0: -209.28 kN·m/m
- Pressure centre: y=-8/3 m

The `joint_water_moment_refinement` function constructs connected,
two-faced interface meshes with 1, 2, 4 or more equal segments. It
compares real `InterfaceGroup.pore_force` nodal loading against the
unchanged analytical integral independently at every resolution.

IFACE4 trapezoidal integration is exact for the **total force** of
linear hydrostatic pressure but not for its first moment. On a
uniform wall its moment error is proportional to the square of
element length. Thus doubling resolution should divide the moment
error by four. The test requires actual calculated ratios of 4,
rather than inferring convergence from the element count.

IFACE6 Simpson integration is exact for the linear-pressure first
moment on a straight segment. The same benchmark requires both
force and moment to pass at all checked mesh levels, in both normal
orientations.

A secondary case sets the water table at -2 m. It cuts the single
coarse IFACE6 element, introducing a pressure kink that can fail the
force check. In the two- and four-segment meshes the water table is
aligned with an element junction and both physical gates must pass.

## Scope

This benchmark addresses **external interface water-load integration
and its moment**. It is not an analysis of pile bending stiffness,
soil–interface coupling, grout/anchor transfer, hydraulic gradients,
or nonlinear staged excavation equilibrium. The numerical result
of a correctly integrated force does not replace a supported-wall
analytical verification.
