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

## F7 mesh sensitivity diagnostics

The audit JSON now contains `mesh_sensitivity_diagnostics`, including
coarse-to-medium and medium-to-fine relative changes for each stage's peak
displacement, tagged beam moments, and tagged bar axial forces. Missing,
duplicated or nonfinite data are explicitly classified as incomplete.
The `diagnostic_only` status is **not** a passed convergence threshold:
spatial peak locations may differ between meshes. These descriptors do not
change the pre-existing execution integrity gate or imply external validation.
No acceptance tolerance is imposed until a justified benchmark is available.

## Engineering evidence review after execution

The workflow now runs `scripts/f7_evidence_review.py` against the *actual*
`f7_audit/excavation_mesh_audit.json`. It preserves
`f7_audit/f7_evidence_review.json` and `f7_audit/f7_evidence_review.md`
in the uploaded artifact and appends the Markdown review to the Actions
job summary. The review distinguishes gravity-balance passes from
unsupported dry-load and coupled excavation-force budgets, groups the
unsupported reasons, and lists measured structural profile differences.

A finest-pair beam-peak relative difference of at least 25% is highlighted
as an **investigation priority only**, not an acceptance or rejection
criterion. The magnitude of the corresponding peak is retained to avoid
misinterpreting a large ratio between small forces/moments. The review
never reports independent physical validation as achieved, and it does
not change the pre-existing solver acceptance exit status. Future work
must establish a complete coupled force budget and an independent
reference before defining engineering tolerances.

## Global interface-transfer ledger

The actual excavation JSON now also includes `interface_transfer_ledger`:
per mesh and stage, this combines nodal interface force residuals with
paired-face resultants and their integration reference errors. Missing
interface tags, nonfinite values, duplicate stages, and noncancelling
forces are explicitly failed. No active interfaces is *not applicable*,
not a pass.

These are **internal interface action–reaction consistency checks**.
Their completion cannot replace a full continuum–pile–anchor external
force equilibrium budget or an independent physical benchmark. The
existing F7 FEM execution integrity gate is unchanged.

## Fail-closed interface transfer acceptance

The real three-mesh audit now emits `interface_transfer_acceptance` and
requires that status to be `passed` for a successful process exit.
The new check cross-references the interface transfer ledger with the
**independently defined** activation schedule for every requested mesh
and stage. An expected-active interface stage must have finite,
within-tolerance transfer evidence and positive active-element count;
a stage without any expected active interfaces may be `not_applicable`
but cannot claim an active transfer pass. Missing or duplicated rows
and contradictory status flags fail closed.

This acceptance is deliberately bounded to internal interface
action/reaction integrity. It does **not** replace the unsupported
global soil/structure force budget, constitutive model benchmarks, or
independent RS2/PLAXIS comparison.
