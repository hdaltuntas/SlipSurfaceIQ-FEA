# Partial contact activation: retained-release equilibrium

This extension follows the full-stage (#83) and fixed-topology partial-stage (#84)
audits. Neither is weakened. It adds a separate audit for removal/reactivation of
unilateral normal contact in a bounded, always-supported two-body setting.

## Distinct physical and numerical loads

For the accepted fraction `a_i`, reconstruct physical loads from persisted point and
uniform straight-edge loads, starting at a verified zero-load initial snapshot:

```
F_i = (1-a_i) F_(i-1) + a_i F_target_i
I0_i = soil_internal(stress_(i-1))
       + contact_internal(current_active_contacts, total_u_(i-1))
H_i = (1-a_i) P_free (I0_i - F_(i-1))
I_i - F_i - R_i - H_i = 0
```

`P_free` suppresses prescribed DOFs. Recorded reactions are defined relative to the
physical applied load, not to `I0`. `H` is the retained portion of the stage's
unbalanced force, **not another physical load** and not a contact action to count
again globally. The preceding unfinished release is already represented in stored
stress; it is not discarded if the following stage has unchanged contact activity.
A full stage has `H=0` exactly. Contact forces are assembled as equal/opposite nodal
contributions before projecting out the prescribed DOFs.

The report keeps `physical_external_resultant`, `retained_release_resultant`,
`effective_external_resultant`, `physical_global_residual` and
`effective_global_residual` separate. Its node and component checks include `H`.
A physical-only balance need not vanish during a partial release. Conversely, a
vanishing global sum does not prove each body is balanced: equal/opposite retained
forces may cancel globally while both bodies require a nonzero numerical load.
The report includes all start/internal, applied and retained nodal arrays for review.

The first uniform force-control fixture starts with `-16 kN/m`, `kn=2000 kPa/m`
and two identical `2400 kPa/m` constrained layer stiffnesses. Initial contact
traction is `-2.5 kPa`; each face resultant has magnitude `5 kN/m`. Removing
contact at `a=0.25` leaves `-3.75/+3.75 kN/m` on the two bodies. A following
unchanged off-stage with `a=0.5` reduces those to `-1.875/+1.875 kN/m`.
The new physical applied force in the removal step is `-17 kN/m`, not a load
increased by counting both retained contact faces again.

## Geometric reference and deliberately restricted scope

Both faces must belong to unchanged active continuum, and **every model node must
remain a continuum node**. Prescribed-DOF membership must remain fixed. These
conditions exclude hidden fresh-node displacement reference resets. Starting from
zero displacement, the audit reconstructs total nodal displacement from each stored
reported displacement and the explicitly declared reporting reset: on reset, the
new datum is the preceding total displacement. This is a read-only audit reference,
not a new recovered gap in the GUI and not a restart checkpoint.

At a transition, for each currently active contact point:

```
g_start = initial_gap + n dot (u2_previous_total - u1_previous_total)
sigma_start = kn * min(g_start, 0)
```

An inactive snapshot's NaN contact gap is never replaced by zero or reused as an
active stress. Reactivation uses the known geometric reference. Current stored gap
is separately checked against current total geometry, and prescribed displacement
values are checked against their own partial-step history.

Existing dry, drained, stress-free (`initial='none'`), zero-gravity, plane-strain,
full-Newton and straight IFACE4/IFACE6 restrictions remain in force. Whole contact
tags may change activity; material changes, mixed Goodman contact, beam/bar elements,
changing continuum activity, support removal, contact-only nodes disappearing,
hydraulic terms, custom unpersisted tractions and nonlinear restart are unsupported.
Every result stage must match the model's original name/index and fraction. Invalid
initial evidence or any failed/unsupported predecessor blocks later claims, including
later full stages. Duplicate stage names remain distinct indices.

Contact weights/normals are calculated from geometry, not from the native contact
group. Continuum quadrature is shared with the library, so this is an independent
force reconstruction, **not a second independently implemented FEM solver**.

## A real predictor failure found by the new fixture

The pure displacement-controlled reopening/reclosure fixture exposed a premature
`nonfinite_or_divergent` decision. At a first predictor from an open, force-free
contact, the two bodies can move rigidly until the gap closes. The free contact nodes
then have finite out-of-balance forces, but the driven-support reaction reference can
still be essentially zero. A large normalized residual at that point does not prove
the first Newton correction diverges. The baseline failed at stage 7 (zero clearance:
last accepted factor approximately 0.0588; 2 mm clearance: approximately 0.2940).

The correction uses the **already existing optional arithmetic force scale only in
the first displacement-predictor divergence guard** (`it==1`, displacement driven,
callback present). It does not alter the residual, contact tangent, convergence
normalization, force/energy tolerances, roundoff acceptance, later-iteration guard,
or models without this callback. The fixture must still receive a Newton correction
and satisfy the original convergence conditions. A scalar two-body regression checks
that the large initial residual is not accepted, ordinary no-callback behavior is
unchanged, and genuinely divergent iterations are rejected without committing.
No new stabilization spring, physical force floor or contact stiffness is introduced.

## Reproducible verification

```
PYTHONPATH=src python scripts/f7_contact_activation_benchmark.py \
  --output f7_contact_integration/contact_activation_equilibrium.json
python -m pytest tests/verification/test_f7_contact_activation_equilibrium.py
```

There are 24 uniform cases (two element types, two clearances, three control modes,
two frame orientations) and eight eccentric cases, each with nine accepted stages.
The **32 native `api.run` models / 288 stages** cover removal, incomplete release,
holding, reactivation, opening, reclosure, explicit datum resets and duplicate names.
The scalar two-layer closed form independently supplies displacement, pressure,
reactions and retained-force targets for uniform cases. Eccentric distributed/point
loads verify equilibrium and analytical applied moments; no exact nonuniform contact
patch or displacement solution is claimed.

Existing 8-model/56-stage, 16-model/104-stage and 20-model/132-stage benchmarks remain
mandatory. The integration job adds the new tests, separate error-gated JSON/log and
completeness assertions. The old full-stage and fixed-topology audits continue to
reject this new partial-activation contract. Neither a capacity check nor experimental
or RS2/PLAXIS physical validation is claimed.
