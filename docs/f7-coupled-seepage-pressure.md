# F7 — Seepage head-to-pressure transfer and coupled equilibrium

The subsequent [flux and atmospheric-face extension](f7-seepage-boundary-evidence.md)
now supports those hydraulic boundaries with saved node-level evidence.
The original prescribed-head-only implementation record below is retained.

`coupled_seepage_stage_budget` checks saved seepage heads and their transfer
to mechanical loads for completed full-load stages with prescribed hydraulic
heads. The new reference does not call the seepage solver or reuse its
assembled mechanical water vector.

## Separate pressure interpolation paths

The two interpolation orders are different and must remain distinct:

- Continuum Gauss-point pressure is
  `gamma_w*max(interpolate(nodal_head)-gp_y,0)`. It is compared with every
  saved active `StageResult.pore` sample, then used to reconstruct continuum
  water forces and the Gauss-point dry/saturated body weight switch.
- Boundary and joint loads start from
  `gamma_w*max(nodal_head-node_y,0)`. Boundary pressure is interpolated from
  these clipped nodal values. On a straight edge, consistent loads are derived
  from exact edge mass matrices: `L/6*[[2,1],[1,2]]` for linear edges and
  `L/30*[[4,-1,2],[-1,4,2],[2,2,16]]` in quadratic endpoint/midpoint order.
  Joint loads use the existing trapezoidal/Simpson tributaries and the
  actual face-1 node IDs.

Active hydraulic nodes must have finite saved heads. Hydraulically inactive
nodes must retain NaN heads; their mechanical joint-pressure input is zero,
matching the FEM contract. No pressure is inferred from a coincident soil
node on another interface face. The existing tied-owner mapping and
total-reaction boundary-water suppression are retained. Interface faces
remain excluded from the exposed-continuum edge set.

## Hydraulic evidence and limits

The audit checks prescribed-head samples against their declared values and
requires exactly the declared boundary-flow entries. With no flux boundary
or seepage face, their signed reported inflows must sum to zero. The relative
reported-flow imbalance uses `max(sum(abs(inflows)),1e-12)` m²/s as its scale;
the floor prevents roundoff from dominating a zero-gradient case.
Missing/nonfinite heads, pressure blocks or flow entries remain unsupported.
Finite pressure/head-boundary/flow-conservation mismatches contribute to a
failed normalized audit, alongside the nodal and global mechanical residuals.

This is **reported boundary-flow conservation and pressure transfer**, not
an independent Darcy/Picard residual audit. Saved mechanical stage data do
not retain the final conductivity matrix or nonlinear conductivity iteration
state. A fabricated but self-consistent hydraulic field cannot be certified
as physically correct by these transfer checks alone.

Supported here: plane strain, gravity/K0 initialization, full stages,
drained materials, default quadrature, prescribed hydraulic heads, and
straight coincident interfaces/exposed edges. Unsupported: partial-stage
history, prescribed hydraulic fluxes, seepage faces, nondefault hydraulic/
mechanical quadrature, undrained excess pressure, imposed displacements,
seismic forces, property/shotcrete changes and curved load geometry.
The existing dry and horizontal-head audit APIs keep their original scope.

## Analytical and corruption verification

T3/T6/Q4/Q8 rectangular references use a 4×6 m domain and left/right heads
3/1 m. The entire domain is saturated, so head is exactly `3-0.5*x` and
discharge is `k*(3-1)/4*6`. Independent reaction references include the
480 kN/m bulk weight, `8*gamma_w` downward water surcharge and
`(40/3)*gamma_w` surcharge moment about the origin. All four references pass.

A partially saturated case demonstrates that clipping pressure before head
interpolation gives a different Gauss-point field and is rejected. Additional
tests cover zero-gradient flow roundoff, missing/nonfinite heads, missing flow
entries, corrupted flow conservation and hydraulically inactive pile-node
identity. Unsupported flux, seepage-face, high-quadrature and partial-stage
contracts are also explicitly checked.

## Actual three-mesh loaded excavation

`scripts/f7_seepage_excavation_audit.py` regenerates the loaded native
pile/anchor excavation at h=2.5, 1.8 and 1.2 m. The soil's saturated unit
weight is 20 kN/m³, with prescribed heads 1 m on `Soil:4` and 0 m on
`Soil:2`; other hydraulic boundaries are natural no-flow boundaries.
The pile interfaces remain hydraulically impermeable. The right-top
pressure/shear and original pile-head point load remain applied.

All **nine mesh/stage budgets passed**, with no solver exceptions. The
maximum absolute nodal force residual is 4.440e-11 kN/m, global moment
residual 2.001e-11 kN·m/m, and relative reported-flow imbalance 4.562e-14.
All saved pressure samples matched the reconstructed head reference.
Independent saturated-weight and applied-load resultants also passed for
all nine rows. The geometry-specific excavation discharge is not claimed
to match an independent physical flow benchmark.

[Raw measured heads, flows and node budgets](data/f7/2026-11-04/seepage_excavation_audit.json).
Execution used the previously recorded local environment on main commit
`843245c` plus these working-tree audit changes.

```bash
QT_QPA_PLATFORM=offscreen OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 NUMBA_NUM_THREADS=1 \
  PYTHONPATH=src python scripts/f7_seepage_excavation_audit.py \
  --output /tmp/f7-seepage-excavation.json
```

The dedicated real-FEM workflow now runs this case and uploads its report,
including status/stage count in the summary. This record is local execution,
not a completed run of the updated GitHub workflow. The 1e-6 dimensionless
assembly tolerance remains unchanged.

Next: prescribed-flux/seepage-face evidence and an independent hydraulic
residual reference before extending seepage histories to partial stages.
Mesh convergence, bare-structure hydraulic exposure and independent physical
validation remain open.
