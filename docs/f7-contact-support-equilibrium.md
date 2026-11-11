# F7 — Temporary displacement restraints, removal and reintroduction

## Scope and entry point

`contact_support_equilibrium_by_stage(result)` extends the independently
reconstructed contact-transition history to changing **stage displacement
restraints**. It does not modify `StaticSolver`, nonlinear convergence criteria,
contact constitutive mechanics, GUI or existing model defaults.

Select a temporary prescribed translation with `Stage.displacements`; omit that
entry in a later stage to release it, provided no permanent `Model.fixities` or
`Model.displacements` entry still prescribes the same DOF. `uy=0` means a real
zero-displacement restraint; it does NOT mean release. Normal-only constraints
can be aligned with x or y. The underlying model supports its original boundary
objects; this change is an audit, not a new arbitrary-normal constraint option.

The original full-stage, fixed-topology partial and contact-activation audit
contracts remain unchanged. In particular, the activation-only public audit
still rejects changing prescribed-DOF membership. A private shared history
implementation avoids maintaining two copies of the transition equations; the
new entry point explicitly opts into the expanded restraint contract.

Still required: dry drained plane strain, zero gravity, stress-free initial
state, full Newton, constant active continuum covering every mesh node, straight
IFACE4/IFACE6 normal contact and persisted model loads. Contact tags may switch
on/off alongside restraints. Excavation, hydraulic loads, friction, beams/bars,
material changes, disappearing nodes and unpersisted custom tractions remain
unsupported. Result files are snapshots, not nonlinear restart checkpoints.

## Equations and sign conventions

Let `P_i` be the current free-DOF projection, `alpha_i` the accepted stage
fraction, `F_i` the physical applied nodal force and `I0_i` the preceding
continuum internal force plus the **current-active** contact force at preceding
total geometry. Independently reconstruct:

```
F_i = (1-alpha_i)*F_previous + alpha_i*F_target_i
H_i = (1-alpha_i)*P_i*(I0_i - F_previous)
I_i - F_i - R_i - H_i = 0
```

`H_i` is the numerical retained-release vector. On newly released DOFs, the
previous reaction becomes part of the starting imbalance; it is not retained
as a current reaction. If contact activity also changes, its independently
reconstructed force change must be included. As a separate consistency check,
on released DOFs verify `I0_i-F_previous = R_previous + delta_contact`.
Reactions are used ONLY for this check, never as the source of the applied load
or retained-release reconstruction. Nodal and connected-body checks prevent
opposite incorrect reactions from hiding behind a zero global sum.

Current prescribed DOFs satisfy
`u_i = (1-alpha_i)*u_previous + alpha_i*u_target_i`, even when they were free in
the preceding stage. Reporting-datum resets do not reset their physical position
or the contact gap. Current free DOFs have zero reaction. When `alpha_i=1`,
`H_i=0`; all the benchmark's full stages pass physical-only equilibrium.

The report keeps transition equilibrium (`status`) separate from
`physical_equilibrium.status`. The latter deliberately excludes `H_i`, so it
can be `failed` during an otherwise consistent partial release. This is not a
failed native solve, nor certification of completed physical equilibrium.
No numerical tolerance is relaxed to turn such a record into a physical pass.

## Reproducible hand calculation

Uniform two-layer fixture: width 2 m, height of each layer 1 m, constrained
modulus 2400 kPa, `kn=2000 kPa/m`, zero initial clearance. At the initial full
stage, temporary upper-face displacement is -6 mm, upper-top displacement is
-8 mm, and applied upper-face force is -16 kN/m.

The scalar solution gives traction `-72/11 kPa` and temporary-restraint reaction
`688/55 = 12.509090909... kN/m`. On release with `alpha=0.25` and new target
-20 kN/m, physical applied load is -17 kN/m and retained force is
`516/55 = 9.381818181... kN/m`. The removed-restraint reaction is exactly zero.
A subsequent free stage with `alpha=0.5` retains `258/55 kN/m`; a full stage
removes the remaining term. Reference formulas do not use native stiffness,
returned reactions or the audit's reconstructed vectors to generate targets.

## Native fixtures and regression tests

Run:

```bash
PYTHONPATH=src python scripts/f7_contact_support_benchmark.py \
  --output contact_support_equilibrium.json
python -m pytest -q tests/verification/test_f7_contact_support_equilibrium.py
```

The script solves 24 `api.run` models / 216 user stages: IFACE4/IFACE6, clearances
0 and 2 mm, global frames at 0 and 90 degrees, and three histories (restraint
changes alone, restraint plus contact switching, eccentric partial-face clamp).
Uniform cases compare scalar layer displacements, pressure, base/top/temporary
reactions and retained forces. Eccentric cases verify equilibrium, NOT an exact
contact-patch/displacement solution. Stage index is not physical time.

Tests cover hand values, removal, partial/full release, reintroduction at a new
displacement, state/datum preservation, moment-origin translation, duplicate
names, missing/contradictory data, false balanced reactions, nonfinite input,
unsupported scope, unchanged prior contracts, roundtrips and CLI failure exit.
Removing the last real support is rejected by native singular/nonconvergence
handling; no fictitious stabilizing stiffness is added.

## Context, not external-software equivalence

Rocscience's [Free boundary documentation](https://www.rocscience.com/help/rs2/documentation/rs2-model/displacements/free)
distinguishes removing a restraint from imposing zero displacement. OpenGeoSys'
[ReleaseNodalForce documentation](https://doxygen.opengeosys.org/stable/df/dc8/ogs_file_param__prj__process_variables__process_variable__boundary_conditions__boundary_condition__ReleaseNodalForce.html)
describes a controlled release contribution to equilibrium. These are conceptual
references only: the recurrence above is derived from this repository's staged
residual, not asserted equivalent to either software's staging semantics.
No RS2/PLAXIS/OGS comparison, geotechnical capacity check or whole-excavation
physical validation is claimed. Shared continuum quadrature is not a second
independent finite-element implementation.
