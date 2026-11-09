# F7 — Fixed-topology partial-stage normal-contact equilibrium

## Added scope, unchanged original checks

PR #83's full-stage `contact_stage_equilibrium` and its existing regression tests
remain unchanged. The separate `contact_partial_equilibrium_by_stage` audit supports
accepted `Stage.load_split` fractions below one under **fixed active topology and
fixed prescribed-DOF membership**. The production solver, contact law, reactions,
residual tolerances, GUI and persistence formats are not changed.

The bounded contract is dry drained plane strain, stress-free `InitialStress("none")`,
zero gravity, full Newton, constant continuum materials and persisted point/uniform
straight-edge loads. Each contact must keep its initial activation state throughout
the audited sequence. Prescribed displacement VALUES may change, but the set of
prescribed components must remain unchanged. Reporting datum resets are allowed.

Changes in support membership, contact activation, excavation or material assignment
need a retained-release/initialization reference and are explicitly unsupported here.
The pre-existing full-stage audit still supports its original contact off/on cases;
this separate history API does not weaken or replace that audit.

## Load history, not a target multiplier

For stage i, alpha_i is the accepted fraction and must equal the model's declared
`load_split`. The applied nodal external force is

```
F_i = (1 - alpha_i) F_(i-1) + alpha_i F_target_i,   F_initial = 0.
```

F_(i-1) is the previous ACTUAL load, not its unreached target. For example,
targets 10, 20, 0 with fractions 0.5, 0.25, 0.5 give applied forces 5, 8.75,
4.375. Repeating a target of 10 at fraction 0.5 gives 5, 7.5, 8.75 — not 5
at every stage. A fraction of one discards previous load weights for the current
target; a partial unload can retain a nonzero applied force even at zero target.

This recurrence follows the native staging contract documented in `fem/static.py`,
`StaticSolver._applied_force` and `fem/nonlinear.py`. No access to those private solver
vectors or functions is used by the audit. Independent point/edge load assembly yields
both nodal forces and analytical resultants/first moments. Their stage recurrences are
compared about the requested moment origin. For this fixed-topology/support contract,
the previous equilibrated internal force equals the previous applied force on free
DOFs, so there is no retained release source. Contact opening/closure under the same
active law is a constitutive response, not a change to the declared active topology.

## Reassembly and rejection behavior

A shallow, read-only reassembly view gives the unchanged full-stage evaluator the
reconstructed applied point loads and complete-stage metadata. Original stored stress,
gap, traction, reaction and activity arrays are neither overwritten nor re-solved.
The ORIGINAL fractions/identities are checked before this view is formed and are
recorded in the new `load_history` output. This view is an implementation reuse for
force checks, not a claim that the native partial stage solved its full target.

The verified zero-stress/zero-load initial snapshot is required. The audit checks every
node, continuum-connected component, global force/moment, reaction support and stored
gap/pressure law with the existing checks. Continuum shape functions and quadrature
are shared with the library: this is not a second independent finite-element solver.
Contact geometry/weights and applied-load first moments are independently reconstructed.

Missing, malformed, inconsistent or nonfinite evidence is `invalid`; valid models
outside the fixed-topology contract are `unsupported`; a measured imbalance is
`failed`. After ANY unsuccessful stage the dependent suffix is `blocked`, even if a
later stage has alpha=1. A missing initial reference blocks the whole sequence. A bad
history therefore cannot be hidden by showing only a later successful-looking record.

## Native evidence and independent analytical fixtures

Run from the repository root with its core dependencies installed:

```
PYTHONPATH=src python scripts/f7_contact_partial_benchmark.py \
  --output f7_contact_integration/contact_partial_equilibrium.json
```

The script solves 20 actual `api.run` / `StaticSolver` models and 132 user stages:

- 12 uniform Q4/IFACE4 or Q8/IFACE6 histories: two clearances, force/displacement/mixed
  control, seven partial/full stages each. Exact elastic layer/contact equilibrium
  checks absolute gap, pressure, top/base reactions and actual external forces.
- Eight multi-element eccentric histories: point and uniform edge loads, translated
  geometry, 0/90-degree frames, two clearances, six stages each. Contact remains
  declared active; these verify equilibrium, not an exact pressure patch solution.

Fixture applied forces and prescribed top displacements are computed using a separate
closed sum of products, `sum(alpha_j * target_j * product(1-alpha_k, k>j))`, instead of
calling the audit's nodal recursion. Uniform references use C=2400 kPa, H=1 m, L=2 m,
kn=2000 kPa/m. For top displacement v and total bottom force F, q=F/L and k=C/H:

```
u_bottom = v + q/k                              (open: v + q/k >= -g0)
u_bottom = (q + k*v - kn*g0)/(k + kn)             (closed)
gap = g0 + u_bottom
sigma_n = kn * min(gap, 0)
R_top = L*k*(v - u_bottom),  R_base = -L*sigma_n
```

The prior 8-model/56-stage exact benchmark, 16-model/104-stage full equilibrium
benchmark and existing tests are retained in CI. The new JSON has a separate failing
exit status and completeness gate; missing/skipped evidence is not accepted. There
are no new arbitrary engineering convergence limits: numerical force/moment tolerances
remain 1e-8 with rtol=1e-8, and the exact-fixture gap tolerance is 1e-10 m.

## Non-claims

No hydraulic/gravity, frictional or mixed-Goodman contact, beams/bars, changing active
continuum topology, support release, contact activation, arbitrary unpersisted custom
tractions, nonlinear restart or design-capacity certification is added. Result snapshots
are still not restart checkpoints. Native equilibrium and bounded layer references are
not a general physical excavation validation or an RS2/PLAXIS comparison.
