# F7 — Applied surface and point loads in the coupled dry budget

The subsequent [incremental dry elastic audit](f7-incremental-dry-excavation-budget.md)
now covers partial releases through a separate history-aware budget. The
full-stage API below retains its explicit full-load contract.

The coupled full-stage dry budget now includes uniform normal/shear traction
on straight exposed continuum edges and global point forces at active nodes.
It retains separate weight, applied-load and total external resultants, each
as `(Fx, Fy, Mz)` about the global origin. Structural owner-node records also
retain the applied nodal contribution.

`independent_dry_applied_loads` uses closed-form consistent weights of
(1/2, 1/2) for linear edges and (1/6, 1/6, 2/3) for straight quadratic edges
whose third node is the geometric midpoint. A uniform edge resultant acts
at its midpoint; point-force moment is `x*Fy-y*Fx`. This avoids the solver's
traction quadrature and assembled load vector. Normal orientation is derived
from the unique active continuum owner, independently of edge endpoint order.

Edges with nodes no longer used after excavation are skipped and counted,
matching the active-edge contract. An edge set with no live edges, a loaded
internal face, an inactive point node, nonfinite loads or curved/noncentral
quadratic geometry is rejected. No unsupported reference becomes a pass.
The current stage's loads are its full target: removing a load in the next
completed stage does not accumulate it from earlier stages.

## Actual loaded three-mesh excavation

`scripts/f7_loaded_excavation_audit.py` rebuilds the canonical supported
excavation at h=2.5, 1.8 and 1.2 m. Every stage applies:

- 20 kPa pressure and 3 kPa shear on the retained right top surface,
  x=0..15 m, y=0;
- a pile-head force `(10, -5)` kN/m at the original node at (0, 0).

The exact added resultant is `(-35, -305, -2250)` in kN/m, kN/m and
kN·m/m respectively: the top-surface CCW tangent is -X, and the pressure
moment is `-20*15*7.5`. These constants are checked separately for every
reported stage; the script exits nonzero for failed/missing budgets,
analytical mismatches or solver failures.

All **nine actual stages passed**, with no solver failures. The largest
absolute nodal force residual was 2.380e-11 kN/m. The analytical applied
reference matched in all nine rows.
[Raw measured artifact](data/f7/2026-11-04/loaded_excavation_audit.json).
The execution environment is the same as the earlier local F7 record.

Reproduce from the repository root:

```bash
QT_QPA_PLATFORM=offscreen OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 NUMBA_NUM_THREADS=1 \
  PYTHONPATH=src python scripts/f7_loaded_excavation_audit.py \
  --output /tmp/f7-loaded-excavation.json
```

The dedicated real-FEM workflow now runs both the canonical and loaded
excavations, preserves the loaded JSON with its existing artifact upload,
and includes loaded-run status in its job summary. This local execution
does not claim that the updated GitHub workflow has already completed.

## Verification and remaining scope

Analytical tests cover force/moment resultants and actual solves for T3,
T6, Q4 and Q8; exact quadratic nodal weights; reversed edge orientation;
load removal; newly exposed face pressure/shear, including the `-y*Fx`
moment term; excavated-edge filtering; and rejected curved/nonfinite loads.
The earlier anchor corruption and reaction-couple tests remain in place.

The coupled metric now scales global force residuals by the largest of
unit force, weight magnitude, applied-force magnitude and total external
force magnitude. The global moment uses that force scale times the maximum
domain span (unit length floor); local DOF scaling is unchanged.

Water, undrained pore forces, seismic inertia, imposed displacements,
partial load/release stages and changing materials/shotcrete sections remain
unsupported. The next extension is the incremental budget for partial
stage release. Numerical equilibrium still does not establish independent
physical validation or mesh convergence.
