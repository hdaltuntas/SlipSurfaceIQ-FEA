# F7 — Interface traction transfer to assembled FEM node forces

## Numerical contract

An active zero-thickness interface contributes equal and opposite **internal**
forces to its two faces. Its local traction components are shear and normal
stress, and the solver maps them into global X/Y directions at each interface
integration point.

This verification reconstructs the interface element internal-force vector
using the solver's same element assembler, scatters it onto the actual global
mesh node IDs, and compares the resulting *separate face forces* with the
independently integrated interface tractions previously introduced in PR #35.

Both IFACE4 and IFACE6 are covered using a two-metre horizontal joint.
At shear traction 3 kPa and normal stress -5 kPa:

    face 1 = (-6, +10) kN/m
    face 2 = (+6, -10) kN/m
    total interface = (0, 0) kN/m

The tests verify the mesh assembly shape, both resultants, global scattering
to nodes, inactive element treatment, invalid active data rejection, and
JSON-safe stage reporting.

## Staged excavation report

The existing optional command

    python examples/f7_excavation_mesh_audit.py --sizes 2.5 1.8 1.2 --output-dir f7_audit

now includes a JSON field `interface_nodal_transfer`, alongside earlier
`interface_force_pairs`. The new field contains each stage/interface's
active element count, face resultants, nodal force residual and comparison
error. This helps identify whether a problem lies in traction integration or
in its translation to mesh DOFs.

## Scope and important limitations

- The assembled force includes **constitutive interface tractions only**.
  Interface water-pressure terms are separate.
- Internal interface action/reaction cancel in global resultant by
  construction; a zero residual here does **not** demonstrate full-model
  equilibrium.
- The exact source of geometric integration weights and local frames is
  the same finite-element implementation being tested. Independent constant
  traction benchmarks help guard it but do not prove every curved interface.
- The full stage balance must still include continuum stress, body forces,
  excavation release, groundwater, external surface loads, bar/beam forces,
  and prescribed-support reactions.
- The three-mesh excavation study is opt-in and must be run and reviewed
  before claiming real support load-transfer validation.

F7 remains open until the full numerical acceptance gates have been met.
