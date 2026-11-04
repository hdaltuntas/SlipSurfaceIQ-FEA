# F7 — Full-stage hydrostatic soil/pile/anchor force budget

The subsequent [incremental horizontal-head audit](f7-incremental-hydrostatic-budget.md)
now covers partial wet stages and changing water levels through a separate
history-aware API. This full-stage API retains its stated contract.

`coupled_hydrostatic_stage_budget` extends the shared nodal reconstruction
to explicit **horizontal piezometric** stage heads. The dry and incremental
dry APIs retain their existing restrictions. The new audit includes:

- effective continuum stresses and actual beam/bar/interface forces;
- dry/saturated soil body forces evaluated at the continuum Gauss points;
- independently derived continuum pressure `p=gamma_w*max(head-y,0)` and
  its nodal contribution `integral(B.T*m*p)`, with `m=(1,1,1,0)`;
- interface water forces from straight-face trapezoidal/Simpson tributaries;
- exact piecewise hydrostatic pressure on exposed straight continuum edges;
- applied straight surface/point loads and recorded boundary reactions.

Each saved active pressure sample is also compared with the independent head
formula. Missing pressure blocks or nonfinite active samples are unsupported;
a finite pressure mismatch contributes to a failed normalized audit. Nonzero
undrained excess pore pressure is outside this contract.

## Reaction convention

The solver deliberately omits exposed-boundary water loads at prescribed DOFs
so that reported reactions are total (effective plus water). The new reference
maps each water contribution to its tied owner node and applies the same
prescribed-DOF convention. It retains three separate boundary summaries:

- `unfiltered_boundary_water_resultant`: exposed continuum water pressure
  before prescribed-DOF suppression;
- `withheld_boundary_water_resultant`: the omitted prescribed components;
- `water_resultant`: continuum, joint and actually applied boundary water
  contributions used with the reported reaction.

The checked equation is effective internal force minus bulk body force,
applied loads, continuum pressure, joint pressure, applied boundary pressure
and reaction. Structural owner-node records retain each water term separately.
Interface faces are excluded from the exposed-continuum boundary set, including
inactive interfaces, following the current FEM topology contract. This does
not independently model hydraulic exposure of bare structural faces.

## Fixed water-table intersection integration

The new reference exposed a solver error at a water table cutting a straight
boundary edge: unsplit Gauss integration crossed the pressure kink. The solver
now splits known horizontal-head straight edges at that intersection before
integrating. For a vertical edge y=-2..0 and head=-1, exact linear nodal pressure
integrals are `gamma_w*(5/12,1/12)`; quadratic values in endpoint/midpoint order
are `gamma_w*(7/24,-1/24,1/4)`. The negative quadratic endpoint contribution
is a consistent nodal load, not clipped to zero.

Analytical tests cover both element orders and plane-strain/axisymmetric
integration, including the first moment. A free-side column whose boundary
is cut by the head now closes against the independent reference. Curved edges
and interpolated seepage nodal pressures retain their existing solver route;
the new coupled audit explicitly declines those cases.

## Actual loaded saturated excavation

`scripts/f7_hydrostatic_excavation_audit.py` runs the existing three-stage
pile/anchor geometry at h=2.5, 1.8 and 1.2 m with horizontal head y=0,
unsaturated unit weight 18 and saturated unit weight 20 kN/m³. The right-top
pressure/shear and pile-head point force from the loaded dry audit are retained.
All soil integration points are saturated in this particular reference case.

All **nine actual mesh/stage budgets passed** after the integration fix,
with no solver exceptions. Maximum absolute nodal force residual:
2.876e-11 kN/m; maximum global moment residual: 8.186e-12 kN·m/m.
All nine independent analytical comparisons passed:

- soil weight `(420-30*i)*20`, plus the unchanged pile weight;
- soil-weight moment `-4500*i` about the global origin;
- applied force/moment `(-35,-305,-2250)`;
- water-resultant Fy `-15*2*i*9.81` and Mz `15*2*i*9.81*7.5`, from pressure
  on the excavated left terrace at depths 0, 2 and 4 m;
- reactions equal to the negative sum of those scoped external resultants.

Here `i=0,1,2` identifies the three stages. These checks validate bounded
numerical force accounting, not independent excavation design physics.
[Raw measured stage/node data](data/f7/2026-11-04/hydrostatic_excavation_audit.json).

```bash
QT_QPA_PLATFORM=offscreen OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 NUMBA_NUM_THREADS=1 \
  PYTHONPATH=src python scripts/f7_hydrostatic_excavation_audit.py \
  --output /tmp/f7-hydrostatic-excavation.json
```

The dedicated real-FEM workflow also runs this case, retains its JSON and
reports status/stage count. The artifact above is a local run; no completed
GitHub execution is inferred.

## Scope and next work

The existing 1e-6 dimensionless assembly tolerance is retained. Separate exact
column tests verify bulk weight and above-ground water surcharge for T3/T6/Q4/Q8.
Bulk weight in the general audit follows Gauss-point saturation, not exact
polygon-clipped wet volume. A mesh-cut water table can therefore retain bulk
weight discretization error despite assembly closure; see the separate
[exact-cut verification](f7-exact-water-table-clip.md). Joint water uses the
existing nodal tributary rule; water-table-cut joint integration still has
the separately documented [moment/refinement limits](f7-joint-water-moment-refinement.md).

Unsupported: seepage, nonhorizontal heads, curved/noncentral loaded edges,
separated joint faces, undrained soil, partial stages, imposed displacements,
seismic loading, changed materials and variable shotcrete sections.
Next: history-aware accounting for changing water conditions and partial wet
stages. Mesh convergence, independent physical benchmarks and user/release
acceptance remain open.
