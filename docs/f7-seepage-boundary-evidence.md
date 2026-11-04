# F7 — Prescribed flux and atmospheric seepage-face evidence

The coupled seepage audit now includes prescribed hydraulic fluxes and
atmospheric seepage faces. Previously it accepted prescribed-head boundaries
only. The new budget independently integrates straight-edge flux, checks
reported flow against saved nodal boundary evidence, and verifies the
seepage-face conditions at every candidate node.

## Flux and face conditions

Positive prescribed `q` is inflow. On a straight external edge its independent
contribution is `q*length`, regardless of endpoint order. Quadratic midpoints
must be central. Edges with hydraulically unused nodes are skipped and counted,
matching the solver's excavated-edge convention. Internal or curved flux
edges are outside this reference. The signed conservation equation is now

```text
sum(reported head/face inflows) + sum(prescribed edge inflows) = 0
```

For a candidate atmospheric face node not overridden by a prescribed head:

- active node: `head-y=0` and nodal boundary inflow <= 0 (outflow only);
- released node: `head-y<=0` and no constrained-node boundary flux;
- active-node IDs must belong to the declared hydraulically used face.

Reported boundary sums are checked against saved nodal fluxes. Shared
head nodes follow the solver's last-declared head ownership; head nodes are
excluded from atmospheric candidates. Overlapping atmospheric faces are
unsupported because they require an explicit flow-ownership policy. A total
flow sum cannot hide equal/opposite nodal errors or a face node taking inflow.

`StageResult` now retains `seepage_nodal_flux`, `seepage_nodes` and
`seepage_diagnostics`. Both HDF5 result formats, lazy legacy access and project
containers preserve them as optional additions. Old files load with `None`
node evidence and empty diagnostics. A legacy face result without node-level
evidence remains unsupported; no zero-flux face is invented. Older prescribed-
head-only records can still use the original aggregate evidence contract.

## Picard oscillation found and corrected

The first actual infiltration/face excavation failed on all three requested
meshes with the original fixed 0.5 Picard relaxation:
[original failed execution](data/f7/2026-11-04/seepage_boundary_fixed_damping_failure.json).
No completed stage budget is claimed for that failed run.
The coarse initial hydraulic solution still had a conductivity fixed-point
residual around 0.86 after 200 iterations. A controlled fixed-0.25 run on the
same geometry and material inputs converged, identifying an iteration issue.

Picard now starts at the caller's `damping` (default 0.5), halves relaxation
after a >20% increase in the undamped conductivity residual, and allows at
least eight iterations between reductions. The floor is `min(start,0.125)`.
The iteration cap remains 200, and no material/hydraulic parameters are tuned.
`adaptive_damping=False` retains fixed relaxation for diagnosis.

Convergence requires an unchanged face set, the existing head-increment
criterion and the **undamped** `max(abs(kr(head)-kr_used)) < 1000*tol`.
This is stricter than the previous damped-update criterion; reducing relaxation
cannot manufacture convergence. Final velocities and fluxes still refer to
the conductivity matrix actually solved, rather than the next proposed update.
Per-iteration relaxation and final conductivity residual are saved in the
stage diagnostics and persist through result/project round trips.

## Actual three-mesh execution

The loaded native pile/anchor excavation has left head 1 m, top infiltration
`q=1e-8 m/s`, an atmospheric right face and saturated unit weight 20 kN/m³.
Other hydraulic boundaries retain their natural no-flow condition. Its
geometry, soil constitutive/hydraulic parameters and structural schedule
are identical between the failed and corrected runs.

After the iteration correction, all **nine mesh/stage budgets passed**,
with no solver failures. Top infiltration independently integrated to
`3e-7 m²/s` before excavation and `1.5e-7 m²/s` after either lift; all nine
analytical flux references passed. All faces contained both active and
released nodes. Saved face pressure, flow direction and nodal-to-boundary
sums passed their checks.

The reported user-stage seepage solves took 57–105 iterations, reducing
relaxation to 0.25 or 0.125. Final undamped conductivity residuals were below
7e-6. Maximum coupled nodal force residual: 4.622e-11 kN/m; maximum global
moment residual: 2.001e-11 kN·m/m; relative flow imbalance: 3.111e-14.
[Successful node/flow/solver evidence](data/f7/2026-11-04/seepage_boundary_audit.json).

```bash
QT_QPA_PLATFORM=offscreen OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 NUMBA_NUM_THREADS=1 \
  PYTHONPATH=src python scripts/f7_seepage_boundary_audit.py \
  --output /tmp/f7-seepage-boundary.json
```

The dedicated FEM workflow runs this case, uploads the evidence and reports
its status/stage count. These measurements are local; they do not assert a
completed GitHub run of the updated workflow.

## Verification and remaining work

T3/T6/Q4/Q8 prescribed-outflux tests recover exact linear head and known
discharge. Additional tests check atmospheric active/released nodes, forged
inflow with a conserved total, positive pressure on a released node, missing
node evidence, modern/legacy/project persistence and adaptive versus fixed
relaxation without changed physical inputs. The inherited 1e-6 dimensionless
assembly tolerance and the 1e-12 m²/s flow scale floor are retained.

The saved nodal flux is solver evidence, not an independent Darcy residual.
The next task is independently reconstructing hydraulic residuals at the
solved head, with explicit treatment of the nonlinear conductivity lag.
Partial seepage histories, mesh convergence and independent physical
excavation validation remain open.
