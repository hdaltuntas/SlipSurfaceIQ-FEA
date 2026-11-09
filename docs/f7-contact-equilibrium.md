# F7: bounded nodal and external equilibrium for normal contact

## Why this follows the resultants viewer

PR #82 integrates contact actions, but equal-and-opposite internal forces can cancel
in the global sum even when each body's force transfer is wrong. The older
`coupled_dry_budget` covers a different contract (Goodman joints, gravity/K0 and no
prescribed displacement). Do not bypass its checks to make it accept normal contact.
This module adds a separate audit without changing either solver or existing gates.

`post.contact_equilibrium.contact_stage_equilibrium(result, index, origin=(0, 0))`
checks a **computed user stage**; index 0 means `result.stages[0]`, not the initial
snapshot. `contact_equilibrium_by_stage` returns every stage, keeping `passed`,
measured `failed`, `unsupported` scope and `invalid` evidence distinct. Empty or
incomplete stage sequences cannot give an overall pass.

## Bounded contract

Plane strain, dry drained continuum and explicitly selected unilateral-normal
interfaces only; initial stress `none`, no gravity, full Newton, complete load
factors and unchanged active continuum topology. Point loads, uniform straight
edge pressure/shear, prescribed displacements, report-datum resets and whole-tag
contact activation/deactivation are covered. Only explicitly inactive contact
contributes zero internal force; missing or malformed active evidence is rejected.

Gravity, water, undrained response, beams/bars, mixed Goodman joints, partial-stage
release, excavation and material changes are outside this audit. Unsupported
problems are not made acceptable by discarding terms or increasing tolerances.
Custom `StaticSolver.extra_tractions` callbacks are not persisted in SolveResult:
this audit is exclusively for the declared Model loads. Its benchmark calls plain
`api.run` and supplies no such callbacks. Snapshot files are not restart states.

## Reconstructed terms and signs

- Continuum nodal force is reassembled from stored Gauss-point stress with
  `sum(B.T * sigma * wdet)`. The audit shares the library's continuum shape
  derivatives/quadrature, but not its assembled residual or nodal force vector.
- Straight IFACE4/IFACE6 normals and endpoint/endpoint-midpoint weights are
  calculated from original coordinates. Stored normal tractions are assembled
  on **distinct node IDs**, never averaged by location. No native contact group
  is used to produce the audit forces.
- External point and uniform edge loads use the existing independent closed-form
  load integration, not the native load assembler. A separate analytical first
  moment is checked against the resultant of the reconstructed nodal loads.
- Reactions are taken from the snapshot, checked for finite shape, and may be
  nonzero only on prescribed, currently used translational DOFs. With no beams,
  a nonzero rotational reaction is rejected.

At every node, the budget is

```
r = f_internal_continuum + f_internal_contact - f_declared_load - reaction
```

The global external balance is `sum(load + reaction) = 0`, with a separate moment
about the requested original-coordinate origin. Internal contact forces are NOT
counted again as global external loads.

For each continuum-connected component, a second balance adds external loads,
reactions and **contact actions on the component**, the negative of native contact
internal contributions. Nodes belonging only to active contact (e.g. a fixed base)
are reported as a separate aggregate, not as a reconstructed continuum body. The
node-by-node criterion remains authoritative even if any aggregate cancels.

The stored gap/pressure pair is also checked against `sigma_n=kn*min(gap,0)`.
This is consistency with the selected law, not experimental validation of that law.
No gap is reconstructed from reset/reported displacements.

## Numerical tolerances and output

Default absolute tolerances are separately dimensioned: `1e-8 kN/m` for force,
`1e-8 kN*m/m` for moment and `1e-8 kPa` for traction, with relative tolerance
`1e-8`. Each comparison uses `atol + rtol*scale` in the same physical units. The
report retains tolerances, global vectors, each component budget and the worst
nodal residual with its individual contributions. These verification tolerances
are not design acceptance criteria and do not relax the native nonlinear solver.

Run the native numerical verification:

```
PYTHONPATH=src python scripts/f7_contact_equilibrium_benchmark.py \
  --output f7_contact_integration/contact_equilibrium.json
```

The script runs 16 models / 104 user stages: the eight existing exact uniform-layer
histories (56 stages), plus eight multi-element eccentric-load histories (48
stages). The latter include point and distributed normal/tangential loads, two
clearances, translated geometry, 0/90 degree frames, deactivation/re-activation
and reopening. Applied forces and first moments are also calculated directly
from fixture dimensions and prescribed load values. These new nonuniform cases
are **equilibrium checks, not closed-form displacement/contact-patch solutions**.

Regression tests deliberately corrupt stresses, contact pressure, gaps, reactions,
activity, stage identities and maps. They include errors that preserve zero net
force (and sometimes zero net moment) while violating local equilibrium. Model
snapshots are not mutated. HDF5 and project roundtrips preserve the audit results.

The existing `f7-contact-integration` workflow retains its original tests and
8-model benchmark, adds this independent audit step, requires complete unskipped
JUnit and expected benchmark coverage, and archives JSON/log evidence even on
failure. Standard CI remains separate. No GUI behavior, legacy Goodman mechanics,
SRF acceptance, full excavation validation or RS2/PLAXIS comparison is changed.
