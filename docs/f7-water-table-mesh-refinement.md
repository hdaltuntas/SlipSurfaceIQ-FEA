# F7 — Groundwater reaction error versus mesh refinement

This package checks the **mesh sensitivity** of the independent water-table
reference introduced in PR #43. It does not claim convergence merely
because a mesh is refined or a global force residual becomes small.

## Benchmark

The model is a laterally confined 2 m × 10 m plane-strain soil column with
two horizontal regions, gamma_unsat=17 kN/m³, gamma_sat=20 kN/m³.
A horizontal piezometric head of -2.37 m deliberately crosses mesh
elements of all three refinement levels.

The independent exact polygon-clipping reference is

    Ry_reference = 2 * (2.37*17 + 7.63*20) = 385.78 kN/m

The reference is not obtained from FEM reactions or from the Gauss-point
pore pressure distribution. At every mesh resolution, the actual FEM
reaction is evaluated independently against the same force target.

## Reproduce

From the repository root:

    python examples/f7_water_table_mesh_refinement.py --rows 2 4 8 --element T6 --output f7_water_mesh.json

T3, T6, Q4 and Q8 are selectable. Mesh rows are refined from coarse to
fine; the default study compares three levels and saves mesh size, element
and node counts, water-cut element counts, the expected and computed
reactions, relative force error, pass/fail against 1e-6, error ratios,
and whether the error decreases monotonically.

The command returns a nonzero exit status if the **finest mesh fails**
the specified acceptance threshold. An intermediate mesh can still
have worse error than a coarser one. The report records this honestly;
no Richardson convergence order is inferred from non-monotone errors.

Regression coverage includes a small three-mesh **actual T3 FEM solve**,
the fixed analytical force reference, support-reaction diagnostics, and
classification safeguards for mismatched physical references.

## Acceptance limits

This benchmark concerns only the global vertical reaction of a
rectangular hydrostatic column. The accepted force residual, even at
several mesh sizes, does **not** prove convergence of local effective
stress, plastic strain, pore pressure or supported excavation response.

This is an optional reproducible mesh audit; the full default three-mesh
T6 run is not required as part of routine CI. Failure at the
specified tolerance indicates that further integration/mesh studies
are needed; the verification reference must not be adjusted merely
to make the result green.
