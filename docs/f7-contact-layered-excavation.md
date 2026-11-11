# F7 — Exact layered removal with normal contact

## Scope and dependency

This fixture-level benchmark follows PR #86. At authoring, #86 is still open and
all of its CI jobs passed; this change is stacked on that branch, not merged main.
The public full-stage, partial-stage, activation and temporary-support audits retain
their existing rejection of changing continuum topology. This change does **not**
relabel those APIs as general excavation audits and changes no production solver,
material law, user interface or tolerance.

The new benchmark actually runs `api.run` / `StaticSolver` for monotone element
removal in a known elastic specimen. It does not substitute a reduced Newton solver
or synthetic stress arrays for a native solution. Closed-form values are test targets.

## Specimen and history

The width is 2 m. Two lower layers share ordinary continuum nodes and span y=-2..0.
A separate upper layer spans y=0..1. Its bottom contacts the lower body's top using
straight IFACE4 or IFACE6. Bottom and top restraints give each body real independent
support; there is no artificial stabilizing spring. Transverse displacement is
constrained, producing a constant constrained modulus C=2400 kPa for E=2000 kPa and
nu=0.25. Normal penalty stiffness is 2000 kPa/m and initial clearance is 0 or 2 mm.

Eight accepted stages load the specimen, remove middle region 2 at alpha=0.25,
continue its release at alpha=0.5, finish the release, remove remaining lower region
1, and continue loading/unloading the surviving upper body. The requested interface
tag remains enabled throughout; native face adjacency must deactivate it when its
lower adjacent element disappears. Its gap/tractions then become NaN and status 255,
not fabricated zero contact values. Disappearing continuum nodes must likewise have
NaN displayed displacement, zero reaction and zero removed stress history.

The 24-case workflow varies element order (Q4/IFACE4, Q8/IFACE6), clearance, 0/90-degree
translated frames and force/displacement/mixed control. Regression tests additionally
exercise one and four elements across the width. This is exact-solution reproduction
on several meshes, not an observed convergence-order estimate for a nonlinear model.

## Independent scalar reference

All stresses use tension-positive signs. Let `sL` and `sU` be the uniform vertical
stresses in the lower and upper continuum, `a` the lower contact displacement, `b`
the upper contact displacement and `v` the prescribed top displacement. Quantities
`q1`, `q2`, `h1`, `h3` below are forces divided by the width.

Before removal, lower-body compliance is 2/C and upper-body compliance is 1/C:

```
t = min(0, kn * (g0 + v + (q2+h3)/C - 2*(q1+h1)/C) / (1+3*kn/C))
sL = q1+h1+t
sU = t-q2-h3
a = 2*sL/C
b = v-sU/C
```

Physical load history is interpolated from the previous **actual** load. When
region 2 is removed, the lower loaded nodes disappear. Their previous load is
projected out before interpolation; it cannot be transferred to a new boundary or
retained as a fictitious applied force. At the newly exposed lower surface,
`h1=(1-alpha)*sL_previous`. At the upper contact surface, now disconnected,
`h3=(1-alpha)*(-sU_previous-q2_previous)`. The remaining lower-layer stress is h1;
upper stress is `-q2_actual-h3`. In all cases
`v_actual=(1-alpha)*v_previous+alpha*v_target`.

The reference uses no stored native stress, native stiffness, private applied-force
vector, native residual or native contact integration utility. It advances its own
scalar state. Prescribed targets and analytical dimensions are the only inputs.

### Hand-derived mixed-control check

For zero initial clearance immediately before the first excavation:

- lower stress = -389/42 kPa;
- contact traction = -142/21 kPa;
- actual upper applied force = -14 kN/m and lower applied force = -5 kN/m.

After removal at alpha=1/4, the remaining physical load is -13 kN/m, **not** -16.75.
The lower -5 kN/m load was on deleted nodes. Separately, retained release forces are
-389/28 kN/m on the surviving lower layer and +71/7 kN/m on the upper layer.
Their sum is -3.75 kN/m. The next half stage retains half of each release term.
A full stage removes those terms exactly. Regression assertions use these rational
values directly rather than generate them from native results.

## What is compared

Every active Gauss stress (including transverse and out-of-plane components), every
active nodal displacement relative to original geometry, all nodal reactions, gap,
traction, contact state, activity mask, inactive-node representation and accepted
fraction are compared. Report-datum resets are reconstructed without resetting the
physical geometry. Repeated stage names remain ordered indices.

Full nodal reaction targets use independent constant-stress boundary integrals on
rectangular element edges: L*(1/2,1/2) for Q4 and L*(1/6,1/6,2/3) for Q8. Opposite
shared edges cancel. Contact uses equal/opposite normal contributions. This checks
individual reactions, not merely a global sum that could hide equal/opposite errors.
Separate original-coordinate global forces and moments are checked as well.

Physical-only classification examines nodal residuals without numerical retained
release. A partial stage can have zero global sum but still carry equal/opposite
unfinished release on disconnected bodies. That stage must **not** be called
physical-only equilibrium. No new physical acceptance criterion is added to the
production solve.

## Reproduction and evidence

```
PYTHONPATH=src python scripts/f7_contact_excavation_benchmark.py \
  --output f7_excavation/excavation.json \
  --example f7_excavation/layered-excavation.ssproj
python -m pytest tests/verification/test_f7_contact_excavation_benchmark.py
```

The dedicated `f7-contact-excavation` workflow retains prior native/contact/audit
tests, requires complete unskipped JUnit and all 24 models / 192 stages, and archives
strict JSON, the solver log, a solved project and exact tracked-source provenance.
A saved project is a result snapshot and re-solvable input, not a nonlinear restart.

The test suite falsifies finite and nonfinite stress, displacement, gap, pressure,
status, activity, fraction and reaction evidence; rejects missing/extra stages and
missing maps; verifies old general-audit rejection; and checks JSON/HDF5/project
roundtrips and nonmutation. A run that does not complete all expected stages fails.

## Explicit non-claims

This is a dry, stress-free, zero-gravity, plane-strain, fixed-normal, elastic-layer
benchmark with monotone removal and stable surviving supports. No nonlinear soil,
reactivation/backfill, disappearing-node restart, hydraulic/frictional contact,
piles/anchors, arbitrary excavation geometry, experimental calibration, design
capacity, or RS2/PLAXIS/OGS comparison is established by it. The full continuum
excavation audit with arbitrary topology is still a separate task.
