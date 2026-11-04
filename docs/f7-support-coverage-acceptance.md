# F7 — Fail-closed structural coverage acceptance

The existing optional three-resolution supported-excavation audit
`examples/f7_excavation_mesh_audit.py` produces a per-stage
`support_result_coverage` diagnostic. Previously this was informational:
a run could exit successfully even when the pile, anchor or interface
results were missing, nonfinite, or incorrectly active.

This package makes the **integrity check** part of the optional audit's
exit-status gate, independently of the existing mesh/stage completeness
gate.

For every requested (mesh size, excavation stage) pair, the gate requires
exactly one row with a completed `support_result_coverage` report.
Every declared support must have a distinct identity, matching element
counts, and a passing structural result-coverage status. Missing,
duplicated, unexpected, incomplete and failed records remain explicit.

The final `excavation_mesh_audit.json` contains
`support_coverage_acceptance`, including expected rows and passed,
failed and missing counts. The optional CLI returns exit code 1 if
either mesh/stage coverage is incomplete or this structural integrity
gate fails.

The tests deliberately corrupt individual pile/interface coverage
records, remove a support result or a mesh/stage row, duplicate identities,
and add unknown stage rows. None may produce a passing report.

## Engineering scope

This gate cannot establish **physical correctness** of pile N/V/M,
anchor axial force, interface traction, or a support's interaction with
the continuum. Finite output values and the expected activation
sequence are necessary but insufficient for mechanical validation.

Separate F7 work is still required to execute the full three-resolution
supported excavation case and compare structural force transfer, global
external loads/reactions, and groundwater pressure against independent
physical references.
