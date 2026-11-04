# F7 — Partial wet excavation, drawdown and rewetting history

`incremental_hydrostatic_budget_by_stage` extends the elastic incremental
audit to horizontal piezometric water levels and explicit dry transitions.
The existing dry API continues to reject water; the full-stage hydrostatic
API continues to reject partial stages.

## Target pressure versus applied loading

For a partial stage, `StageResult.pore` stores the pressure associated with
the **target** water condition. It is not a partially blended pressure field.
The new audit validates those samples against `gamma_w*max(target_head-y,0)`
and separately reconstructs the actually applied body, surface and water
load fields on the current owner nodes:

```text
actual_external = lambda*target_external + (1-lambda)*mapped_previous_external
actual_water    = lambda*target_water    + (1-lambda)*mapped_previous_water
```

The initial external/water fields are rebuilt from the initial declared
regions, structures, horizontal head, saturated body forces and the same
total-reaction convention used by the
[full-stage hydrostatic audit](f7-coupled-hydrostatic-budget.md).
Missing initial water evidence is not replaced by zero.

As in the dry incremental audit, retained release on free DOFs is
`(1-lambda)*(previous_committed_internal_on_current_active_set-mapped_previous_external)`.
It is zero on prescribed DOFs because their recorded reactions are measured
against the actually applied external field. The checked equation remains
`internal - actual_external - retained_release - reaction = 0`.

Reports retain `actual_applied_water_resultant`, `target_water_resultant`,
target `water_head_m`, target pressure errors and structural-node
`actual_applied_water` vectors. The inherited `water_resultant` is explicitly
labelled `water_resultant_scope=current_stage_target`. A dry target uses
`water_head_m=null` and `water_mode=none`; JSON remains finite.

Across excavation geometry changes, interpolation occurs on actual used
owner nodes, dropping nodes that have no current DOFs. A previously balanced
global water resultant may therefore acquire a horizontal component after
remapping; it cannot be obtained by simply interpolating global scalars.
The retained release and reactions balance that discrete load field. This
checks the solver's load/release convention, not an independent transient
hydraulic field or exposure model for bare structural faces.

## Analytical and corruption checks

T3/T6/Q4/Q8 column tests lower an above-ground head from 3 to 1 m with
0.4 release, then 0.5 of the remainder, then full release. With unchanged
geometry and fully saturated soil, the actual surcharge corresponds exactly
to heads 2.2, 1.6 and 1.0 m, while every stage's pore output still targets
1.0 m. A final dry stage recovers the dry bulk weight and zero water load.

Replacing the saved target pressure with the interpolated apparent head is
detected as invalid evidence. Corrupting a previous wet committed stress
breaks the next retained-force check. Missing initial pressure blocks remain
unsupported. In actual drawdown/rewetting stages with unchanged topology,
the water resultants obey the exact weighted recurrence and retained release
vanishes to roundoff.

## Executed three-mesh history

`scripts/f7_partial_hydrostatic_audit.py` executes ten stages on each of
h=2.5, 1.8 and 1.2 m, keeping the loaded native pile/anchor excavation:

1. Full pile installation with head 0 m.
2. First wet lift, release 0.4.
3. Same lift, 0.5 of the remainder (0.7 cumulative).
4. Complete that lift and install the anchor at full stage load.
5. Target head -2 m, partial drawdown 0.4.
6. Complete drawdown to -2 m.
7. Second lift under lowered head, release 0.4.
8. Complete the second lift.
9. Target head 0 m, partial rewetting 0.5.
10. Complete rewetting.

All **30 mesh/stage budgets passed**, with no solver exceptions. Maximum
absolute nodal force residual: 2.876e-11 kN/m; maximum global moment residual:
1.001e-11 kN·m/m.
[Raw stage/node evidence](data/f7/2026-11-04/partial_hydrostatic_audit.json).
This is local execution in the previously recorded environment, not a claim
that the updated GitHub workflow has already completed.

```bash
QT_QPA_PLATFORM=offscreen OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 NUMBA_NUM_THREADS=1 \
  PYTHONPATH=src python scripts/f7_partial_hydrostatic_audit.py \
  --output /tmp/f7-partial-hydrostatic.json
```

The dedicated workflow now runs this history after the full-stage wet case,
uploads its JSON and includes status/stage count in the job summary.

## Remaining scope

The audit retains the 1e-6 dimensionless assembly tolerance. Soil must be
elastic and drained; sections/materials must remain unchanged. Full stages
may activate supports; partial stages may remove elements but cannot activate
new soil, beam, bar or interface elements. Their initialization needs an
additional constitutive reference. Seepage, nonhorizontal heads, undrained
pressure, imposed displacements, seismic forces and curved loaded edges are
also unsupported.

Bulk saturation is still evaluated at Gauss points and joint water still
uses the nodal tributary rule. Their previously documented water-table-cut
accuracy limits remain. Numerical equilibrium is not independent physical
validation or mesh convergence. The next water extension is seepage-derived
pressure evidence; partial-stage activation and physical benchmarks remain open.
