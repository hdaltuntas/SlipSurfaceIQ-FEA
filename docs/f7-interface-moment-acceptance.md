# F7 — Active interface moment acceptance in excavation audit

PR #57 added signed force and moment transfer diagnostics for effective
interface tractions in the optional three-resolution pile/anchor excavation
study. They were report-only. An active skin interface could therefore
have a failed moment transfer check while the command still exited zero.

This change adds a **stage-aware acceptance gate** for those reports.

The expected active interface tags are obtained from the native model's
stage specifications, not inferred from the solver's reported outputs.
For every requested mesh and completed stage, all declared interfaces
must have a corresponding report. An interface expected to be active
must report a positive number of active elements, a `passed` status,
and a finite residual within its recorded positive tolerance.
An interface expected to be inactive must have zero active elements and
an explicit `unsupported` status; inactivity is not counted as a pass.

Missing or duplicated mesh-stage rows, missing report objects,
undeclared interface result tags, failed residuals, unexpected activity,
and nonfinite errors all fail the gate. Summary data lists each
mesh/stage/interface outcome and separates passed active checks from
not-applicable inactive checks.

The optional `examples/f7_excavation_mesh_audit.py` now writes
`interface_moment_acceptance` into `excavation_mesh_audit.json`
and exits nonzero if mesh-stage coverage, structural result coverage,
**or** active interface moment coverage fails.

This gate checks assembly consistency of the FEM interface's internal
effective-traction force and moment. It cannot serve as an
independent physical benchmark for global excavation equilibrium,
pile bending, bolt loads, hydraulic gradients or continuum response.
The full three-resolution supported-excavation study remains to be
executed and interpreted separately.
