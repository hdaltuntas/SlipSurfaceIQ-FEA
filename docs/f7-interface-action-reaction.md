# F7/V5 — Interface face-force reciprocity

This package checks the **action/reaction identity inside each active
zero-thickness soil–support interface** and exports it by stage. It is
not the same as independently demonstrating global force balance in an
excavated FEM domain.

## Force definition

A supported interface has two opposing faces. For each integration
point, the constitutive output is local traction `t=[tau,sigma_n]` in
kPa. The solver defines an in-plane rotation matrix R and a geometric
integration weight w (with axisymmetric radius scaling only in
axisymmetric problems). The global resultant for face 2 is

    F2 = sum_IP (R t) w
    F1 = -F2

Each stage exports face 1 and face 2 Fx/Fy, their algebraic imbalance,
and the number of active (non-NaN) interface elements. Entirely inactive
elements are omitted rather than interpreted as valid zero-stress
elements; partly invalid active tractions cause an explicit error.

The regression test uses a 2 m horizontal interface with shear 3 kPa
and normal stress -5 kPa. The expected face 2 resultant is (6,-10)
kN/m and face 1 (-6,+10) kN/m. The independent force calculation
therefore verifies unit scaling, local-to-global orientation, and
action/reaction resultants.

## Reproducible reporting

The optional existing audit

    python examples/f7_excavation_mesh_audit.py --sizes 2.5 1.8 1.2 --output-dir f7_audit

adds `interface_force_pairs` per stage and mesh to
`excavation_mesh_audit.json`. It preserves all previous report
fields. The three-mesh solve remains optional and is not run in
routine CI.

## Unverified engineering gates

- The identity F1+F2=0 follows from the interface formulation;
  **it does not independently validate the total assembled global
  residual** or load transfer to a particular beam/soil DOF.
- Hydrostatic *joint water pressure* is a separate force component,
  not part of these effective-stress constitutive tractions.
- The global excavation stage must still independently balance
  boundary loads, self-weight, water, removed-element stress-release
  forces, reactions, and structural actions.
- Force continuity through nonconforming ends, pile–anchor junctions,
  and excavation corners requires further mesh-sensitive tests.
- Signed N/V/M and interface tractions must be reconciled in the
  same local frames before an engineering release.

A green CI only confirms the bounded reciprocity and reporting tests,
not complete F7 numerical verification.
