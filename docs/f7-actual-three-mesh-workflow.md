# F7 — Execute the real three-mesh pile/anchor excavation

The optional supported-excavation script has accumulated strict data
integrity and assembly checks (PRs #54–#58), but green unit tests do
**not** mean that the complete staged FEM problem was actually solved
at three resolutions.

This change adds a separate GitHub Actions workflow,
`.github/workflows/f7-supported-excavation.yml`, to run the **real**
native excavation model with the existing independent mesh builds at
`h = 2.5, 1.8, 1.2 m`. The actual model has a pile, skin interfaces,
an anchor and two excavation lifts; no synthetic force rows are
substituted for the solver output.

## Evidence retained

On completion or failure, the job uploads the audit's actual JSON and
CSV artifacts and `f7_audit/solver.log` (captured standard output and errors),
together with a GitHub job-summary containing the
completed stage count, mesh/stage coverage, structural-output coverage,
interface-moment acceptance and mesh/solver failure count.

Run from GitHub Actions under **f7-supported-excavation** (manual
`workflow_dispatch`), or inspect the pull-request-triggered run.
The job fails if the existing script exits nonzero: missing mesh/stage
rows, solver errors, structural coverage failures and active interface
moment failures are not silently accepted.

This is intentionally a **separate, potentially expensive workflow**
rather than an additional task in the fast Python 3.10–3.13 CI matrix.
Its job timeout is 45 minutes; actual runtime and convergence cannot
be assumed before a completed run has been inspected.

## Interpretation

A green run would demonstrate that all requested stages completed
on three generated meshes and passed the implemented bounded checks.
It would **not** by itself certify physical N/V/M, groundwater seepage,
anchor design or independent RS2/Plaxis agreement.

The resulting artifacts must be examined for support-profile changes,
global reactions, plasticity, interface force/moment transfer and
numerical convergence. Unsupported reference cases remain
unsupported and are not replaced by fabricated passing metrics.
