# F7/V5 — Signed structural force distributions

The earlier excavation audit compared absolute beam N/V/M and bolt axial
force magnitudes along a common CAD station coordinate. This loses whether a
section is in compression or tension and conceals opposing shear and moment
signs. It is not adequate for a signed structural force diagram.

## Explicit sign convention

Beam internal section forces originate from the solver's local frame:
N is tension-positive, V is local shear, and M is local bending moment.
For `signed=True`, the mesh beam element must run in the same direction
as its corresponding CAD support from start to end. Every beam element
orientation is checked against the CAD direction, and the routine raises
an explicit error if an element is reversed or degenerate. No guessed
local-frame sign transformation is applied.

Bar axial force uses the solver's tensile-positive scalar value,
which is invariant under reversing an endpoint pair. This remains a
separate bar profile with one component.

Adjacent element end stations are averaged when the same station is
present twice. The resulting data is an *interpolated diagnostic*, not
a substitute for displaying element-local end-section jumps directly.

## Mesh audit integration

The optional tool is

    python examples/f7_excavation_mesh_audit.py --sizes 2.5 1.8 1.2 --output-dir f7_audit

`excavation_force_distributions.json` now includes signed profiles,
signed RMS comparisons across mesh resolutions and per-support errors
for unsupported or inconsistent orientations. Existing magnitude
profiles and their comparisons are preserved for compatibility.
The CLI's underlying three-mesh solve remains optional and is not
executed by the short CI test suite.

Signed-vs-magnitude profiles cannot be compared numerically: the
comparison tool explicitly checks the profile mode. A missing signed
profile is never reported as a zero signed section force.

## Limitations and next acceptance gates

- A polyline with changing tangent cannot be treated as one global
  section frame merely by projecting onto its endpoint chord. Curved
  supports will require arc-length parameterization and transported
  local frames before signed diagrams can be considered reliable.
- Signed section results are interpolated, so concentrated loads and
  junction discontinuities must be inspected at actual element ends.
- Signed result interpretation does not itself verify internal force
  equilibrium between soil, interface, pile/liner and bolt.
- Full F7 acceptance still requires independently assembled stage
  tractions, three-level mesh review and external benchmark comparisons.
