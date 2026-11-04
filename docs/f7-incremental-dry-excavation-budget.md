# F7 — Partial dry elastic loading and excavation-release budget

`incremental_dry_budget_by_stage` separates two quantities that differ when
an excavation stage stops at `load_split < 1`:

- actual applied body/surface/point loads interpolated from the previous
  applied state to the current target;
- the retained, not-yet-released nodal internal-force imbalance after changing
  the active soil/interface set.

The original `coupled_dry_stage_budget` remains the full-stage reference.
Both share reconstruction of soil stresses, structural forces, interface
tractions, target weights/loads, tied owner nodes and reactions; neither reads
the solver's assembled force vectors.

## Reconstruction

Let `P` be the previous actually applied nodal load field mapped onto current
used owner nodes, `T` the current target external load and `lambda` the stage
load fraction. The actual applied field is

```text
A = lambda*T + (1-lambda)*P
```

The initial field is independently integrated gravity on the initial active
mesh. Every subsequent field is retained recursively, so two partial changes
of 0.4 and 0.5 reach 0.7 of the same remaining load change, not 0.9.
Loads on nodes without current DOFs are dropped during remapping, matching
the staged geometry convention; removed element weight cannot simply be
interpolated as one scalar total.

Reconstruct `I0`, the committed internal-force field on the **new** active
set, from the previous saved stresses/beam/bar/interface outputs. In the
present contract a partial stage may remove elements but cannot activate
new ones. The retained release field on free DOFs is

```text
H = (1-lambda)*(I0-P)
```

`H` is zeroed on prescribed DOFs: recorded reactions are measured against
the actually applied external field there. The checked nodal equation is
`I - A - H - R = 0`. Global force and moment compare `A + H + R` against zero.
For unchanged equilibrated geometry, `H` vanishes to roundoff. At full release,
`H=0`, reducing to the existing full-stage budget.

Reports retain target weights/loads, actual applied resultants, retained
release resultants and each structural owner's `actual_applied_external`
and `retained_release` vectors. The inherited `external_resultant` is the
effective `A+H` resultant for this audit, not physical applied loading alone.
Units remain kN/m for forces and kN·m/m for moments about the global origin.

## Executed loaded excavation

`scripts/f7_partial_excavation_audit.py` independently regenerates the same
three meshes, applies the previously documented right-top pressure/shear
and pile-head force, and executes six stages:

1. Full pile installation/loading.
2. First excavation lift with 0.4 release.
3. Same first lift with 0.5 of the remaining release (0.7 cumulative).
4. Complete the first lift and install the anchor at full stage load.
5. Second lift with 0.4 release and the installed anchor.
6. Complete the second lift.

All **18 mesh/stage budgets passed**, with no solver exceptions. The largest
absolute nodal force residual was 1.966e-11 kN/m. In the coarse mesh the first
partial lift retained resultant `(10.88095, -277.875, 2054.39146)`; the next
partial step retained exactly half to numerical precision. These are measured
discretized release forces, not independent continuum design references.
[Raw stage/node evidence](data/f7/2026-11-04/partial_excavation_audit.json).

```bash
QT_QPA_PLATFORM=offscreen OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 NUMBA_NUM_THREADS=1 \
  PYTHONPATH=src python scripts/f7_partial_excavation_audit.py \
  --output /tmp/f7-partial-excavation.json
```

The dedicated real-FEM workflow runs this script after the existing full-stage
and loaded benchmarks, uploads its JSON, and reports its status/stage count.
The record above is local execution; it does not assert a completed GitHub run.

## Tests and limits

T3/T6/Q4/Q8 pressure-loading tests compare actual resultants against exact
0.4, 0.7 and 1.0 references. The supported excavation test checks nonzero held
forces, their halving on repeated partial release, and final full-stage closure.
Corrupting a previous committed stress breaks the retained-force budget;
missing previous stages remain unsupported rather than becoming zero history.

Current scope: elastic drained soil, dry geometry, unchanged materials and
sections, straight surface loads/point forces, full-stage support activation,
and excavation-only activation changes during partial stages. New soil,
beam, bar or interface activation within a partial stage is explicitly
unsupported; its constitutive initialization needs a separate reference.
Nonelastic soil, water/pore forces, seismic inertia and imposed displacements
also remain unsupported. The existing 1e-6 dimensionless assembly tolerance
is retained; numerical equilibrium does not certify physical validation or
mesh convergence. Water-force accounting is the next planned extension.
