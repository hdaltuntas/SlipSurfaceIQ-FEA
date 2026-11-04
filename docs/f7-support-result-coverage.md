# F7 — Staged structural output and activation coverage

The supported-excavation audit now requires explicit, auditable coverage
of pile, anchor and zero-thickness interface results, in addition to the
existing mesh/stage row coverage introduced in PR #54.

## Integrity criteria

For every declared beam/liner, bar/bolt and interface block, the
`stage_support_result_coverage` diagnostic checks:

- The activity mask and stage result array are present.
- The mask and result shapes match the element count and physical type.
- Active element results are finite (beam N/V/M at both ends; bar N;
  interface effective shear/normal tractions).
- Inactive element results are NaN, not fabricated zero forces.
- When an expected active support set is provided, each requested
  support is fully active and each unrequested support fully inactive.

Missing outputs or incorrect activation are reported as `failed`
(or `missing` in per-tag detail) rather than silently omitted.

The optional three-resolution study in
`examples/f7_excavation_mesh_audit.py` now stores a
`support_result_coverage` report for every solved stage, using the
canonical stage's declared `active_structures`.

This is a structural data-integrity test, not an independent mechanics
benchmark: a finite pile moment or anchor force may still be physically
incorrect. Also, the current overall command-line exit status is governed
by the mesh/stage coverage gate; support coverage failures are explicitly
reported but not yet treated as complete physical acceptance.

## Remaining F7 work

Run the full supported-excavation study across all three mesh resolutions.
Compare support N/V/M profiles, bar axial forces, interface tractions,
water pressure, and support reactions with independent physical
references. An output-coverage pass is necessary but not sufficient
for model verification.
