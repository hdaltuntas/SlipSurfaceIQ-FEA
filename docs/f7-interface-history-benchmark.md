# F7 interface histories: constitutive verification and the contact-gap limitation

## Scope

This benchmark extends PR #74 from zero-state single increments to committed
loading histories. It does not change the production constitutive implementation.
Four prescribed histories run on IFACE4 and IFACE6 at 0, 37 and -63 degrees:
frictional shear reversal, dilatant shear reversal, zero-tension normal
opening/reversal, and shear/tension-corner unloading and reverse loading.
There are 24 histories and 228 committed increments.

For every increment, the reference advances its own plastic-jump memory:

```
t_trial = diag(ks, kn) * (total_jump - reference_plastic_jump)
t_expected = labelled_closed_form_branch(t_trial)
reference_plastic_jump = total_jump - diag(ks, kn)^(-1) * t_expected
```

The scalar branch formulas are reused from `f7_dilatant_interface_benchmark.py`.
No native stress, force, stiffness or integration weight is used to update
reference memory or construct reference forces. Branch labels are specified by
the fixture, validated for admissibility, and kept away from switching points.
This is verification of selected paths of the implemented mathematical law,
not an independent experimental material calibration.

The native side advances from its previously committed traction. Each step
first evaluates and discards a different trial, then evaluates the selected
increment twice. Every element degree of freedom is perturbed from the same
committed state for a centered-difference tangent check. Only the selected
increment is committed; rejected trials and derivative evaluations must leave
the committed state unchanged. Independent shape-function integrals check
full nodal forces and full tangent matrices with separate dimensional scales.

Analytical comparisons use a normalized tolerance of 1e-9; finite differences
use 1e-6. Tests also compare four subincrements with one increment along the
selected straight shear/normal paths. This is not an assertion of arbitrary
step-size independence for every multisurface path.

## Important finding: tensile cap is not unilateral geometric contact

The existing interface stores tractions and applies an incremental
elastoplastic tensile cap. It has no separately evolving geometric-gap contact
state. For a zero-tension normal history with `kn = 2000 kPa/m`, an initially
coincident interface opened to 6 mm has zero normal traction. Reversing the
opening to 5 mm produces **-2 kPa** in the current mathematical law, even
though the absolute geometric separation is still positive.

A distinct, unbonded, zero-reference-gap linear penalty contact comparator is

```
sigma_contact = min(kn * geometric_gap, 0)  # tension-positive convention
```

That comparator predicts zero normal traction at 5 mm separation. The side-by-
side report therefore labels `unilateral_contact_gap_comparison` as
`not_equivalent`, not as a passed physical opening/closure check. This finding
must not be hidden behind a green constitutive-history test. It is a model
scope distinction, not evidence that the incremental return equations were
implemented incorrectly. Future physical-contact work needs an explicit
contact/gap state, appropriate reclosure and slip rules, solver lifecycle
integration, persistence, and separate reference tests.

The distinction is consistent with primary contact-model documentation:
Itasca's linear contact is active only for nonpositive surface gap, and its
flat-joint normal law gives zero stress in an unbonded region with positive
gap. Those sources motivate the comparator; no comparison run against Itasca
or another commercial program has been performed.

Sources (accessed 6 November 2026):
- Itasca, Linear Model, Activity-Deletion Criteria:
  https://docs.itascacg.com/itasca900/common/contactmodel/linear/doc/manual/cmlinear.html
- Itasca, Flat-Joint Model, normal stress/gap relation:
  https://docs.itascacg.com/itasca940/common/contactmodel/flatjoint/doc/manual/cmflatjoint.html

## Running and interpreting the output

From the repository root with the core dependencies installed:

```bash
PYTHONPATH=src python scripts/f7_interface_history_benchmark.py \
  --output f7_audit/interface_history_benchmark.json
```

The normal F7 step fails on constitutive-history, flag, force, tangent or
trial/commit integrity errors. Its summary separately prints the contact-gap
comparison and explicitly states that physical gap closure is not established.
Existing three-mesh excavation and coupled-budget gates are preserved.

To request the stronger contact-equivalence contract explicitly:

```bash
PYTHONPATH=src python scripts/f7_interface_history_benchmark.py \
  --require-unilateral-contact --output f7_audit/contact_requirement.json
```

That request currently exits nonzero while still writing the evidence; it does
not relabel `not_equivalent` as a physical pass. Neither command verifies
fatigue, bond degradation, general load histories, groundwater, curved or
axisymmetric interfaces, or the complete soil-pile-anchor excavation model.

## Regression coverage

The 53 pytest cases include the 24 history/orientation combinations,
hand-calculated rational stress paths, selected substepping checks, deliberate
history-reset/state-mutation/traction/force/tangent/flag/NaN corruption,
invalid geometry and reference inputs, missing contact data, and CLI contract
handling. NaN observations are retained as failed checks with JSON-safe nulls.
