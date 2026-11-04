# F7 — Coupled dry pile/anchor excavation equilibrium budget

**Subsequent extension:** straight surface loads and point forces are now
supported; see [loaded three-mesh evidence and current scope](f7-coupled-dry-applied-loads.md).
The no-applied-load run and original contract below are retained as the
initial implementation record.

The new `coupled_dry_stage_budget` audits the actual supported-excavation
stages, including excavated soil, pile self-weight, active interfaces and
anchor axial forces. It adds `coupled_dry_balance` to the three-mesh report
and its force-balance summary. Existing simplified dry/excavation audits
retain their own unsupported classifications; their scope is not silently
expanded.

## Two complementary checks

1. Independently integrate the **currently active** soil and beam weights
   and their first moment `Mz = x*Fy - y*Fx` about the global origin.
   Compare these external resultants with the actual boundary reactions,
   including nodal reaction couples. At full stage release, removed soil
   weight and internal excavation-release forces are not additional persistent
   external loads; adding them again would double count them.
2. Rebuild continuum quadrature and integrate actual effective Gauss-point
   stresses; reconstruct signed beam end forces, bar endpoint forces and
   interface forces on actual mesh nodes. Subtract consistent soil body
   forces, beam body forces and reactions. Bar result values already include
   spacing and pretension, so neither is applied a second time.

Excavated faces deactivate some joint elements. The reconstruction uses the
FEM topology's `tie_pairs` and `DofMap.owner` rules to aggregate forces at
the same constrained DOF. The solver's assembled internal/external force
vectors are not used. Declared stage activation is checked against the model
and interface adjacency; a missing anchor cannot be hidden with a changed
result activity mask. Tied nodes with separated coordinates are unsupported.

Every structural owner-node entry retains its original structural source IDs,
coordinates, continuum/beam/bar/interface contributions, weights, reactions
and residual. Inactive elements are excluded, rather than converted from
missing active values to zero.

## Measured local execution (4 November 2026)

The real native model was solved again at h=2.5, 1.8 and 1.2 m, using the
environment recorded in [the evidence directory](data/f7/2026-11-04/README.md).
All **nine mesh/stage budgets passed**, with no solver exceptions. Maximum
absolute nodal force residual: 1.572e-11 kN/m. Maximum absolute global force
component residual: 1.456e-11 kN/m; global moment residual: 1.910e-11 kN·m/m.
The CLI exited zero with the new coupled budget included in its acceptance
condition. Raw reports and generated review are under
[coupled-dry](data/f7/2026-11-04/coupled-dry/excavation_mesh_audit.json).

Analytical test references use the original 30×14 m soil rectangle at
18 kN/m³ and a 9 m pile with equivalent area `pi*0.8²/(4*2)` and unit
weight 24 kN/m³. Each lift removes 15×2 m from the left side:

- Active soil weights: 7560, 7020 and 6480 kN/m, plus the pile weight.
- Downward-weight moments: 0, -4050 and -8100 kN·m/m.
- Reaction resultants must have the opposite force/moment signs.

The tests also corrupt anchor force while keeping global weight unchanged,
add an equal/opposite reaction couple with zero net force, remove active
anchor evidence, and solve a nonzero-pretension anchor at different spacing.
These checks ensure that a global force sum alone cannot hide local transfer
or moment errors.

## Acceptance and limits

The existing 1e-6 dimensionless assembly tolerance applies to the maximum of:
componentwise nodal residuals normalized by the largest contribution at that
DOF (unit floor in its respective force/moment units), global force imbalance
normalized by total weight (unit floor), and global moment imbalance normalized
by weight times the domain's maximum span (unit floors).
Absolute force and moment residuals are retained separately.

Unsupported: water/pore forces, undrained materials, applied surface/point
loads, seismic forces, imposed displacements, partial stages/load splits,
changed materials and variable shotcrete sections. Missing/nonfinite active
evidence remains unsupported with a reason; finite measured imbalance is
failed. Either prevents the canonical audit CLI from accepting this budget.

This closes the **dry full-stage coupled numerical equilibrium** gap for
the demonstrated excavation. Shared assembly geometry/topology make the
nodal reconstruction a consistency check. It does not prove independent
soil/support physics, plastic benchmark accuracy, mesh convergence, water
equilibrium or RS2/PLAXIS agreement. The installation-stage small-moment
mesh sensitivity remains visible in the review.

Reproduce from the repository root:

```bash
QT_QPA_PLATFORM=offscreen OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 NUMBA_NUM_THREADS=1 \
  PYTHONPATH=src python examples/f7_excavation_mesh_audit.py \
  --sizes 2.5 1.8 1.2 --output-dir /tmp/f7-coupled-dry
python scripts/f7_evidence_review.py /tmp/f7-coupled-dry/excavation_mesh_audit.json
```
